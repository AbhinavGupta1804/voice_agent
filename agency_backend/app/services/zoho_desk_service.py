"""
Zoho Desk Service — Create and manage support tickets in Zoho Desk.
===================================================================
"""
import logging
import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from ..config import Config

logger = logging.getLogger(__name__)


class ZohoDeskService:
    """Service for Zoho Desk API integration."""
    
    _access_token: Optional[str] = None
    _token_expires_at: Optional[datetime] = None
    
    @classmethod
    async def _get_access_token(cls) -> str:
        """
        Get a valid access token, refreshing if necessary.
        Uses the refresh_token to get a new access_token when expired.
        """
        # Return cached token if still valid (with 5 min buffer)
        if cls._access_token and cls._token_expires_at:
            if datetime.now() < cls._token_expires_at - timedelta(minutes=5):
                return cls._access_token
        
        # Refresh the token
        logger.info("[ZohoDesk] Refreshing access token...")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://accounts.zoho.in/oauth/v2/token",
                data={
                    "refresh_token": Config.ZOHO_REFRESH_TOKEN,
                    "client_id": Config.ZOHO_CLIENT_ID,
                    "client_secret": Config.ZOHO_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                }
            )
            
            if response.status_code != 200:
                logger.error(f"[ZohoDesk] Token refresh failed: {response.text}")
                raise Exception(f"Failed to refresh Zoho token: {response.text}")
            
            data = response.json()
            cls._access_token = data["access_token"]
            # Token expires in 1 hour, set expiry time
            cls._token_expires_at = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
            
            logger.info("[ZohoDesk] Access token refreshed successfully")
            return cls._access_token
    
    @classmethod
    async def create_ticket(
        cls,
        customer_name: str,
        issue_description: str,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
        priority: str = "Medium"
    ) -> Dict[str, Any]:
        """
        Create a support ticket in Zoho Desk.
        
        Args:
            customer_name: Customer's name
            issue_description: Description of the issue
            phone_number: Customer's phone number (optional)
            email: Customer's email (optional)
            priority: High, Medium, or Low
            
        Returns:
            {
                "success": True/False,
                "ticket_id": "123456789",
                "ticket_number": "101",
                "message": "..."
            }
        """
        try:
            access_token = await cls._get_access_token()
            
            # Map priority to Zoho format
            priority_map = {
                "High": "High",
                "Medium": "Medium", 
                "Low": "Low"
            }
            zoho_priority = priority_map.get(priority, "Medium")
            
            # Build a concise subject from the issue (first ~60 chars)
            short_issue = issue_description[:60].rstrip()
            if len(issue_description) > 60:
                short_issue += "…"
            subject = f"[{zoho_priority}] {customer_name} — {short_issue}"

            # Build ticket payload
            ticket_data = {
                "subject": subject,
                "description": issue_description,
                "priority": zoho_priority,
                "departmentId": Config.ZOHO_DEPARTMENT_ID,
                "channel": "Phone",
                "status": "Open",
                "classification": "Problem",
                "cf": {},  # custom fields placeholder
            }
            
            # Add contact info
            contact = {"lastName": customer_name}
            if phone_number:
                contact["phone"] = phone_number
            if email:
                contact["email"] = email
            else:
                # Zoho requires email for contact, create a valid placeholder
                # Strip special chars from phone number for email
                import re
                clean_phone = re.sub(r'[^\d]', '', phone_number or '') or 'unknown'
                contact["email"] = f"voicecall.{clean_phone}@placeholder.com"
            
            ticket_data["contact"] = contact
            
            logger.info(f"[ZohoDesk] Creating ticket for {customer_name}: {issue_description[:50]}...")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{Config.ZOHO_API_DOMAIN}/api/v1/tickets",
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "orgId": Config.ZOHO_ORG_ID,
                        "Content-Type": "application/json",
                    },
                    json=ticket_data,
                )
                
                if response.status_code in (200, 201):
                    data = response.json()
                    ticket_id = data.get("id")
                    ticket_number = data.get("ticketNumber")
                    
                    logger.info(f"[ZohoDesk] Ticket #{ticket_number} created successfully (ID: {ticket_id})")
                    
                    return {
                        "success": True,
                        "ticket_id": ticket_id,
                        "ticket_number": ticket_number,
                        "message": f"Ticket #{ticket_number} create ho gaya hai {customer_name} ji ke liye. Humari team jaldi contact karegi.",
                    }
                else:
                    logger.error(f"[ZohoDesk] Failed to create ticket: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"Zoho Desk error: {response.text}",
                    }
                    
        except Exception as e:
            logger.error(f"[ZohoDesk] Exception creating ticket: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error creating ticket: {str(e)}",
            }
    
    @classmethod
    async def get_ticket(cls, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket details by ID."""
        try:
            access_token = await cls._get_access_token()
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{Config.ZOHO_API_DOMAIN}/api/v1/tickets/{ticket_id}",
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "orgId": Config.ZOHO_ORG_ID,
                    },
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"[ZohoDesk] Failed to get ticket {ticket_id}: {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"[ZohoDesk] Exception getting ticket: {e}", exc_info=True)
            return None
