from typing import List, Optional
import logging
from datetime import datetime

import asyncpg

from ..db.postgres import get_db_pool
from ..models.ticket_models import TicketCreate, TicketResponse
from ..services.zoho_desk_service import ZohoDeskService
from ..utils.phone_utils import normalize_phone_number

logger = logging.getLogger(__name__)

class TicketService:
    """Service layer for Support Ticket operations."""

    @staticmethod
    async def create_ticket(ticket_data: TicketCreate) -> Optional[TicketResponse]:
        """Create a new support ticket."""
        pool = await get_db_pool()
        
        # Normalize phone number
        phone_normalized = normalize_phone_number(ticket_data.phone_number)
        
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO support_tickets 
                    (customer_name, phone_number, issue_description, priority, status)
                    VALUES ($1, $2, $3, $4, 'Open')
                    RETURNING ticket_id, customer_name, phone_number, issue_description, priority, status, created_at, updated_at
                """, 
                ticket_data.customer_name,
                phone_normalized,
                ticket_data.issue_description,
                ticket_data.priority
                )
                
                if row:
                    ticket_response = TicketResponse(**dict(row))
                    logger.info(f"[TicketService] Created ticket #{row['ticket_id']} for {ticket_data.customer_name}")

                    # Also push to Zoho Desk so ticket is visible in CRM
                    try:
                        zoho_result = await ZohoDeskService.create_ticket(
                            customer_name=ticket_data.customer_name,
                            issue_description=ticket_data.issue_description,
                            phone_number=phone_normalized,
                            priority=ticket_data.priority or "Medium",
                        )
                        if zoho_result.get("success"):
                            # Website ticket_id ≠ CRM (Zoho) ticket id — different numbering.
                            # zoho_ticket_id = Zoho's long internal ID (for API). ticket_id = our website id.
                            zoho_long_id = zoho_result.get("ticket_id")
                            if zoho_long_id:
                                await conn.execute(
                                    "UPDATE support_tickets SET zoho_ticket_id = $1 WHERE ticket_id = $2",
                                    str(zoho_long_id), row["ticket_id"],
                                )
                                logger.info(
                                    "[TicketService] Saved zoho_ticket_id (CRM long id) for website ticket #%s, CRM display #%s",
                                    row["ticket_id"],
                                    zoho_result.get("ticket_number"),
                                )
                            logger.info(f"[TicketService] Pushed to Zoho Desk (CRM ticket #%s)", zoho_result.get("ticket_number"))
                        else:
                            logger.warning(f"[TicketService] Zoho Desk create failed: {zoho_result.get('message', 'unknown')}")
                    except Exception as zoho_err:
                        logger.warning(f"[TicketService] Zoho Desk sync failed (ticket still in DB): {zoho_err}")

                    return ticket_response
                return None
        except Exception as e:
            logger.error(f"[TicketService] Failed to create ticket: {e}")
            return None

    @staticmethod
    async def get_all_tickets() -> List[TicketResponse]:
        """Get all tickets for the dashboard."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT ticket_id, customer_name, phone_number, issue_description, priority, status, created_at, updated_at
                    FROM support_tickets
                    ORDER BY created_at DESC
                """)
                return [TicketResponse(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"[TicketService] Failed to get all tickets: {e}")
            return []

    @staticmethod
    async def get_ticket_status(phone_number: str) -> List[TicketResponse]:
        """Get all tickets for a specific phone number."""
        pool = await get_db_pool()
        
        # Normalize lookup for consistency
        phone_normalized = normalize_phone_number(phone_number)
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT ticket_id, customer_name, phone_number, issue_description, priority, status, created_at, updated_at
                    FROM support_tickets
                    WHERE phone_number = $1
                    ORDER BY created_at DESC
                """, phone_normalized)
                
                return [TicketResponse(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"[TicketService] Failed to get tickets for {phone_number}: {e}")
            return []

    @staticmethod
    async def get_ticket_by_id(ticket_id: int) -> Optional[TicketResponse]:
        """Get a single ticket by ID."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT ticket_id, customer_name, phone_number, issue_description, priority, status, created_at, updated_at
                    FROM support_tickets
                    WHERE ticket_id = $1
                """, ticket_id)
                
                if row:
                    return TicketResponse(**dict(row))
                return None
        except Exception as e:
            logger.error(f"[TicketService] Failed to get ticket #{ticket_id}: {e}")
            return None

    @staticmethod
    async def append_to_ticket(ticket_id: int, additional_issue_description: str) -> Optional[dict]:
        """
        Append an additional complaint to an existing ticket (same call, second complaint).
        Updates DB description and syncs to Zoho if zoho_ticket_id is set.
        Returns {"success": True, "message": "..."} or None if ticket not found.
        """
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                # ticket_id = website ticket id (our numbering). zoho_ticket_id = CRM (Zoho) long id, different numbering.
                row = await conn.fetchrow(
                    """
                    SELECT ticket_id, issue_description, zoho_ticket_id
                    FROM support_tickets
                    WHERE ticket_id = $1
                    """,
                    ticket_id,
                )
                if not row:
                    logger.warning(f"[TicketService] append_to_ticket: website ticket #%s not found", ticket_id)
                    return None
                current_desc = row["issue_description"] or ""
                zoho_ticket_id = row.get("zoho_ticket_id")  # CRM (Zoho) long id for PATCH, or null
                logger.info(
                    "[TicketService] append_to_ticket: website ticket #%s found, crm_zoho_id=%s, current_desc_len=%d",
                    ticket_id,
                    "present" if zoho_ticket_id else "null",
                    len(current_desc),
                )
                new_desc = current_desc.rstrip() + "\n\n[Additional complaint] " + (additional_issue_description or "").strip()

                await conn.execute(
                    """
                    UPDATE support_tickets
                    SET issue_description = $1, updated_at = NOW()
                    WHERE ticket_id = $2
                    """,
                    new_desc,
                    ticket_id,
                )
                logger.info(
                    "[TicketService] Appended to website ticket #%s in DB, new_desc_len=%d",
                    ticket_id,
                    len(new_desc),
                )

                if zoho_ticket_id:
                    try:
                        zoho_result = await ZohoDeskService.update_ticket_description(
                            str(zoho_ticket_id), new_desc
                        )
                        if zoho_result.get("success"):
                            logger.info(
                                "[TicketService] append_to_ticket: CRM (Zoho) ticket updated successfully",
                                str(zoho_ticket_id)[:16] + "...",
                            )
                        else:
                            logger.warning(
                                "[TicketService] append_to_ticket: Zoho update failed: %s",
                                zoho_result.get("message"),
                            )
                    except Exception as zoho_err:
                        logger.warning(
                            "[TicketService] append_to_ticket: Zoho sync failed (DB updated): %s",
                            zoho_err,
                        )
                else:
                    logger.info(
                        "[TicketService] append_to_ticket: no crm zoho_ticket_id for website ticket #%s, DB only",
                        ticket_id,
                    )

                return {
                    "success": True,
                    "message": f"Additional complaint added to ticket #{ticket_id}. Maine aapki yeh complaint bhi isi complain ticket mein add kar di hai.",  # ticket_id = website id
                }
        except Exception as e:
            logger.error(f"[TicketService] Failed to append to ticket #{ticket_id}: {e}")
            return None

    @staticmethod
    async def close_ticket(ticket_id: int) -> bool:
        """Mark a ticket as Closed."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE support_tickets
                    SET status = 'Closed'
                    WHERE ticket_id = $1
                """, ticket_id)
                
                # "UPDATE 1" means 1 row affected
                return result == "UPDATE 1"
        except Exception as e:
            logger.error(f"[TicketService] Failed to close ticket #{ticket_id}: {e}")
            return False
