"""
Self-Healing Enterprise Cost Intelligence System
FastAPI application entrypoint.

Startup sequence:
  1. PostgreSQL pool + idempotent schema apply
  2. Seed demo data if DB is empty (500 txns, 200 licenses, 50 tickets)
  3. Redis pub/sub connection
  4. Ollama model pre-warm (qwen2.5:7b + llama3.2:3b)
  5. APScheduler 15-min scan jobs (Phase 2)
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from importlib import import_module

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from db.database import init_db, close_db, execute_schema, get_connection
from middleware.etag_middleware import ETagMiddleware

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ordered startup → yield → ordered shutdown."""
    logger.info("═" * 55)
    logger.info("  Self-Healing Enterprise Cost Intelligence System")
    logger.info("═" * 55)

    # ── 1. Database ────────────────────────────────────────────────────────────
    await init_db()
    await execute_schema()
    logger.info("✓  PostgreSQL — pool ready")

    # ── 2. Demo data ───────────────────────────────────────────────────────────
    await _maybe_seed()

    # ── 3. Redis ───────────────────────────────────────────────────────────────
    try:
        from services.redis_client import init_redis
        await init_redis()
        logger.info("✓  Redis — pub/sub ready")
    except ImportError:
        logger.info("·  Redis client (Phase 2)")

    # ── 4. Ollama pre-warm ────────────────────────────────────────────────────
    try:
        from services.llm_router import prewarm_models
        await prewarm_models()
    except Exception as exc:
        logger.warning("·  Ollama pre-warm skipped: %s", exc)

    # ── 5. Scheduler ──────────────────────────────────────────────────────────
    try:
        from services.scheduler import start_scheduler
        start_scheduler()
        logger.info("✓  APScheduler — 15-min scans active")
    except ImportError:
        logger.info("·  Scheduler (Phase 2)")

    # ── 6. Orchestrator consumer loop ─────────────────────────────────────────
    try:
        from agents.orchestrator import OrchestratorAgent
        app.state.consumer_task = asyncio.create_task(
            _run_consumer_loop(), name="orchestrator_consumer"
        )
        logger.info("✓  Orchestrator consumer — listening on Redis queue")
    except Exception as exc:
        logger.warning("·  Orchestrator consumer not started: %s", exc)

    # ── 7. WebSocket event listener ───────────────────────────────────────────
    try:
        from services.websocket_server import get_websocket_manager
        ws_manager = get_websocket_manager()
        ws_manager.start_listener_task()
        logger.info("✓  WebSocket event listener — broadcasting Redis events")
    except Exception as exc:
        logger.warning("·  WebSocket event listener not started: %s", exc)

    logger.info("═" * 55)
    logger.info("  Ready → http://localhost:8000/docs")
    logger.info("═" * 55)

    yield  # ── application running ────────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down gracefully...")
    
    # Stop WebSocket event listener
    try:
        from services.websocket_server import get_websocket_manager
        ws_manager = get_websocket_manager()
        await ws_manager.stop_listener_task()
    except Exception:
        pass
    
    if hasattr(app.state, "consumer_task"):
        app.state.consumer_task.cancel()
        try:
            await app.state.consumer_task
        except asyncio.CancelledError:
            pass
    _try_stop("services.scheduler", "stop_scheduler", is_async=False)
    await _try_stop_async("services.redis_client", "close_redis")
    await close_db()
    logger.info("Shutdown complete.")


async def _maybe_seed() -> None:
    """Seed only when the DB is empty — idempotent."""
    async with get_connection() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM transactions")
        if count == 0:
            logger.info("   DB empty — running seed data...")
            from db.seed_data import seed
            await seed(conn)
            logger.info("✓  Demo data seeded")
        else:
            logger.info("✓  DB — %d transactions already present", count)


def _try_stop(module: str, fn: str, is_async: bool = False) -> None:
    try:
        mod = import_module(module)
        getattr(mod, fn)()
    except (ImportError, AttributeError, Exception):
        pass


async def _try_stop_async(module: str, fn: str) -> None:
    try:
        mod = import_module(module)
        await getattr(mod, fn)()
    except (ImportError, AttributeError, Exception):
        pass


async def _run_consumer_loop() -> None:
    """
    Standalone consumer loop — runs as a background asyncio Task.
    Gets a fresh DB connection per task inside OrchestratorAgent.consume_forever().
    """
    from agents.orchestrator import OrchestratorAgent
    from db.database import get_pool
    from services.redis_client import consume_tasks

    logger.info("Consumer loop: waiting for tasks on Redis queue...")
    async for task in consume_tasks():
        try:
            async with get_pool().acquire() as conn:
                orch = OrchestratorAgent(conn)
                await orch.run(task)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Consumer loop error: %s", exc)
        finally:
            await asyncio.sleep(0)


# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Cost Intelligence System",
    description=(
        "Self-Healing Enterprise Cost Intelligence & Autonomous Action. "
        "ET Gen AI Hackathon 2026 — Problem Statement #3."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js dev (default port)
        "http://localhost:3001",   # Next.js dev (alternate port)
        "http://frontend:3000",    # Docker network
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── ETag Middleware ───────────────────────────────────────────────────────────
# Apply ETag-based HTTP caching to all GET endpoints
# Requirements: 2.1 (Backend SHALL generate and return ETag headers for all GET endpoints)
app.add_middleware(ETagMiddleware)


# ── Routers ───────────────────────────────────────────────────────────────────
# Phase 1 — always included
from routers.transactions import router as txn_router
from routers.approvals import router as approvals_router

app.include_router(txn_router)
app.include_router(approvals_router)

# Phase 2+ — included when built; silently skipped if module missing
_OPTIONAL_ROUTERS = [
    "routers.anomalies",
    "routers.actions",
    "routers.audit",
    "routers.savings",
    "routers.demo",
    "routers.dashboard",
    "routers.system",
]

for _mod_path in _OPTIONAL_ROUTERS:
    try:
        _mod = import_module(_mod_path)
        app.include_router(_mod.router)
        logger.debug("Registered router: %s", _mod_path)
    except (ImportError, AttributeError):
        pass


# ── System endpoints ──────────────────────────────────────────────────────────
@app.get("/health", tags=["system"], summary="Liveness probe")
async def health():
    """Kubernetes / Docker liveness probe."""
    return {"status": "ok", "env": settings.APP_ENV, "version": "1.0.0"}


@app.get("/api/system/status", tags=["system"], summary="Full system status")
async def system_status():
    """
    Returns model routing state, deepseek budget, and pending approval count.
    Polled by the dashboard header every 30 seconds.
    """
    from db.database import get_pool
    from core.constants import ModelName

    # Pending approvals count
    async with get_pool().acquire() as conn:
        pending = await conn.fetchval(
            "SELECT COUNT(*) FROM actions_taken WHERE status = 'pending_approval'"
        )

    # LLM router state
    try:
        from services.llm_router import (
            deepseek_calls_this_hour,
            deepseek_budget_remaining,
            get_loaded_models,
        )
        calls = deepseek_calls_this_hour()
        budget = deepseek_budget_remaining()
        loaded_models = await get_loaded_models()
        loaded_names = {m.get("name", "") for m in loaded_models}
    except Exception:
        calls, budget, loaded_names = 0, settings.MAX_DEEPSEEK_CALLS_PER_HOUR, set()

    return {
        "status": "ok",
        "env": settings.APP_ENV,
        "models": [
            {
                "name": ModelName.QWEN.value,
                "role": "default",
                "loaded": ModelName.QWEN.value in loaded_names,
            },
            {
                "name": ModelName.DEEPSEEK.value,
                "role": "reasoning",
                "loaded": ModelName.DEEPSEEK.value in loaded_names,
                "calls_this_hour": calls,
                "budget_remaining": budget,
            },
            {
                "name": ModelName.LLAMA.value,
                "role": "fallback",
                "loaded": ModelName.LLAMA.value in loaded_names,
            },
        ],
        "thresholds": {
            "auto_approve_limit_inr": settings.AUTO_APPROVE_LIMIT,
            "sla_escalation_threshold": settings.SLA_ESCALATION_THRESHOLD,
            "duplicate_window_days": settings.DUPLICATE_WINDOW_DAYS,
            "unused_license_days": settings.UNUSED_LICENSE_DAYS,
        },
        "pending_approvals": pending or 0,
    }


@app.get("/api/system/routing-config", tags=["system"])
async def routing_config():
    """Expose the model routing config for the dashboard model-status panel."""
    from core.config import ROUTING_CONFIG
    from services.llm_router import deepseek_calls_this_hour, deepseek_budget_remaining
    return {
        **ROUTING_CONFIG,
        "deepseek_calls_this_hour": deepseek_calls_this_hour(),
        "deepseek_budget_remaining": deepseek_budget_remaining(),
    }



# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time dashboard updates.
    
    This endpoint provides real-time updates to the dashboard by broadcasting
    events from Redis pub/sub channels. Clients connect to this endpoint to
    receive live updates when anomalies are created, actions are executed,
    approvals change status, savings are updated, or system status changes.
    
    Authentication: Currently accepts all connections. In production, validate
    tokens from headers or query parameters.
    
    Message Format: JSON with {type, timestamp, data} structure
    
    Requirements: 1.1, 1.4
    
    Example client connection:
        const ws = new WebSocket('ws://localhost:8000/ws/dashboard');
        ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            console.log('Received:', message.type, message.data);
        };
    """
    from services.websocket_server import get_websocket_manager
    
    ws_manager = get_websocket_manager()
    client_id = None
    
    try:
        # Connect and authenticate
        client_id = await ws_manager.connect(websocket)
        logger.info("WebSocket client connected: %s", client_id)
        
        # Keep connection alive and handle incoming messages
        # (Currently we only broadcast from server to client, but this loop
        # keeps the connection open and allows for future client->server messages)
        while True:
            try:
                # Wait for messages from client (with timeout to check connection health)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Currently we don't process client messages, but log them
                logger.debug("Received message from client %s: %s", client_id, data)
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    from datetime import datetime, timezone
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": {}
                    })
                except Exception:
                    # Connection is dead
                    break
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", client_id)
    except Exception as e:
        logger.error("WebSocket error for client %s: %s", client_id, e)
    finally:
        # Clean up connection
        if client_id:
            await ws_manager.disconnect(client_id)
