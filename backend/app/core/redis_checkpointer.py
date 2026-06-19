import json
import structlog
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import redis.asyncio as redis

logger = structlog.get_logger("aether.core.redis_checkpointer")


class RedisCheckpointer:
    """
    A Redis-backed checkpointer for LangGraph task persistence.
    
    Features:
    - Automatic TTL-based cleanup (default 24 hours)
    - Namespace support for multi-tenant isolation
    - Thread-safe operations
    - Comprehensive error handling
    """

    def __init__(self, redis_client: redis.Redis, namespace: str = "aether", ttl_hours: int = 24):
        """
        Initialize the Redis checkpointer.
        
        Args:
            redis_client: Async Redis client
            namespace: Namespace prefix for keys (default: "aether")
            ttl_hours: Time-to-live for checkpoints in hours (default: 24)
        """
        self.redis_client = redis_client
        self.namespace = namespace
        self.ttl_seconds = ttl_hours * 3600
        logger.info("redis_checkpointer.initialized", namespace=namespace, ttl_hours=ttl_hours)

    def _make_key(self, config: Dict[str, Any], suffix: str = "") -> str:
        """
        Create a Redis key from the checkpoint config.
        
        Args:
            config: Checkpoint configuration (typically contains thread_id)
            suffix: Optional suffix for the key
        
        Returns:
            Redis key string
        """
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        key = f"{self.namespace}:checkpoint:{thread_id}"
        if suffix:
            key += f":{suffix}"
        return key

    async def put(self, config: Dict[str, Any], values: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        """
        Store a checkpoint.
        
        Args:
            config: Checkpoint configuration
            values: State values to store
            metadata: Metadata about the checkpoint
        """
        try:
            key = self._make_key(config)
            
            checkpoint_data = {
                "values": json.dumps(values, default=str),
                "metadata": json.dumps(metadata, default=str),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # Store with TTL
            await self.redis_client.hset(key, mapping=checkpoint_data)
            await self.redis_client.expire(key, self.ttl_seconds)
            
            logger.info("redis_checkpointer.checkpoint_stored", key=key)

        except Exception as e:
            logger.error("redis_checkpointer.put_failed", error=str(e), exc_info=True)
            raise

    async def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Retrieve a checkpoint.
        
        Args:
            config: Checkpoint configuration
        
        Returns:
            Checkpoint data or None if not found
        """
        try:
            key = self._make_key(config)
            data = await self.redis_client.hgetall(key)
            
            if not data:
                logger.debug("redis_checkpointer.checkpoint_not_found", key=key)
                return None
            
            # Decode the data
            checkpoint = {
                "values": json.loads(data.get(b"values", b"{}")),
                "metadata": json.loads(data.get(b"metadata", b"{}")),
                "timestamp": data.get(b"timestamp", b"").decode("utf-8"),
            }
            
            logger.info("redis_checkpointer.checkpoint_retrieved", key=key)
            return checkpoint

        except Exception as e:
            logger.error("redis_checkpointer.get_failed", error=str(e), exc_info=True)
            return None

    async def put_writes(self, config: Dict[str, Any], writes: Dict[str, Any]) -> None:
        """
        Store intermediate writes during task execution.
        
        Args:
            config: Checkpoint configuration
            writes: Intermediate state writes
        """
        try:
            key = self._make_key(config, "writes")
            
            writes_data = {
                "writes": json.dumps(writes, default=str),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            await self.redis_client.hset(key, mapping=writes_data)
            await self.redis_client.expire(key, self.ttl_seconds)
            
            logger.debug("redis_checkpointer.writes_stored", key=key)

        except Exception as e:
            logger.error("redis_checkpointer.put_writes_failed", error=str(e), exc_info=True)
            raise

    async def cleanup_expired(self) -> int:
        """
        Manually cleanup expired checkpoints.
        Note: Redis automatically handles TTL, but this can be called for explicit cleanup.
        
        Returns:
            Number of keys cleaned up
        """
        try:
            # Find all checkpoint keys
            pattern = f"{self.namespace}:checkpoint:*"
            keys = await self.redis_client.keys(pattern)
            
            cleaned = 0
            for key in keys:
                ttl = await self.redis_client.ttl(key)
                if ttl == -1:  # No TTL set
                    await self.redis_client.delete(key)
                    cleaned += 1
            
            logger.info("redis_checkpointer.cleanup_complete", cleaned_count=cleaned)
            return cleaned

        except Exception as e:
            logger.error("redis_checkpointer.cleanup_failed", error=str(e), exc_info=True)
            return 0

    async def delete_checkpoint(self, config: Dict[str, Any]) -> bool:
        """
        Delete a specific checkpoint.
        
        Args:
            config: Checkpoint configuration
        
        Returns:
            True if deleted, False if not found
        """
        try:
            key = self._make_key(config)
            result = await self.redis_client.delete(key)
            
            if result:
                logger.info("redis_checkpointer.checkpoint_deleted", key=key)
            else:
                logger.debug("redis_checkpointer.checkpoint_not_found_for_deletion", key=key)
            
            return bool(result)

        except Exception as e:
            logger.error("redis_checkpointer.delete_failed", error=str(e), exc_info=True)
            return False

    async def list_checkpoints(self, limit: int = 100) -> list:
        """
        List all active checkpoints.
        
        Args:
            limit: Maximum number of checkpoints to return
        
        Returns:
            List of checkpoint metadata
        """
        try:
            pattern = f"{self.namespace}:checkpoint:*"
            keys = await self.redis_client.keys(pattern)
            
            checkpoints = []
            for key in keys[:limit]:
                data = await self.redis_client.hgetall(key)
                if data:
                    checkpoints.append({
                        "key": key.decode("utf-8") if isinstance(key, bytes) else key,
                        "timestamp": data.get(b"timestamp", b"").decode("utf-8"),
                    })
            
            logger.info("redis_checkpointer.list_complete", count=len(checkpoints))
            return checkpoints

        except Exception as e:
            logger.error("redis_checkpointer.list_failed", error=str(e), exc_info=True)
            return []
