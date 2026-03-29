"""
Redis Client — async task queue for inter-agent communication.

Blueprint §2: Inter-agent communication uses Redis pub/sub.
Blueprint §12: Redis TTL = 30 min on tasks. Max 5 concurrent Ollama workers.

Queue pattern:
  Scheduler / API  →  LPUSH ci:tasks  →  Orchestrator (BRPOP)
  Orchestrator     →  LPUSH ci:results
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
from uuid import uuid4

import redis.asyncio as aioredis

from core.config import settings
from core.constants import RedisQueue, TaskType
from models.schemas import AgentTask

logger = logging.getLogger(__name__)

# Module-level client — initialized once on startup
_redis: Optional[aioredis.Redis] = None

TASK_TTL_SECONDS = 1800          # 30 minutes (blueprint §12)
CONSUMER_TIMEOUT_MS = 2000       # BRPOP block timeout — yields control every 2s
MAX_QUEUE_SIZE = 100             # drop oldest if queue grows beyond this


# ═══════════════════════════════════════════════════════════════════════════
# PUB/SUB CHANNELS — Event Broadcasting for WebSocket
# ═══════════════════════════════════════════════════════════════════════════
class EventChannel:
    """Redis pub/sub channel constants for real-time event broadcasting."""
    ANOMALY_CREATED = "ci:events:anomaly_created"
    ACTION_EXECUTED = "ci:events:action_executed"
    APPROVAL_STATUS_CHANGED = "ci:events:approval_status_changed"
    SAVINGS_UPDATED = "ci:events:savings_updated"
    SYSTEM_STATUS_CHANGED = "ci:events:system_status_changed"
    
    @classmethod
    def all_channels(cls) -> list[str]:
        """Returns list of all event channels for subscription."""
        return [
            cls.ANOMALY_CREATED,
            cls.ACTION_EXECUTED,
            cls.APPROVAL_STATUS_CHANGED,
            cls.SAVINGS_UPDATED,
            cls.SYSTEM_STATUS_CHANGED,
        ]


# ═══════════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════
async def init_redis() -> None:
    global _redis
    _redis = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
        retry_on_timeout=True,
        max_connections=20,
    )
    # Verify connection
    await _redis.ping()
    logger.info("Redis connected — %s:%s", settings.REDIS_HOST, settings.REDIS_PORT)


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis


# ═══════════════════════════════════════════════════════════════════════════
# TASK QUEUE  (Orchestrator input)
# ═══════════════════════════════════════════════════════════════════════════
async def publish_task(task: AgentTask) -> None:
    """
    Push a task onto the ci:tasks queue (LPUSH — newest at head).
    Sets TTL so stale tasks auto-expire after 30 minutes.
    """
    r = get_redis()
    payload = task.model_dump_json()

    async with r.pipeline(transaction=True) as pipe:
        await pipe.lpush(RedisQueue.TASKS.value, payload)
        await pipe.expire(RedisQueue.TASKS.value, TASK_TTL_SECONDS)
        # Trim if queue grows too large (circuit breaker)
        await pipe.ltrim(RedisQueue.TASKS.value, 0, MAX_QUEUE_SIZE - 1)
        await pipe.execute()

    logger.debug("Task published: %s (%s)", task.task_id, task.task_type)


async def consume_tasks() -> AsyncGenerator[AgentTask, None]:
    """
    Async generator — yields tasks one at a time from ci:tasks queue.
    Uses BRPOP so it blocks efficiently instead of busy-polling.
    Yields control back to the event loop between each task.
    """
    r = get_redis()
    logger.info("Task consumer started — watching %s", RedisQueue.TASKS.value)

    while True:
        try:
            # BRPOP blocks for CONSUMER_TIMEOUT_MS then returns None
            result = await r.brpop(
                RedisQueue.TASKS.value,
                timeout=CONSUMER_TIMEOUT_MS / 1000,
            )
            if result is None:
                # Timeout — yield control so other coroutines can run
                await asyncio.sleep(0)
                continue

            _, payload = result
            task_data = json.loads(payload)
            task = AgentTask(**task_data)
            logger.debug("Task consumed: %s (%s)", task.task_id, task.task_type)
            yield task

        except aioredis.ConnectionError as e:
            logger.error("Redis connection lost: %s — retrying in 5s", e)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error("Task consumer error: %s", e)
            await asyncio.sleep(1)


async def get_queue_length() -> int:
    """Returns current number of pending tasks."""
    try:
        return await get_redis().llen(RedisQueue.TASKS.value)
    except Exception:
        return -1


# ═══════════════════════════════════════════════════════════════════════════
# RESULT PUBLISHING  (pipeline output → dashboard polling)
# ═══════════════════════════════════════════════════════════════════════════
async def publish_result(result: dict) -> None:
    """
    Push pipeline result summary to ci:results list.
    Dashboard polls /api/savings/summary which reads from DB,
    but this allows real-time WebSocket upgrade in future.
    """
    r = get_redis()
    payload = json.dumps(result, default=str)
    async with r.pipeline(transaction=True) as pipe:
        await pipe.lpush(RedisQueue.RESULTS.value, payload)
        await pipe.ltrim(RedisQueue.RESULTS.value, 0, 49)   # keep last 50
        await pipe.expire(RedisQueue.RESULTS.value, TASK_TTL_SECONDS)
        await pipe.execute()


async def get_recent_results(count: int = 10) -> list[dict]:
    """Fetch the N most recent pipeline results."""
    try:
        r = get_redis()
        raw = await r.lrange(RedisQueue.RESULTS.value, 0, count - 1)
        return [json.loads(item) for item in raw]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE: publish a scan task by type
# ═══════════════════════════════════════════════════════════════════════════
async def enqueue_scan(task_type: TaskType, priority: str = "NORMAL") -> str:
    """Create and publish a scan task. Returns the task_id."""
    from datetime import datetime, timezone
    task = AgentTask(
        task_id=str(uuid4()),
        task_type=task_type.value,
        priority=priority,
    )
    await publish_task(task)
    return task.task_id


# ═══════════════════════════════════════════════════════════════════════════
# PUB/SUB — Event Broadcasting
# ═══════════════════════════════════════════════════════════════════════════
async def publish_event(channel: str, event_data: dict) -> None:
    """
    Publish an event to a Redis pub/sub channel.
    
    Args:
        channel: Redis channel name (use EventChannel constants)
        event_data: Event payload to broadcast (will be JSON serialized)
    
    Requirements: 7.1, 7.6
    """
    try:
        r = get_redis()
        payload = json.dumps(event_data, default=str)
        await r.publish(channel, payload)
        logger.debug("Event published to %s: %s", channel, event_data.get("type", "unknown"))
    except Exception as e:
        logger.error("Failed to publish event to %s: %s", channel, e)
        # Don't raise — event broadcasting should not block main flow


async def subscribe_to_events(
    channels: list[str],
) -> AsyncGenerator[tuple[str, dict], None]:
    """
    Subscribe to Redis pub/sub channels and yield incoming events.
    
    Args:
        channels: List of channel names to subscribe to
    
    Yields:
        Tuple of (channel_name, event_data)
    
    Requirements: 7.6
    
    Example:
        async for channel, event in subscribe_to_events(EventChannel.all_channels()):
            print(f"Received event on {channel}: {event}")
    """
    r = get_redis()
    pubsub = r.pubsub()
    
    try:
        # Subscribe to all specified channels
        await pubsub.subscribe(*channels)
        logger.info("Subscribed to channels: %s", channels)
        
        while True:
            try:
                # Listen for messages with timeout to allow graceful shutdown
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )
                
                if message is None:
                    # Timeout — yield control to event loop
                    await asyncio.sleep(0)
                    continue
                
                if message["type"] == "message":
                    channel = message["channel"]
                    try:
                        event_data = json.loads(message["data"])
                        logger.debug("Event received from %s", channel)
                        yield (channel, event_data)
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse event from %s: %s", channel, e)
                        continue
                        
            except aioredis.ConnectionError as e:
                logger.error("Redis pub/sub connection lost: %s — retrying in 5s", e)
                await asyncio.sleep(5)
                # Attempt to resubscribe
                await pubsub.subscribe(*channels)
                
    except asyncio.CancelledError:
        logger.info("Event subscription cancelled")
        raise
    except Exception as e:
        logger.error("Event subscription error: %s", e)
        raise
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
        logger.info("Unsubscribed from channels: %s", channels)


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════
async def redis_health() -> dict:
    try:
        r = get_redis()
        await r.ping()
        queue_len = await get_queue_length()
        return {"status": "ok", "queue_length": queue_len}
    except Exception as e:
        return {"status": "error", "error": str(e)}