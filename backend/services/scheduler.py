"""
APScheduler — cron-like background jobs.

Blueprint §13 Phase 3: APScheduler tasks (15-min scans, hourly reconciliation).
Jobs publish AgentTasks to Redis — Orchestrator consumes and dispatches.
Jobs never call agents directly, keeping scheduling decoupled from execution.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.constants import TaskType

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


# ═══════════════════════════════════════════════════════════════════════════
# JOB FUNCTIONS  (publish tasks to Redis — never call agents directly)
# ═══════════════════════════════════════════════════════════════════════════
async def scan_duplicates_job() -> None:
    try:
        from services.redis_client import enqueue_scan
        task_id = await enqueue_scan(TaskType.SCAN_DUPLICATES)
        logger.info("Scheduled: scan_duplicates → task %s", task_id)
    except Exception as e:
        logger.error("scan_duplicates_job failed: %s", e)


async def scan_sla_job() -> None:
    try:
        from services.redis_client import enqueue_scan
        task_id = await enqueue_scan(TaskType.SCAN_SLA)
        logger.info("Scheduled: scan_sla → task %s", task_id)
    except Exception as e:
        logger.error("scan_sla_job failed: %s", e)


async def scan_licenses_job() -> None:
    try:
        from services.redis_client import enqueue_scan
        task_id = await enqueue_scan(TaskType.SCAN_LICENSES)
        logger.info("Scheduled: scan_licenses → task %s", task_id)
    except Exception as e:
        logger.error("scan_licenses_job failed: %s", e)


async def scan_pricing_job() -> None:
    try:
        from services.redis_client import enqueue_scan
        task_id = await enqueue_scan(TaskType.SCAN_PRICING)
        logger.info("Scheduled: scan_pricing → task %s", task_id)
    except Exception as e:
        logger.error("scan_pricing_job failed: %s", e)


async def reconcile_job() -> None:
    try:
        from services.redis_client import enqueue_scan
        task_id = await enqueue_scan(TaskType.RECONCILE)
        logger.info("Scheduled: reconcile → task %s", task_id)
    except Exception as e:
        logger.error("reconcile_job failed: %s", e)


async def auto_release_holds_job() -> None:
    """
    Release payment holds older than AUTO_RELEASE_HOURS with no confirmation.
    Blueprint §8: auto-release in 48h if no confirmation.
    Runs directly — no agent needed.
    """
    try:
        from db.database import get_pool
        from services.action_handlers.payment_handler import auto_release_stale_holds
        async with get_pool().acquire() as conn:
            count = await auto_release_stale_holds(conn)
        if count:
            logger.info("Auto-released %d stale payment holds", count)
    except Exception as e:
        logger.error("auto_release_holds_job failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
# SCHEDULER LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════
def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Blueprint §13: 15-min scans
    _scheduler.add_job(
        scan_duplicates_job,
        trigger=IntervalTrigger(minutes=15),
        id="scan_duplicates",
        name="Duplicate Payment Scanner",
        replace_existing=True,
    )
    _scheduler.add_job(
        scan_sla_job,
        trigger=IntervalTrigger(minutes=15),
        id="scan_sla",
        name="SLA Breach Predictor",
        replace_existing=True,
    )

    # Hourly scans
    _scheduler.add_job(
        scan_licenses_job,
        trigger=IntervalTrigger(hours=1),
        id="scan_licenses",
        name="Unused License Scanner",
        replace_existing=True,
    )
    _scheduler.add_job(
        scan_pricing_job,
        trigger=IntervalTrigger(hours=1),
        id="scan_pricing",
        name="Vendor Pricing Anomaly Scanner",
        replace_existing=True,
    )
    _scheduler.add_job(
        reconcile_job,
        trigger=IntervalTrigger(hours=1),
        id="reconcile",
        name="Financial Reconciliation",
        replace_existing=True,
    )

    # Blueprint §8: auto-release stale holds every 6 hours
    _scheduler.add_job(
        auto_release_holds_job,
        trigger=IntervalTrigger(hours=6),
        id="auto_release_holds",
        name="Stale Payment Hold Releaser",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "APScheduler started — %d jobs registered",
        len(_scheduler.get_jobs()),
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


def get_scheduler_status() -> dict:
    if not _scheduler:
        return {"running": False, "jobs": []}
    return {
        "running": _scheduler.running,
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time),
            }
            for job in _scheduler.get_jobs()
        ],
    }