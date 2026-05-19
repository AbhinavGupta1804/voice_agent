"""ElevenLabs / Retell Custom Tools API endpoints."""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, Field

from ..config import Config
from ..services.rag import get_retriever
from ..services.ticket_service import TicketService
from ..services.call_record_service import CallRecordService
from ..services.whatsapp_booking_service import WhatsAppBookingService
from ..utils.retell_payload import parse_tool_request
from ..models.ticket_models import TicketCreate

logger = logging.getLogger(__name__)

# IST timezone (UTC+5:30) — all customer-facing times are in IST
IST = timezone(timedelta(hours=5, minutes=30))

CAL_BASE_URL = "https://api.cal.com/v2"


class ProductLookupRequest(BaseModel):
    """Request model for product lookup tool."""
    query: str = Field(..., description="Customer's question about product")


class ProductLookupResponse(BaseModel):
    """Response model for product lookup tool - simple format for ElevenLabs."""
    response: str = Field(..., description="The text for the agent to speak")


class CreateTicketRequest(BaseModel):
    """Request model to create a complain ticket."""
    customer_name: str = Field(..., description="Name of the customer reporting the issue")
    issue_description: str = Field(..., description="Details of the issue or complaint")
    phone_number: Optional[str] = Field(None, description="Phone number associated with the ticket")
    conversation_id: Optional[str] = Field(None, description="ElevenLabs conversation ID; used to resolve phone if phone_number is empty")
    priority: Optional[str] = Field("Medium", description="Priority level: High, Medium, or Low")

class TicketToolResponse(BaseModel):
    """Response model for ticket actions."""
    success: bool
    message: str = Field(..., description="Confirmation message for the agent to speak")

class CheckTicketRequest(BaseModel):
    """Request model to check ticket status."""
    phone_number: str = Field(..., description="Phone number to lookup tickets for")


class AppendToTicketRequest(BaseModel):
    """Request model to append another complaint to an existing ticket (same call)."""
    ticket_id: int = Field(..., description="The website ticket ID returned when create_ticket was called earlier on this call (e.g. 137). This is NOT the CRM/Zoho ticket number.")
    additional_issue_description: str = Field(..., description="The new complaint or issue to add to the same ticket")


class GetAvailableSlotRequest(BaseModel):
    """Request model for checking available appointment slots."""
    date: str = Field(..., description="Date for appointment in YYYY-MM-DD format (IST). Example: 2026-03-08")


class GetAvailableSlotResponse(BaseModel):
    """Response model for available slots."""
    response: str = Field(..., description="The text for the agent to speak")


class BookSlotRequest(BaseModel):
    """Request model for booking an appointment slot."""
    start_time: str = Field(..., description="Slot start time in IST as returned by get_available_slot. Example: 2026-03-08T10:00:00")
    name: str = Field(..., description="Customer name for the booking")
    email: str = Field("guest@naturalsicecream.in", description="Customer email (optional)")
    phone_number: Optional[str] = Field(None, description="Customer phone number")
    timezone: Optional[str] = Field("Asia/Kolkata", description="IANA timezone for the attendee (e.g. Asia/Kolkata). Defaults to Asia/Kolkata for Indian customers.", alias="timeZone")


class BookSlotResponse(BaseModel):
    """Response model for booking confirmation."""
    response: str = Field(..., description="The text for the agent to speak")


class CurrentDateResponse(BaseModel):
    """Response model for current date/time lookup."""
    datetime: str = Field(..., description="Current datetime in ISO 8601 format (IST)")
    date: str = Field(..., description="Current date in YYYY-MM-DD format (IST)")
    timezone: str = Field(..., description="Timezone name")


class CollectEmailViaWhatsAppResponse(BaseModel):
    """Response after send + wait for WhatsApp email (Option 2)."""
    success: bool
    status: str
    call_id: str
    email: str = ""
    ready: bool = False
    message: str = ""


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
            You are a voice assistant for Naturals Ice Cream. Answer ONLY what the user asked, in clear English.

            Product match (critical):
            - First infer which specific product or flavor the customer asked about (e.g. vanilla ice cream, veggie iced tea).
            - Use ONLY passages that clearly describe that same product or flavor. If the passages are mainly about a different product (e.g. customer asked vanilla but the text is only about Malai), do NOT answer using the wrong product. Say briefly that you are sorry, you do not have that information for what they asked, and offer to help with something else.
            - Never blend or substitute another SKU's nutrition, price, or description as if it were the one they asked about.

            Answer shape:
            - If they ask for PRICE only → say only the price for that product. Do NOT add nutrition, ingredients, or calories unless they asked.
            - If they ask for calories (or nutrition) only → give only that for that product, one short sentence. Do NOT add price, full macros, ingredients, or other facts unless they asked.
            - If they ask for ingredients only → give only that.
            - One short sentence is best. Two sentences only if the question clearly has two parts.
            - If the product data does not contain the exact detail they asked for (for the matched product), say you don't have that information—do not guess or pad from unrelated lines.
            - Do not read out raw lists or extra numbers they did not ask for.
            """
            
            user_prompt = f"User Question: {query}\n\nProduct Data:\n{combined_info}"
            
            try:
                # Generate a natural language response
                voice_answer = await generate_groq_response(
                    messages=[
                        ChatMessage(role="system", content=system_prompt),
                        ChatMessage(role="user", content=user_prompt)
                    ],
                    temperature=0.3,
                    max_tokens=80
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
    async def create_ticket_tool(
        request: CreateTicketRequest,
        x_conversation_id: Optional[str] = Header(None, alias="X-Conversation-Id"),
    ):
        """
        ElevenLabs Custom Tool: Create a new complain ticket.
        If phone_number is empty, resolves it from conversation_id (body or X-Conversation-Id header).
        """
        # Log immediately so you can confirm which server received the request (local vs Cloud Run)
        logger.info(
            "[ElevenLabs Tool] create_ticket ENDPOINT HIT - customer=%s issue_len=%d (this server is creating ticket + pushing to Zoho)",
            request.customer_name, len(request.issue_description or ""),
        )
        try:
            conversation_id = request.conversation_id or x_conversation_id
            phone_number = request.phone_number or ""
            # Defensive fallback: some callers may send priority as null.
            normalized_priority = (request.priority or "Medium").strip() or "Medium"
            if not phone_number.strip() and conversation_id:
                resolved = await CallRecordService.get_phone_number_from_conversation(request.conversation_id)
                if resolved:
                    phone_number = resolved
                    logger.info("[ElevenLabs Tool] create_ticket: resolved phone_number from conversation_id=%s", conversation_id)
            
            logger.info(f"[ElevenLabs Tool] Creating ticket for {request.customer_name}: {request.issue_description}, phone=%s", phone_number or "(none)")
            
            ticket_data = TicketCreate(
                customer_name=request.customer_name,
                issue_description=request.issue_description,
                phone_number=phone_number or None,
                priority=normalized_priority
            )
            
            created_ticket = await TicketService.create_ticket(ticket_data)
            
            if created_ticket:
                logger.info(
                    "[ElevenLabs Tool] create_ticket: success, ticket_id=%s, customer=%s",
                    created_ticket.ticket_id,
                    request.customer_name,
                )
                return TicketToolResponse(
                    success=True,
                    message=f"Complain ticket bana di hai. Ticket number hai {created_ticket.ticket_id}. Agar isi call mein aur koi complaint ho toh bataiye, main isi ticket mein add kar dungi."
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

    @router.post("/append_to_ticket", response_model=TicketToolResponse)
    async def append_to_ticket_tool(request: AppendToTicketRequest):
        """
        ElevenLabs Custom Tool: Add another complaint to the same ticket (when customer has a second complaint on the same call).
        Use the ticket_id that was returned when create_ticket was called earlier in this call.
        """
        try:
            add_desc_preview = (request.additional_issue_description or "")[:100]
            logger.info(
                "[ElevenLabs Tool] append_to_ticket: ticket_id=%s, additional_issue_len=%d, preview=%s",
                request.ticket_id,
                len(request.additional_issue_description or ""),
                add_desc_preview + ("..." if len(request.additional_issue_description or "") > 100 else ""),
            )
            result = await TicketService.append_to_ticket(
                ticket_id=request.ticket_id,
                additional_issue_description=request.additional_issue_description,
            )
            if result:
                logger.info("[ElevenLabs Tool] append_to_ticket: success for ticket #%s", request.ticket_id)
                return TicketToolResponse(success=True, message=result["message"])
            logger.warning("[ElevenLabs Tool] append_to_ticket: ticket #%s not found", request.ticket_id)
            return TicketToolResponse(
                success=False,
                message="That ticket number was not found. I can create a new complain ticket for this issue if you'd like."
            )
        except Exception as e:
            logger.error(f"[ElevenLabs Tool] Append to ticket error: {e}", exc_info=True)
            return TicketToolResponse(success=False, message="System error. Could not add to ticket.")

    # ──────────────────────────────────────────────
    # Cal.com Appointment Booking Tools (IST-aware)
    # ──────────────────────────────────────────────

    def _cal_headers(version: str | None = None) -> dict:
        """Return common headers for Cal.com API requests."""
        ver = version or Config.CAL_API_VERSION
        return {
            "Authorization": f"Bearer {Config.CAL_API_KEY}",
            "cal-api-version": ver,
            "Content-Type": "application/json",
        }

    @router.post("/get_available_slot", response_model=GetAvailableSlotResponse)
    async def get_available_slot(request: GetAvailableSlotRequest):
        """
        ElevenLabs Custom Tool: Check available appointment slots for a given date.
        Customer provides date in IST; we query Cal.com (which uses UTC)
        and return results converted back to IST.
        """
        if not Config.CAL_API_KEY:
            return GetAvailableSlotResponse(
                response="Appointment booking is not configured. Please contact us directly."
            )

        try:
            # Parse the requested date (IST)
            try:
                req_date = datetime.strptime(request.date.strip(), "%Y-%m-%d").date()
            except ValueError:
                return GetAvailableSlotResponse(
                    response="Please provide the date in YYYY-MM-DD format, for example 2026-03-08."
                )

            # Build UTC time window for the full IST day
            ist_start = datetime(req_date.year, req_date.month, req_date.day, 0, 0, 0, tzinfo=IST)
            ist_end = ist_start + timedelta(days=1)
            utc_start = ist_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            utc_end = ist_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            logger.info(
                "[ElevenLabs Tool] get_available_slot: date=%s  UTC window=%s → %s",
                request.date, utc_start, utc_end,
            )

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{CAL_BASE_URL}/slots/available",
                    headers=_cal_headers(),
                    params={
                        "startTime": utc_start,
                        "endTime": utc_end,
                        "eventTypeId": Config.CAL_EVENT_TYPE_ID,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            # data.data.slots is a dict keyed by date → list of {time: "..."}
            slots_raw = data.get("data", {}).get("slots", {})
            all_slots: list[str] = []
            for date_key, slot_list in slots_raw.items():
                for s in slot_list:
                    utc_time_str = s.get("time", "")
                    if utc_time_str:
                        # Parse UTC time and convert to IST
                        utc_dt = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
                        ist_dt = utc_dt.astimezone(IST)
                        all_slots.append(ist_dt.strftime("%I:%M %p"))

            if not all_slots:
                return GetAvailableSlotResponse(
                    response=f"{req_date.strftime('%d %B')} ko koi slot available nahi hai. Koi aur date try karein?"
                )

            slots_text = ", ".join(all_slots)
            return GetAvailableSlotResponse(
                response=f"{req_date.strftime('%d %B')} ko yeh slots available hain: {slots_text}. Kaunsa time book karoon?"
            )

        except httpx.HTTPStatusError as e:
            logger.error("[ElevenLabs Tool] Cal.com API error: %s %s", e.response.status_code, e.response.text)
            return GetAvailableSlotResponse(response="Slot check karne mein error aa raha hai. Please thodi der baad try karein.")
        except Exception as e:
            logger.error("[ElevenLabs Tool] get_available_slot error: %s", e, exc_info=True)
            return GetAvailableSlotResponse(response="System error. Slot check nahi ho paaya.")

    @router.post("/book_slots", response_model=BookSlotResponse)
    async def book_slots(request: BookSlotRequest):
        """
        ElevenLabs Custom Tool: Book an appointment slot.
        The start_time from the agent is in IST (e.g. '2026-03-08T10:00:00').
        We convert to UTC before sending to Cal.com.
        """
        if not Config.CAL_API_KEY:
            return BookSlotResponse(
                response="Appointment booking is not configured. Please contact us directly."
            )

        try:
            # Parse the IST time provided by the agent
            try:
                ist_dt = datetime.fromisoformat(request.start_time).replace(tzinfo=IST)
            except ValueError:
                return BookSlotResponse(
                    response="Time format galat hai. Please YYYY-MM-DDTHH:MM:SS format mein dein."
                )

            utc_dt = ist_dt.astimezone(timezone.utc)
            utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            logger.info(
                "[ElevenLabs Tool] book_slots: IST=%s → UTC=%s, name=%s",
                request.start_time, utc_iso, request.name,
            )

            # Cal.com v2 requires attendee.timeZone (camelCase only) as valid IANA (e.g. Asia/Kolkata). Normalize value.
            raw_tz = (request.timezone or "Asia/Kolkata").strip()
            # Normalize common mistake: Asia/kolkata -> Asia/Kolkata (IANA is case-sensitive)
            if raw_tz.lower() == "asia/kolkata":
                raw_tz = "Asia/Kolkata"
            attendee: dict = {
                "name": request.name,
                "email": request.email or "guest@naturalsicecream.in",
                "timeZone": raw_tz,
            }
            if request.phone_number:
                attendee["phoneNumber"] = request.phone_number

            payload = {
                "start": utc_iso,
                "eventTypeId": int(Config.CAL_EVENT_TYPE_ID),
                "attendee": attendee,
                "metadata": {},
            }

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{CAL_BASE_URL}/bookings",
                    headers=_cal_headers(Config.CAL_BOOK_API_VERSION),
                    json=payload,
                )
                resp.raise_for_status()
                booking_data = resp.json()

            booking_id = booking_data.get("data", {}).get("uid", "N/A")
            ist_display = ist_dt.strftime("%d %B %Y, %I:%M %p")

            logger.info("[ElevenLabs Tool] book_slots: success, uid=%s", booking_id)
            return BookSlotResponse(
                response=f"Appointment book ho gayi hai {ist_display} IST ke liye. Booking reference: {booking_id}."
            )

        except httpx.HTTPStatusError as e:
            logger.error("[ElevenLabs Tool] Cal.com booking error: %s %s", e.response.status_code, e.response.text)
            return BookSlotResponse(response="Booking karne mein error aa raha hai. Please thodi der baad try karein.")
        except Exception as e:
            logger.error("[ElevenLabs Tool] book_slots error: %s", e, exc_info=True)
            return BookSlotResponse(response="System error. Booking nahi ho paayi.")

    @router.get("/get_current_date", response_model=CurrentDateResponse)
    async def get_current_date():
        """
        ElevenLabs Custom Tool: Fetch current date/time in IST.
        Useful for converting relative dates like "today" or "tomorrow".
        """
        now_ist = datetime.now(IST)
        return CurrentDateResponse(
            datetime=now_ist.isoformat(),
            date=now_ist.strftime("%Y-%m-%d"),
            timezone="Asia/Kolkata",
        )

    @router.post("/collect_email_via_whatsapp", response_model=CollectEmailViaWhatsAppResponse)
    async def collect_email_via_whatsapp(request: Request):
        """
        Retell / ElevenLabs tool (Option 2): send WhatsApp + wait for reply on Redis.

        Holds the HTTP request up to BOOKING_EMAIL_WAIT_TIMEOUT_SECONDS (default 90s).
        Set Retell tool timeout to 120000ms. User does NOT need to say they sent the email.
        """
        try:
            body: Dict[str, Any] = await request.json()
        except Exception:
            body = {}

        call_id, args = parse_tool_request(body)
        if not call_id:
            call_id = args.get("call_id") or body.get("call_id")
        if not call_id:
            logger.error(
                "[BookingEmail Tool] collect_email: missing call_id keys=%s",
                list(body.keys()),
            )
            raise HTTPException(
                status_code=400,
                detail="call_id is required (from Retell call object or request body)",
            )

        customer_name = (
            args.get("customer_name") or body.get("customer_name") or ""
        ).strip()
        if not customer_name:
            raise HTTPException(status_code=400, detail="customer_name is required")

        selected_time = (
            args.get("selected_time") or body.get("selected_time") or ""
        ).strip() or None

        logger.info(
            "[BookingEmail Tool] collect_email_via_whatsapp start call_id=%s name=%s",
            call_id,
            customer_name,
        )
        result = await WhatsAppBookingService.collect_email_via_whatsapp(
            call_id=call_id,
            customer_name=customer_name,
            selected_time=selected_time,
        )
        logger.info(
            "[BookingEmail Tool] collect_email_via_whatsapp done call_id=%s status=%s ready=%s",
            call_id,
            result.get("status"),
            result.get("ready"),
        )

        return CollectEmailViaWhatsAppResponse(
            success=bool(result.get("success")),
            status=result.get("status", "timeout"),
            call_id=call_id,
            email=result.get("email") or "",
            ready=bool(result.get("ready")),
            message=result.get("message", ""),
        )

    app.include_router(router)
