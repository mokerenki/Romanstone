import asyncio
import structlog
from datetime import datetime, timedelta
from app.agents.morning_briefing import MorningBriefingOrchestrator
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.memory.cognee_setup import CogneeMemory

logger = structlog.get_logger("aether.core.proactive_scheduler")

class ProactiveScheduler:
    """
    Schedules and triggers proactive agent tasks, such as the morning briefing.
    """

    def __init__(self, model_router: KimiDeepSeekRouter, cognee_memory: CogneeMemory, briefing_time_str: str = "08:00"):
        self.model_router = model_router
        self.cognee_memory = cognee_memory
        self.briefing_time_str = briefing_time_str
        self._running = False
        self._task: Optional[asyncio.Task] = None
        logger.info("proactive_scheduler.initialized", briefing_time=briefing_time_str)

    async def start(self):
        """
        Starts the scheduler loop in a background task.
        """
        if self._running:
            logger.warning("proactive_scheduler.already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_schedule_loop())
        logger.info("proactive_scheduler.started")

    async def stop(self):
        """
        Stops the scheduler loop.
        """
        if not self._running:
            logger.warning("proactive_scheduler.not_running")
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("proactive_scheduler.task_cancelled")
            self._task = None
        logger.info("proactive_scheduler.stopped")

    async def _run_schedule_loop(self):
        """
        The main loop for checking and triggering scheduled tasks.
        """
        while self._running:
            now = datetime.now()
            briefing_hour, briefing_minute = map(int, self.briefing_time_str.split(":"))
            
            scheduled_briefing_time = now.replace(
                hour=briefing_hour, minute=briefing_minute, second=0, microsecond=0
            )
            
            # If the scheduled time has passed for today, schedule for tomorrow
            if now > scheduled_briefing_time:
                scheduled_briefing_time += timedelta(days=1)
            
            time_to_wait = (scheduled_briefing_time - now).total_seconds()
            
            logger.debug("proactive_scheduler.waiting_for_briefing", next_briefing_in_seconds=time_to_wait)
            
            try:
                await asyncio.sleep(time_to_wait)
                
                if self._running: # Double check if still running after sleep
                    logger.info("proactive_scheduler.triggering_morning_briefing")
                    orchestrator = MorningBriefingOrchestrator(self.model_router, self.cognee_memory)
                    briefing = await orchestrator.generate_briefing()
                    logger.info("proactive_scheduler.morning_briefing_generated", briefing_length=len(briefing))
                    # TODO: Integrate with a notification service (e.g., email, frontend websocket)
                    print(f"\n--- MORNING BRIEFING ---\n{briefing}\n-----------------------\n")
                    
            except asyncio.CancelledError:
                logger.info("proactive_scheduler.loop_cancelled")
                break
            except Exception as e:
                logger.error("proactive_scheduler.error_in_loop", error=str(e), exc_info=True)
            
            # After triggering, wait a bit before re-evaluating to avoid immediate re-trigger
            await asyncio.sleep(60) # Wait 1 minute before next check

