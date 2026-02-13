"""Service for WhatsApp messaging via Twilio Programmable Messaging."""
import asyncio
import logging
from typing import Optional
from urllib.parse import urljoin

from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException
from requests.exceptions import ConnectionError, Timeout, RequestException

from ..config import Config

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
RETRY_BACKOFF = 2  # multiplier for exponential backoff


class WhatsAppService:
    """Service for sending WhatsApp messages using Twilio."""
    
    _client: Optional[TwilioClient] = None
    
    @classmethod
    def _get_client(cls) -> TwilioClient:
        """Get or create the Twilio client."""
        if cls._client is None:
            Config.validate_twilio_config()
            cls._client = TwilioClient(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
        return cls._client
    
    @classmethod
    async def send_call_summary_whatsapp(
        cls,
        to_number: str,
        client_name: str,
        summary: str,
        follow_up_date: Optional[str] = None,
        include_brochure: bool = True,
        ticket_id: Optional[int] = None,
        issue: Optional[str] = None,
        call_id: Optional[str] = None
    ) -> dict:
        """
        Send a call summary or ticket confirmation via WhatsApp.
        
        Args:
            to_number: Recipient phone number.
            client_name: Name of the client.
            summary: Call summary.
            follow_up_date: Optional follow-up date.
            include_brochure: Whether to attach brochure.
            ticket_id: Optional Ticket ID if a support ticket was raised.
            issue: Optional Issue description for the ticket.
        """
        try:
            client = cls._get_client()
            
            # Normalize phone number logic...
            _to_strip = to_number.replace("whatsapp:", "").replace("+", "").strip()
            # If it doesn't start with '91', add it
            if not _to_strip.startswith("91") or len(_to_strip) == 10:
                normalized_to_number = "91" + _to_strip
            else:
                normalized_to_number = _to_strip
            
            whatsapp_to = f"whatsapp:+{normalized_to_number}"
            whatsapp_from = f"whatsapp:{Config.TWILIO_WHATSAPP_NUMBER}"
            
            # --- Message Template Logic ---
            # --- Message Template Logic ---
            if ticket_id and issue:
                # TICKET TEMPLATE
                message_body = f"""
👋 *Hello {client_name},*

Thank you for reaching out to Naturals Ice Cream.

✅ We have registered your complaint against:
*{issue}*

🎫 *Ticket ID:* #{ticket_id}

We will contact you soon to resolve this.
                """
                
                

                # Build params
                message_params = {
                    "from_": whatsapp_from,
                    "to": whatsapp_to,
                    "body": message_body
                }
                
                # Send the message using Twilio's WhatsApp API with retry logic
                message = await cls._send_with_retry(
                    client, message_params, to_number
                )
                
            logger.info(f"[WhatsApp] Message sent successfully to {to_number}, sid: {message.sid}")
            
            # If follow-up date exists, send interactive message with buttons
            if follow_up_date and call_id:
                await cls._send_interactive_buttons(
                    client, whatsapp_from, whatsapp_to, follow_up_date, call_id
                )
                
                return {
                    "success": True,
                    "message_sid": message.sid,
                    "to": to_number,
                    "status": message.status
                }
            else:
                # If no ticket, do NOT send anything
                logger.info(f"[WhatsApp] No ticket raised for {to_number}, skipping WhatsApp notification.")
                return {
                    "success": True,  # Return true to indicate no error occurred (just skipped)
                    "message_sid": None,
                    "to": to_number,
                    "status": "skipped"
                }

        except Exception as e:
            logger.error(f"[WhatsApp] Failed to send message to {to_number}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to_number
            }
    
    @classmethod
    async def _send_with_retry(
        cls,
        client: TwilioClient,
        message_params: dict,
        to_number: str,
        retry_count: int = 0
    ):
        """
        Send WhatsApp message with retry logic for connection errors.
        
        Args:
            client: Twilio client instance
            message_params: Message parameters for Twilio API
            to_number: Recipient number for logging
            retry_count: Current retry attempt
            
        Returns:
            Twilio message object
            
        Raises:
            Exception: If all retries fail
        """
        try:
            message = await asyncio.to_thread(
                client.messages.create,
                **message_params
            )
            return message
            
        except (ConnectionError, Timeout, OSError) as e:
            # Network/connection errors - retry with exponential backoff
            if retry_count < MAX_RETRIES:
                delay = RETRY_DELAY * (RETRY_BACKOFF ** retry_count)
                logger.warning(
                    f"[WhatsApp] Connection error (attempt {retry_count + 1}/{MAX_RETRIES}): {e}. "
                    f"Retrying in {delay} seconds..."
                )
                await asyncio.sleep(delay)
                return await cls._send_with_retry(
                    client, message_params, to_number, retry_count + 1
                )
            else:
                logger.error(f"[WhatsApp] Max retries reached for {to_number}: {e}")
                raise Exception(f"Failed to send WhatsApp message after {MAX_RETRIES} retries: {e}")
                
        except TwilioRestException as e:
            # Twilio API errors - don't retry (likely invalid request)
            logger.error(f"[WhatsApp] Twilio API error for {to_number}: {e}")
            raise Exception(f"Twilio API error: {e}")
            
        except RequestException as e:
            # Other request errors - retry once
            if retry_count < 1:
                logger.warning(f"[WhatsApp] Request error (attempt {retry_count + 1}): {e}. Retrying...")
                await asyncio.sleep(RETRY_DELAY)
                return await cls._send_with_retry(
                    client, message_params, to_number, retry_count + 1
                )
            else:
                logger.error(f"[WhatsApp] Request error for {to_number}: {e}")
                raise Exception(f"Request error: {e}")
                
        except Exception as e:
            # Unknown errors - log and raise
            logger.error(f"[WhatsApp] Unexpected error for {to_number}: {e}")
            raise
    
    @classmethod
    async def _send_interactive_buttons(
        cls,
        client: TwilioClient,
        from_number: str,
        to_number: str,
        follow_up_date: str,
        call_id: str
    ) -> None:
        """
        Send interactive message with Confirm and Reschedule buttons.
        
        Note: This uses Twilio's Content API for interactive templates.
        For production, you should set up a WhatsApp Business approved template.
        """
        try:
            # Build callback URL for button responses
            base_url = Config.NGROK_URL or f"http://localhost:{Config.PORT}"
            callback_url = urljoin(base_url, "/webhook/whatsapp_response")
            
            # Send a follow-up message prompting action
            action_message = f"""Would you like to confirm or reschedule your follow-up appointment on {follow_up_date}?

Reply with:
✅ *CONFIRM* - to confirm the appointment
📅 *RESCHEDULE* - to request a different time

Reference: {call_id}"""
            
            message = await asyncio.to_thread(
                client.messages.create,
                from_=from_number,
                to=to_number,
                body=action_message
            )
            
            logger.info(f"[WhatsApp] Interactive prompt sent, sid: {message.sid}")
            
        except Exception as e:
            logger.warning(f"[WhatsApp] Failed to send interactive buttons: {e}")
    
    @classmethod
    async def send_simple_message(
        cls,
        to_number: str,
        message_body: str,
        media_url: Optional[str] = None
    ) -> dict:
        """
        Send a simple WhatsApp message with optional media attachment.
        
        Args:
            to_number: Recipient phone number in E.164 format.
            message_body: Message content.
            media_url: Optional URL to media file (image, PDF, audio).
            
        Returns:
            dict: Response containing message SID and status.
        """
        try:
            client = cls._get_client()
            
            # Normalize phone number
            _to_strip = to_number.replace("whatsapp:", "").lstrip("+")
            if not _to_strip.startswith("91") or len(_to_strip) == 10:
                normalized_to_number = "91" + _to_strip
            else:
                normalized_to_number = _to_strip
            
            whatsapp_to = f"whatsapp:+{normalized_to_number}"
            whatsapp_from = f"whatsapp:{Config.TWILIO_WHATSAPP_NUMBER}"
            
            # Build message parameters
            message_params = {
                "from_": whatsapp_from,
                "to": whatsapp_to,
                "body": message_body
            }
            
            # Add media URL if provided
            if media_url:
                message_params["media_url"] = [media_url]
                logger.info(f"[WhatsApp] Including media: {media_url}")
            
            # Use retry logic for simple message too
            message = await cls._send_with_retry(
                client, message_params, to_number
            )
            
            logger.info(f"[WhatsApp] Simple message sent to {to_number}, sid: {message.sid}")
            
            return {
                "success": True,
                "message_sid": message.sid,
                "to": to_number,
                "status": message.status
            }
            
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to send simple message to {to_number}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to_number
            }
