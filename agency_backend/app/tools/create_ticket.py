"""
create_ticket tool — Standalone tool for Custom LLM voice calls.
================================================================
Used by groq_proxy.py tool dispatcher when Groq detects a ticket
should be created during a live voice call.

Interface:
    TOOL_DEFINITION  — dict describing the tool (name, description, params)
    validate(args)   — validates & cleans arguments, returns clean dict
    execute(args)    — creates ticket via TicketService, returns result dict
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# =====================================================================
# TOOL DEFINITION (used by dispatcher to build system prompt)
# =====================================================================

TOOL_DEFINITION = {
    "name": "create_ticket",
    "description": (
        "Create a customer support ticket. Use when customer reports a complaint, "
        "wrong order, quality issue, delivery problem, billing dispute, or any issue "
        "that needs follow-up."
    ),
    "parameters": {
        "customer_name": {
            "type": "string",
            "required": True,
            "description": "Customer's name (MUST ask if not provided)",
        },
        "issue_description": {
            "type": "string",
            "required": True,
            "description": "Clear description of the issue",
        },
        "phone_number": {
            "type": "string",
            "required": False,
            "description": "Phone number if provided, else null",
        },
        "priority": {
            "type": "string",
            "required": False,
            "description": "High | Medium | Low (default Medium)",
        },
    },
}


# =====================================================================
# VALIDATE
# =====================================================================

def validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate & clean tool arguments.
    Returns clean dict ready for TicketService.
    Raises ValueError if required fields are missing.
    """
    customer_name = (args.get("customer_name") or "").strip()
    issue_description = (args.get("issue_description") or "").strip()

    if not customer_name:
        raise ValueError("Aap apna naam bata dijiye, phir main aapka ticket bana deti hoon.")
    if not issue_description:
        raise ValueError("Aapki problem kya hai, please bataiye.")

    phone_number = (args.get("phone_number") or "").strip() or None
    priority = (args.get("priority") or "Medium").strip()
    if priority not in ("High", "Medium", "Low"):
        priority = "Medium"

    return {
        "customer_name": customer_name,
        "issue_description": issue_description,
        "phone_number": phone_number,
        "priority": priority,
    }


# =====================================================================
# EXECUTE
# =====================================================================

async def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute create_ticket: validates args, creates ticket in BOTH:
    1. Local PostgreSQL (for website dashboard)
    2. Zoho Desk (for support team)

    Returns:
        {
            "success": True/False,
            "message": "confirmation or error message",
            "ticket_id": 123 (if success)
        }
    """
    # Step 1: Validate
    try:
        clean_args = validate(args)
    except ValueError as e:
        logger.warning(f"[create_ticket] Validation failed: {e}")
        return {"success": False, "message": str(e)}

    local_ticket_id = None
    zoho_ticket_number = None

    # Step 2a: Create ticket in Local PostgreSQL (for website dashboard)
    try:
        from ..services.ticket_service import TicketService
        from ..models.ticket_models import TicketCreate

        ticket_data = TicketCreate(
            customer_name=clean_args["customer_name"],
            issue_description=clean_args["issue_description"],
            phone_number=clean_args["phone_number"],
            priority=clean_args["priority"],
        )

        logger.info(f"[create_ticket] Creating local DB ticket for {clean_args['customer_name']}")
        result = await TicketService.create_ticket(ticket_data)
        if result:
            local_ticket_id = result.ticket_id
            logger.info(f"[create_ticket] Local ticket #{local_ticket_id} created")
    except Exception as e:
        logger.error(f"[create_ticket] Local DB error (non-blocking): {e}")

    # Step 2b: Create ticket in Zoho Desk (for support team)
    try:
        from ..services.zoho_desk_service import ZohoDeskService

        logger.info(f"[create_ticket] Creating Zoho Desk ticket for {clean_args['customer_name']}")
        zoho_result = await ZohoDeskService.create_ticket(
            customer_name=clean_args["customer_name"],
            issue_description=clean_args["issue_description"],
            phone_number=clean_args["phone_number"],
            priority=clean_args["priority"],
        )
        if zoho_result.get("success"):
            zoho_ticket_number = zoho_result.get("ticket_number", zoho_result.get("ticket_id"))
            logger.info(f"[create_ticket] Zoho ticket #{zoho_ticket_number} created")
    except Exception as e:
        logger.error(f"[create_ticket] Zoho Desk error (non-blocking): {e}")

    # Step 3: Return result (success if at least one succeeded)
    if local_ticket_id or zoho_ticket_number:
        ticket_ref = zoho_ticket_number or local_ticket_id
        return {
            "success": True,
            "message": f"Ticket number {ticket_ref} create ho gaya hai {clean_args['customer_name']} ji ke liye. Humari team jaldi contact karegi.",
            "ticket_id": local_ticket_id,
            "zoho_ticket_number": zoho_ticket_number,
        }
    else:
        return {
            "success": False,
            "message": "Abhi ticket create nahi ho pa raha hai. Please baad mein try karein.",
        }
