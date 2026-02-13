from typing import List, Optional
import logging
from datetime import datetime

import asyncpg

from ..db.postgres import get_db_pool
from ..models.ticket_models import TicketCreate, TicketResponse

logger = logging.getLogger(__name__)

class TicketService:
    """Service layer for Support Ticket operations."""

    @staticmethod
    async def create_ticket(ticket_data: TicketCreate) -> Optional[TicketResponse]:
        """Create a new support ticket."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO support_tickets 
                    (customer_name, phone_number, issue_description, priority, status)
                    VALUES ($1, $2, $3, $4, 'Open')
                    RETURNING ticket_id, customer_name, phone_number, issue_description, priority, status, created_at, updated_at
                """, 
                ticket_data.customer_name,
                ticket_data.phone_number,
                ticket_data.issue_description,
                ticket_data.priority
                )
                
                if row:
                    logger.info(f"[TicketService] Created ticket #{row['ticket_id']} for {ticket_data.customer_name}")
                    return TicketResponse(**dict(row))
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
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT ticket_id, customer_name, phone_number, issue_description, priority, status, created_at, updated_at
                    FROM support_tickets
                    WHERE phone_number = $1
                    ORDER BY created_at DESC
                """, phone_number)
                
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
