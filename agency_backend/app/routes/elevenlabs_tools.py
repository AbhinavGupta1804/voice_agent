"""ElevenLabs Custom Tools API endpoints."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.rag import get_retriever
from ..services.ticket_service import TicketService
from ..models.ticket_models import TicketCreate

logger = logging.getLogger(__name__)


class ProductLookupRequest(BaseModel):
    """Request model for product lookup tool."""
    query: str = Field(..., description="Customer's question about product")


class ProductLookupResponse(BaseModel):
    """Response model for product lookup tool - simple format for ElevenLabs."""
    response: str = Field(..., description="The text for the agent to speak")


class CreateTicketRequest(BaseModel):
    """Request model to create a support ticket."""
    customer_name: str = Field(..., description="Name of the customer reporting the issue")
    issue_description: str = Field(..., description="Details of the issue or complaint")
    phone_number: Optional[str] = Field(None, description="Phone number associated with the ticket")
    priority: str = Field("Medium", description="Priority level: High, Medium, or Low")

class TicketToolResponse(BaseModel):
    """Response model for ticket actions."""
    success: bool
    message: str = Field(..., description="Confirmation message for the agent to speak")

class CheckTicketRequest(BaseModel):
    """Request model to check ticket status."""
    phone_number: str = Field(..., description="Phone number to lookup tickets for")


def register_elevenlabs_tools_routes(app):
    """Register ElevenLabs Custom Tools routes."""
    router = APIRouter(prefix="/api/elevenlabs", tags=["ElevenLabs Tools"])

    @router.post("/product-lookup", response_model=ProductLookupResponse)
    async def product_lookup(request: ProductLookupRequest):
        """
        ElevenLabs Custom Tool: Look up product information from RAG.
        
        The voice agent calls this when customer asks about:
        - Product prices
        - Ingredients/nutrition
        - Availability
        - Flavors
        """
        try:
            query = request.query.strip()
            if not query:
                return ProductLookupResponse(
                    response="Please specify what product information you need."
                )
            
            logger.info(f"[ElevenLabs Tool] Product lookup query: {query}")
            
            # Retrieve relevant chunks from RAG
            retriever = get_retriever(k=3)
            docs = retriever.invoke(query)
            
            if not docs:
                return ProductLookupResponse(
                    response="I couldn't find information about that product. Let me check with our team."
                )
            
            # Combine retrieved chunks into answer
            chunks = [doc.page_content for doc in docs]
            combined_info = "\n\n".join(chunks)
            
            # Use Groq to summarize into a conversational voice response
            from .groq_proxy import generate_groq_response, ChatMessage, GROQ_MODEL
            
            system_prompt = """
            You are a helpful voice assistant for Naturals Ice Cream.
            Verified product data is provided below.
            Answer the user's question using ONLY this data.
            Keep the answer conversational, short (1-2 sentences), and natural for speaking.
            Do not read raw data lists; summarize them.
            If the data doesn't answer the specific question, say you don't have that info.
            """
            
            user_prompt = f"User Question: {query}\n\nProduct Data:\n{combined_info}"
            
            try:
                # Generate a natural language response
                voice_answer = await generate_groq_response(
                    messages=[
                        ChatMessage(role="system", content=system_prompt),
                        ChatMessage(role="user", content=user_prompt)
                    ],
                    temperature=0.7,
                    max_tokens=150
                )
                final_response = voice_answer.get("content", "") if isinstance(voice_answer, dict) else voice_answer
                
                logger.info(f"[ElevenLabs Tool] Generated voice answer: {final_response}")
                return ProductLookupResponse(response=final_response)
                
            except Exception as llm_error:
                logger.error(f"[ElevenLabs Tool] LLM summary failed: {llm_error}")
                # Fallback to raw chunks if LLM fails, but truncated
                return ProductLookupResponse(response=f"Here is what I found: {combined_info[:500]}")
            
        except FileNotFoundError as e:
            logger.error(f"[ElevenLabs Tool] Vectorstore not found: {e}")
            raise HTTPException(
                status_code=503,
                detail="Product database not initialized. Please run RAG setup first."
            )
        except Exception as e:
            logger.error(f"[ElevenLabs Tool] Product lookup error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/create_ticket", response_model=TicketToolResponse)
    async def create_ticket_tool(request: CreateTicketRequest):
        """
        ElevenLabs Custom Tool: Create a new support ticket.
        """
        try:
            logger.info(f"[ElevenLabs Tool] Creating ticket for {request.customer_name}: {request.issue_description}")
            
            ticket_data = TicketCreate(
                customer_name=request.customer_name,
                issue_description=request.issue_description,
                phone_number=request.phone_number,
                priority=request.priority
            )
            
            created_ticket = await TicketService.create_ticket(ticket_data)
            
            if created_ticket:
                return TicketToolResponse(
                    success=True,
                    message=f"I've created a support ticket successfully. The ticket ID is {created_ticket.ticket_id}. Our team will look into this."
                )
            else:
                return TicketToolResponse(
                    success=False,
                    message="I'm sorry, I encountered an error while trying to create the ticket. Please try again later."
                )
                
        except Exception as e:
            logger.error(f"[ElevenLabs Tool] Create ticket error: {e}", exc_info=True)
            return TicketToolResponse(success=False, message="System error. Could not create ticket.")

    @router.post("/check-ticket-status", response_model=TicketToolResponse)
    async def check_ticket_status_tool(request: CheckTicketRequest):
        """
        ElevenLabs Custom Tool: Check status of existing tickets.
        """
        try:
            tickets = await TicketService.get_ticket_status(request.phone_number)
            
            if not tickets:
                return TicketToolResponse(
                    success=True,
                    message="I couldn't find any open tickets associated with this phone number."
                )
            
            # Summarize the latest ticket
            latest_ticket = tickets[0]
            status_msg = f"I found a ticket from {latest_ticket.created_at.strftime('%B %d')}. The status is {latest_ticket.status}. Description: {latest_ticket.issue_description}."
            
            return TicketToolResponse(success=True, message=status_msg)
            
        except Exception as e:
            logger.error(f"[ElevenLabs Tool] Check ticket status error: {e}", exc_info=True)
            return TicketToolResponse(success=False, message="System error. Could not check ticket status.")

    app.include_router(router)
