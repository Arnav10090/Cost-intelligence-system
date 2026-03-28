"""
License Handler — deactivate and restore software licenses.

Blueprint §8:
  - license_deactivation: PATCH /api/licenses/{id} {active: false}
  - Rollback: restore if false positive flagged
"""
import logging
from uuid import UUID
from typing import Optional

import asyncpg

from core.constants import ActionState
from core.utils import utcnow

logger = logging.getLogger(__name__)


async def deactivate_license(
    db: asyncpg.Connection,
    license_id: UUID,
    action_id: Optional[UUID] = None,
    reason: str = "Unused — auto-deactivated by Resource Optimization Agent",
) -> dict:
    """
    Deactivate a software license.
    Blueprint §3 Agent 3 example: deactivate 29 licenses automatically.
    """
    row = await db.fetchrow("""
        UPDATE licenses
        SET
            is_active      = FALSE,
            deactivated_at = NOW()
        WHERE id = $1 AND is_active = TRUE
        RETURNING id, tool_name, assigned_email, monthly_cost, is_active
    """, license_id)

    if not row:
        raise ValueError(f"License {license_id} not found or already inactive")

    logger.info(
        "License DEACTIVATED — %s assigned to %s | monthly cost ₹%.0f",
        row["tool_name"], row["assigned_email"], float(row["monthly_cost"]),
    )

    if action_id:
        await db.execute("""
            UPDATE actions_taken SET status = $1 WHERE id = $2
        """, ActionState.SUCCESS.value, action_id)

    return dict(row)


async def restore_license(
    db: asyncpg.Connection,
    license_id: UUID,
    restored_by: str = "system",
) -> dict:
    """
    Restore a previously deactivated license (rollback for false positive).
    Blueprint §8: rollback if false positive flagged.
    """
    row = await db.fetchrow("""
        UPDATE licenses
        SET
            is_active      = TRUE,
            deactivated_at = NULL
        WHERE id = $1 AND is_active = FALSE
        RETURNING id, tool_name, assigned_email, is_active
    """, license_id)

    if not row:
        raise ValueError(f"License {license_id} not found or already active")

    logger.info(
        "License RESTORED — %s for %s by %s",
        row["tool_name"], row["assigned_email"], restored_by,
    )
    return dict(row)


async def bulk_deactivate_licenses(
    db: asyncpg.Connection,
    license_ids: list[UUID],
) -> tuple[int, float]:
    """
    Batch deactivate multiple licenses in a single transaction.
    Returns (count_deactivated, total_monthly_savings).
    """
    count = 0
    total_monthly = 0.0

    async with db.transaction():
        for lid in license_ids:
            try:
                row = await deactivate_license(db, lid)
                count += 1
                total_monthly += float(row.get("monthly_cost", 0))
            except ValueError:
                continue  # Already inactive — skip

    logger.info(
        "Bulk deactivation: %d/%d licenses | ₹%.0f/month saved",
        count, len(license_ids), total_monthly,
    )
    return count, total_monthly


async def get_unused_licenses(
    db: asyncpg.Connection,
    inactive_days: int = 60,
) -> list[dict]:
    """
    Query licenses that are active but unused for `inactive_days` days.
    Used by the Resource Optimization Agent scan.
    """
    rows = await db.fetch("""
        SELECT
            id,
            tool_name,
            assigned_email,
            last_login,
            is_active,
            employee_active,
            monthly_cost,
            EXTRACT(DAY FROM NOW() - last_login)::INTEGER AS inactive_days
        FROM licenses
        WHERE
            is_active = TRUE
            AND (
                employee_active = FALSE
                OR last_login < NOW() - ($1 * INTERVAL '1 day')
                OR last_login IS NULL
            )
        ORDER BY employee_active ASC, last_login ASC
    """, inactive_days)
    return [dict(r) for r in rows]