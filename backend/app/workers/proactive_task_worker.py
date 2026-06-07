import asyncio
import json
import aioredis
from datetime import datetime, timezone
import structlog
import uuid
import os

# Import necessary components for the agent loop
from app.graph import create_graph
from app.core.model_router import ModelRouter
from app.tools.registry import ToolRegistry
from app.memory.cognee_setup import CogneeMemory
from app.memory.graph_setup import KuzuGraph
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.memory.retriever_tool import MemoryRetrieverTool

# Configure logging for the worker
logger = structlog.get_logger("aether.worker.proactive_task")

class ProactiveTaskWorker:
    """Consumes proactive tasks from a Redis Stream and dispatches them to the agent loop for execution."""

    def __init__(self, redis_url: str = "redis://localhost:6379", stream_name: str = "proactive_tasks_stream", consumer_group: str = "proactive_task_group"):
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = f"worker_{uuid.uuid4().hex[:8]}" # Unique consumer name for this instance
        self._running = False
        self.redis_client: Optional[aioredis.Redis] = None

        # Initialize agent components (each worker instance gets its own)
        self.model_router = ModelRouter()
        self.tool_registry = ToolRegistry()
        
        # Register core tools (ensure these are available to the worker)
        self.tool_registry.register(BrowserTool())
        self.tool_registry.register(PythonREPLTool())

        # Initialize memory components for the worker
        # KuzuDB path should be unique per worker if not using a shared/networked DB
        # For production, KuzuDB might be on a shared volume or a remote instance
        kuzu_db_path = os.environ.get("KUZU_DB_PATH", f"/tmp/aether_worker_{self.consumer_name}/kuzu.db")
        self.kuzu_graph = KuzuGraph(db_path=kuzu_db_path)
        self.cognee_memory = CogneeMemory(config={"kuzu_db_path": kuzu_db_path})
        self.tool_registry.register(MemoryRetrieverTool(self.cognee_memory))

        # Placeholder for checkpointer (needs to be configured for persistent checkpoints)
        # For production, this would likely be a Redis-backed or database-backed checkpointer
        self.checkpointer = None # TODO: Initialize a proper checkpointer (e.g., RedisCheckpointSaver)

        logger.info("proactive_task_worker.initialized", consumer_name=self.consumer_name, redis_url=redis_url)

    async def start(self):
        """Connects to Redis, initializes memory, and starts consuming tasks."""
        if self._running:
            logger.info("proactive_task_worker.already_running")
            return

        logger.info("proactive_task_worker.starting", consumer_name=self.consumer_name)
        self._running = True
        self.redis_client = await aioredis.from_url(self.redis_url)
        
        # Initialize Kuzu and Cognee memory for this worker instance
        self.kuzu_graph.initialize()
        await self.cognee_memory.initialize()

        # Ensure the Redis Stream consumer group exists
        try:
            await self.redis_client.xgroup_create(self.stream_name, self.consumer_group, id="$", mkstream=True)
            logger.info("proactive_task_worker.consumer_group_created", group=self.consumer_group, stream=self.stream_name)
        except aioredis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                logger.error("proactive_task_worker.xgroup_create_error", group=self.consumer_group, stream=self.stream_name, error=str(e), exc_info=True)
                raise # Re-raise if it's not just a busy group error
            logger.info("proactive_task_worker.consumer_group_exists", group=self.consumer_group)

        asyncio.create_task(self._listen_for_tasks())
        logger.info("proactive_task_worker.started_listening", consumer_name=self.consumer_name)

    async def stop(self):
        """Stops the worker and closes Redis connection."""
        logger.info("proactive_task_worker.stopping", consumer_name=self.consumer_name)
        self._running = False
        if self.redis_client:
            await self.redis_client.close()
        logger.info("proactive_task_worker.stopped", consumer_name=self.consumer_name)

    async def _listen_for_tasks(self):
        """Continuously listens for new tasks from the Redis Stream using a consumer group."""
        while self._running:
            try:
                # Read tasks using consumer group. Block for a short period.
                response = await self.redis_client.xreadgroup(
                    self.consumer_group, self.consumer_name, {self.stream_name: ">"}, count=1, block=1000 # Block for 1 second
                )
                
                if response:
                    for stream, messages in response:
                        for message_id, fields in messages:
                            payload_str = fields[b"payload"].decode("utf-8")
                            task_payload = json.loads(payload_str)
                            
                            logger.info("proactive_task_worker.task_received", message_id=message_id.decode(), task_id=task_payload.get("task_id"), consumer=self.consumer_name)
                            
                            # Process task in a separate asyncio task to avoid blocking the stream reader
                            asyncio.create_task(self.process_task(task_payload, message_id))
                            
            except asyncio.CancelledError:
                logger.info("proactive_task_worker.listener_cancelled", consumer=self.consumer_name)
                break
            except Exception as e:
                logger.error("proactive_task_worker.stream_read_error", consumer=self.consumer_name, error=str(e), exc_info=True)
                await asyncio.sleep(5) # Wait before retrying to prevent tight loop on persistent errors

    async def process_task(self, task_payload: Dict[str, Any], message_id: bytes):
        """Processes a single proactive task using the agent loop and acknowledges it upon completion."""
        task_id = task_payload.get("task_id")
        thread_id = task_payload.get("thread_id")
        task_description = task_payload.get("task_description")
        context = task_payload.get("context")
        user_id = task_payload.get("user_id")
        tenant_id = task_payload.get("tenant_id")
        priority = task_payload.get("priority")
        action_type = task_payload.get("action_type")

        logger.info("proactive_task_worker.processing_task", task_id=task_id, task_description=task_description, consumer=self.consumer_name)

        # Create the graph for this task execution
        graph = create_graph(self.model_router, self.tool_registry, self.checkpointer)

        initial_state = {
            "task_id": task_id,
            "task": task_description,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "messages": [{"role": "user", "content": f"{task_description}\n\nContext: {context}"}],
            "plan": [], "current_step": 0, "tool_calls": [],
            "verification": None, "needs_replan": False, "final_answer": None,
            "status": "pending", "cost_metrics": {
                "kimi_input_tokens": 0, "kimi_output_tokens": 0,
                "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
                "total_cost_usd": 0.0, "tool_calls": 0,
            },
            "planning_iterations": 0, "scratchpad": "",
            "priority": priority,
            "action_type": action_type
        }

        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "aether"}}
        try:
            # Execute the graph.ainvoke
            await graph.ainvoke(initial_state, config=config)
            logger.info("proactive_task_worker.task_completed", task_id=task_id, consumer=self.consumer_name)
        except Exception as exc:
            error_trace = traceback.format_exc()
            logger.error("proactive_task_worker.task_failed", task_id=task_id, error=str(exc), traceback=error_trace, exc_info=True, consumer=self.consumer_name)
        finally:
            # Acknowledge the message regardless of success or failure
            if self.redis_client:
                await self.redis_client.xack(self.stream_name, self.consumer_group, message_id)
                logger.info("proactive_task_worker.task_acknowledged", message_id=message_id.decode(), task_id=task_id, consumer=self.consumer_name)


# Entry point for running the worker as a standalone process
if __name__ == "__main__":
    # Basic setup for structlog in standalone worker
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    worker = ProactiveTaskWorker()
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        asyncio.run(worker.stop())
    except Exception as e:
        logger.critical("proactive_task_worker.main_error", error=str(e), exc_info=True)