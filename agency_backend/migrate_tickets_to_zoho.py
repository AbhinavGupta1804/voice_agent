"""
One-time migration script: Push all existing PostgreSQL tickets to Zoho Desk.
=============================================================================
Usage:
    cd agency_backend
    python migrate_tickets_to_zoho.py
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Ensure app modules are importable
sys.path.insert(0, ".")

from app.services.zoho_desk_service import ZohoDeskService
from app.db.postgres import get_db_pool


async def migrate():
    logger.info("=== Starting ticket migration to Zoho Desk ===")

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ticket_id, customer_name, phone_number, issue_description,
                   priority, status, created_at
            FROM support_tickets
            ORDER BY ticket_id ASC
        """)

    total = len(rows)
    logger.info(f"Found {total} tickets in PostgreSQL")

    success = 0
    failed = 0

    for row in rows:
        ticket = dict(row)
        tid = ticket["ticket_id"]
        name = ticket["customer_name"]
        desc = ticket["issue_description"]
        phone = ticket["phone_number"]
        priority = ticket["priority"] or "Medium"
        status = ticket["status"] or "Open"

        logger.info(f"[{tid}/{total}] Migrating ticket for {name}...")

        result = await ZohoDeskService.create_ticket(
            customer_name=name,
            issue_description=desc,
            phone_number=phone,
            priority=priority,
        )

        if result.get("success"):
            success += 1
            zoho_num = result.get("ticket_number")
            logger.info(f"  -> Zoho ticket #{zoho_num} created")
        else:
            failed += 1
            logger.error(f"  -> FAILED: {result.get('message')}")

        # Small delay to avoid rate-limiting
        await asyncio.sleep(0.5)

    logger.info(f"=== Migration complete: {success} success, {failed} failed out of {total} ===")


if __name__ == "__main__":
    asyncio.run(migrate())
