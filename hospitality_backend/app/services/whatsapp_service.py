"""Service for WhatsApp messaging via Twilio Programmable Messaging."""
import asyncio
import logging
from typing import Optional

from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException
from requests.exceptions import ConnectionError, Timeout, RequestException

from config import Config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2
RETRY_BACKOFF = 2


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
    async def send_order_confirmation(
        cls,
        to_number: str,
        caller_name: str,
        order_id: str,
        items: list,
        estimated_time_minutes: Optional[int] = None
    ) -> dict:
        """
        Send order confirmation via WhatsApp with order details and estimated time.
        
        Args:
            to_number: Recipient phone number in E.164 format
            caller_name: Name of the caller/customer
            order_id: Order ID
            items: List of order items
            estimated_time_minutes: Estimated time to complete the order
            
        Returns:
            dict: Response containing message SID and status
        """
        try:
            client = cls._get_client()
            
            # Normalize phone number: Always ensure it starts with '91' for Indian numbers
            _to_strip = to_number.replace("whatsapp:", "").lstrip("+")
            if not _to_strip.startswith("91"):
                normalized_to_number = "91" + _to_strip
            else:
                normalized_to_number = _to_strip
            
            whatsapp_to = f"whatsapp:{normalized_to_number}"
            whatsapp_from = f"whatsapp:{Config.TWILIO_WHATSAPP_NUMBER}"
            
            # Build items list
            items_text = "\n".join([
                f"• {item.get('name', 'Item')} x{item.get('quantity', 1)}"
                for item in items
            ])
            
            # Build message
            time_text = f"\n\n⏱️ *Estimated Time:* {estimated_time_minutes} minutes" if estimated_time_minutes else ""
            
            message_body = f"""
🍽️ *Order Confirmation - {order_id}*

Hello {caller_name}! Thank you for your order.

📋 *Order Details:*
{items_text}{time_text}

Your order is being prepared. We'll notify you when it's ready!

---
_This is an automated message from {Config.TWILIO_PHONE_NUMBER}_
            """.strip()
            
            message_params = {
                "from_": whatsapp_from,
                "to": whatsapp_to,
                "body": message_body
            }
            
            message = await cls._send_with_retry(client, message_params, to_number)
            
            logger.info(f"[WhatsApp] Order confirmation sent to {to_number}, sid: {message.sid}")
            
            return {
                "success": True,
                "message_sid": message.sid,
                "to": to_number,
                "status": message.status
            }
            
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to send order confirmation to {to_number}: {e}")
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
        """Send WhatsApp message with retry logic."""
        try:
            message = await asyncio.to_thread(
                client.messages.create,
                **message_params
            )
            return message
            
        except (ConnectionError, Timeout, OSError) as e:
            if retry_count < MAX_RETRIES:
                delay = RETRY_DELAY * (RETRY_BACKOFF ** retry_count)
                logger.warning(f"[WhatsApp] Connection error (attempt {retry_count + 1}/{MAX_RETRIES}): {e}. Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                return await cls._send_with_retry(client, message_params, to_number, retry_count + 1)
            else:
                logger.error(f"[WhatsApp] Max retries reached for {to_number}: {e}")
                raise Exception(f"Failed to send WhatsApp message after {MAX_RETRIES} retries: {e}")
                
        except TwilioRestException as e:
            logger.error(f"[WhatsApp] Twilio API error for {to_number}: {e}")
            raise Exception(f"Twilio API error: {e}")
            
        except RequestException as e:
            if retry_count < 1:
                logger.warning(f"[WhatsApp] Request error (attempt {retry_count + 1}): {e}. Retrying...")
                await asyncio.sleep(RETRY_DELAY)
                return await cls._send_with_retry(client, message_params, to_number, retry_count + 1)
            else:
                logger.error(f"[WhatsApp] Request error for {to_number}: {e}")
                raise Exception(f"Request error: {e}")
                
        except Exception as e:
            logger.error(f"[WhatsApp] Unexpected error for {to_number}: {e}")
            raise
    
    @classmethod
    async def send_simple_message(cls, to_number: str, message: str) -> dict:
        """
        Send a simple WhatsApp message.
        
        Args:
            to_number: Recipient phone number in E.164 format
            message: Message text to send
            
        Returns:
            dict: Response containing message SID and status
        """
        try:
            client = cls._get_client()
            
            # Normalize phone number: Always ensure it starts with '91' for Indian numbers
            _to_strip = to_number.replace("whatsapp:", "").lstrip("+")
            if not _to_strip.startswith("91"):
                normalized_to_number = "91" + _to_strip
            else:
                normalized_to_number = _to_strip
            
            whatsapp_to = f"whatsapp:{normalized_to_number}"
            whatsapp_from = f"whatsapp:{Config.TWILIO_WHATSAPP_NUMBER}"
            
            message_params = {
                "from_": whatsapp_from,
                "to": whatsapp_to,
                "body": message
            }
            
            message_obj = await cls._send_with_retry(client, message_params, to_number)
            
            logger.info(f"[WhatsApp] Simple message sent to {to_number}, sid: {message_obj.sid}")
            
            return {
                "success": True,
                "message_sid": message_obj.sid,
                "to": to_number,
                "status": message_obj.status
            }
            
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to send simple message to {to_number}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to_number
            }
    
    @classmethod
    async def send_order_prepared_notification(
        cls,
        to_number: str,
        caller_name: str,
        order_id: str
    ) -> dict:
        """
        Send notification when order status changes to preparing.
        
        Args:
            to_number: Recipient phone number in E.164 format
            caller_name: Name of the customer
            order_id: Order ID
            
        Returns:
            dict: Response containing message SID and status
        """
        try:
            message = f"""
👨‍🍳 *Your Order is Being Prepared!*

Hello {caller_name}!

Your order *{order_id}* is now being prepared in our kitchen.

We'll notify you once it's ready!

Thank you for your patience.

---
_This is an automated message from {Config.TWILIO_PHONE_NUMBER}_
            """.strip()
            
            return await cls.send_simple_message(to_number, message)
            
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to send order prepared notification to {to_number}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to_number
            }
    
    @classmethod
    async def send_order_ready_notification(
        cls,
        to_number: str,
        caller_name: str,
        order_id: str
    ) -> dict:
        """
        Send notification when order status changes to ready.
        
        Args:
            to_number: Recipient phone number in E.164 format
            caller_name: Name of the customer
            order_id: Order ID
            
        Returns:
            dict: Response containing message SID and status
        """
        try:
            message = f"""
🎉 *Your Order is Ready!*

Hello {caller_name}!

Your order *{order_id}* is now ready for pickup/delivery!

We're looking forward to serving you. Thank you for choosing us!

---
_This is an automated message from {Config.TWILIO_PHONE_NUMBER}_
            """.strip()
            
            return await cls.send_simple_message(to_number, message)
            
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to send order ready notification to {to_number}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to_number
            }

