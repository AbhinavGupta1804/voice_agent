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
        
        # Refresh the token (use ZOHO_ACCOUNTS_DOMAIN to support different regions)
        token_url = f"{getattr(Config, 'ZOHO_ACCOUNTS_DOMAIN', 'https://accounts.zoho.in').rstrip('/')}/oauth/v2/token"
        logger.info("[ZohoDesk] Refreshing access token from %s", token_url)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "refresh_token": Config.ZOHO_REFRESH_TOKEN,
                    "client_id": Config.ZOHO_CLIENT_ID,
                    "client_secret": Config.ZOHO_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                }
            )
            
            if response.status_code != 200:
                err_text = response.text
                logger.error("[ZohoDesk] Token refresh failed. Check ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN. response=%s", err_text)
                raise Exception(f"Failed to refresh Zoho token: {err_text}")
            
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
            # Validate required config (helps debug GCP env vars)
            missing = []
            if not Config.ZOHO_CLIENT_ID:
                missing.append("ZOHO_CLIENT_ID")
            if not Config.ZOHO_CLIENT_SECRET:
                missing.append("ZOHO_CLIENT_SECRET")
            if not Config.ZOHO_REFRESH_TOKEN:
                missing.append("ZOHO_REFRESH_TOKEN")
            if not Config.ZOHO_ORG_ID:
                missing.append("ZOHO_ORG_ID")
            if not Config.ZOHO_DEPARTMENT_ID:
                missing.append("ZOHO_DEPARTMENT_ID")
            if missing:
                msg = f"[ZohoDesk] Missing env vars: {', '.join(missing)}. Set them in Cloud Run (or .env)."
                logger.error(msg)
                return {"success": False, "message": msg}

            api_domain = (Config.ZOHO_API_DOMAIN or "").rstrip("/")
            org_id = str(Config.ZOHO_ORG_ID).strip() if Config.ZOHO_ORG_ID else ""
            dept_id = str(Config.ZOHO_DEPARTMENT_ID).strip() if Config.ZOHO_DEPARTMENT_ID else ""
            logger.info(
                "[ZohoDesk] create_ticket config: api_domain=%s orgId=%s departmentId=%s",
                api_domain, org_id, dept_id,
            )

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

            # Build ticket payload (Zoho API accepts string or number for departmentId)
            ticket_data = {
                "subject": subject,
                "description": issue_description,
                "priority": zoho_priority,
                "departmentId": dept_id or Config.ZOHO_DEPARTMENT_ID,
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
            
            create_url = f"{api_domain}/api/v1/tickets"
            logger.info(
                "[ZohoDesk] Creating ticket for %s: POST %s (orgId=%s)",
                customer_name, create_url, org_id,
            )
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    create_url,
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "orgId": org_id,
                        "Content-Type": "application/json",
                    },
                    json=ticket_data,
                )
                
                if response.status_code in (200, 201):
                    data = response.json()
                    # Website ticket_id ≠ CRM ticket id — different numbering.
                    # id = Zoho's long internal ID (for API). ticketNumber = short display # in CRM.
                    zoho_long_id = data.get("id")
                    ticket_number = data.get("ticketNumber")
                    
                    logger.info(
                        "[ZohoDesk] Ticket created in Zoho: ticketNumber=%s id=%s (save as zoho_ticket_id in DB)",
                        ticket_number, zoho_long_id,
                    )
                    
                    return {
                        "success": True,
                        "ticket_id": zoho_long_id,  # long id for DB zoho_ticket_id column; NOT ticketNumber
                        "ticket_number": ticket_number,
                        "message": f"Ticket #{ticket_number} create ho gaya hai {customer_name} ji ke liye. Humari team jaldi contact karegi.",
                    }
                else:
                    err_body = response.text
                    logger.error(
                        "[ZohoDesk] Create ticket failed. status=%s body=%s orgId=%s departmentId=%s url=%s",
                        response.status_code, err_body, org_id, dept_id, create_url,
                    )
                    return {
                        "success": False,
                        "message": f"Zoho Desk error: {err_body}",
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
            org_id = str(Config.ZOHO_ORG_ID).strip() if Config.ZOHO_ORG_ID else ""
            api_domain = (Config.ZOHO_API_DOMAIN or "").rstrip("/")
            url = f"{api_domain}/api/v1/tickets/{ticket_id}"
            access_token = await cls._get_access_token()
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "orgId": org_id,
                    },
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error("[ZohoDesk] Failed to get ticket: status=%s body=%s url=%s", response.status_code, response.text, url)
                    return None
                    
        except Exception as e:
            logger.error(f"[ZohoDesk] Exception getting ticket: {e}", exc_info=True)
            return None

    @classmethod
    async def update_ticket_description(cls, zoho_ticket_id: str, new_description: str) -> Dict[str, Any]:
        """
        Update an existing ticket's description in Zoho Desk (e.g. after appending another complaint).
        zoho_ticket_id must be CRM (Zoho) long internal ID (from support_tickets.zoho_ticket_id). Website ticket_id uses different numbering.
        Uses PATCH so only the description field is updated.
        """
        try:
            if not Config.ZOHO_ORG_ID:
                logger.error("[ZohoDesk] update_ticket_description: ZOHO_ORG_ID not set")
                return {"success": False, "message": "ZOHO_ORG_ID not set"}
            org_id = str(Config.ZOHO_ORG_ID).strip()
            api_domain = (Config.ZOHO_API_DOMAIN or "").rstrip("/")
            patch_url = f"{api_domain}/api/v1/tickets/{zoho_ticket_id}"
            logger.info("[ZohoDesk] update_ticket_description: PATCH %s orgId=%s", patch_url, org_id)
            
            access_token = await cls._get_access_token()
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    patch_url,
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "orgId": org_id,
                        "Content-Type": "application/json",
                    },
                    json={"description": new_description},
                )
                if response.status_code == 200:
                    logger.info(
                        "[ZohoDesk] update_ticket_description: ticket %s updated, new_desc_len=%d",
                        str(zoho_ticket_id)[:16] + "...",
                        len(new_description),
                    )
                    return {"success": True, "message": "Ticket description updated."}
                logger.error(
                    "[ZohoDesk] Failed to update ticket: status=%s body=%s url=%s",
                    response.status_code, response.text, patch_url,
                )
                return {"success": False, "message": response.text}
        except Exception as e:
            logger.error(f"[ZohoDesk] Exception updating ticket: {e}", exc_info=True)
            return {"success": False, "message": str(e)}
