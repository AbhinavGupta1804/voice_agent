from typing import List
from fastapi import APIRouter, HTTPException, Depends

from ..models.ticket_models import TicketCreate, TicketResponse
from ..services.ticket_service import TicketService

router = APIRouter(prefix="/tickets", tags=["Support Tickets"])

@router.post("/", response_model=TicketResponse)
async def create_ticket(ticket: TicketCreate):
    """
    Create a new support ticket.
    """
    created_ticket = await TicketService.create_ticket(ticket)
    if not created_ticket:
        raise HTTPException(status_code=500, detail="Failed to create ticket")
    return created_ticket

@router.get("/", response_model=List[TicketResponse])
async def list_all_tickets():
    """
    Get all support tickets for dashboard.
    """
    return await TicketService.get_all_tickets()

@router.get("/user/{phone_number}", response_model=List[TicketResponse])
async def get_user_tickets(phone_number: str):
    """
    Get all tickets associated with a specific phone number.
    """
    tickets = await TicketService.get_ticket_status(phone_number)
    return tickets

@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: int):
    """
    Get a specific ticket by its ID.
    """
    ticket = await TicketService.get_ticket_by_id(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket

@router.patch("/{ticket_id}/close")
async def close_ticket(ticket_id: int):
    """
    Mark a ticket as Closed.
    """
    success = await TicketService.close_ticket(ticket_id)
    if not success:
        raise HTTPException(status_code=404, detail="Ticket not found or update failed")
    return {"status": "success", "message": f"Ticket #{ticket_id} closed."}
