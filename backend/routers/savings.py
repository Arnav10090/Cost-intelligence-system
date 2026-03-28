"""Savings router — drives the live dashboard counter. Blueprint §9."""
import asyncpg
from fastapi import APIRouter, Depends

from db.database import get_db
from services.cost_calculator import get_savings_summary, get_savings_breakdown

router = APIRouter(prefix="/api/savings", tags=["savings"])


@router.get("/summary")
async def savings_summary(db: asyncpg.Connection = Depends(get_db)):
    """
    Live savings counter payload — polled every 10s by the dashboard.
    Blueprint §9 Formula 4: all 4 categories + annual projection.
    """
    return await get_savings_summary(db)


@router.get("/breakdown")
async def savings_breakdown(db: asyncpg.Connection = Depends(get_db)):
    """
    Per-category breakdown with formula strings shown.
    'Show the math' — judges requirement.
    """
    return await get_savings_breakdown(db)


@router.get("/projection")
async def savings_projection(db: asyncpg.Connection = Depends(get_db)):
    """Annual projection with ROI calculation."""
    summary = await get_savings_summary(db)
    monthly = float(summary.total_savings_this_month)
    system_cost = 500_000.0   # hypothetical annual cost of this system

    return {
        "monthly_inr": monthly,
        "annual_projection_inr": monthly * 12,
        "system_annual_cost_inr": system_cost,
        "roi_percent": round((monthly * 12 / system_cost) * 100, 1) if system_cost else None,
        "payback_months": round(system_cost / monthly, 1) if monthly > 0 else None,
        "formula": "projected_annual = total_monthly × 12 | roi = (annual / system_cost) × 100",
    }