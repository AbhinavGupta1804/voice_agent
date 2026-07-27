"""Service for Retell AI API interactions."""
import asyncio
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from ..config import Config

logger = logging.getLogger(__name__)

RETELL_API_BASE = "https://api.retellai.com"


class RetellService:
    """Retell AI phone call operations (direct API or SIP via Twilio)."""

    @staticmethod
    def _headers() -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {Config.RETELL_API_KEY}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def build_dynamic_variables(
        client_name: str = "",
        phone_number: str = "",
        follow_up_first_message: str = "",
    ) -> Dict[str, str]:
        """Dynamic variables injected into the Retell agent prompt and tools."""
        variables: Dict[str, str] = {}
        name = (client_name or "").strip()
        phone = (phone_number or "").strip()
        if name:
            variables["customer_name"] = name
            variables["client_name"] = name
        if phone:
            variables["phone_number"] = phone
        follow_up = (follow_up_first_message or "").strip()
        if follow_up:
            variables["follow_up_first_message"] = follow_up[:500]
        return variables

    @staticmethod
    def build_metadata(
        client_name: str,
        phone_number: str,
        call_type: str,
    ) -> Dict[str, str]:
        return {
            "client_name": client_name,
            "phone_number": phone_number,
            "call_type": call_type,
        }

    @staticmethod
    def build_sip_twiml(retell_call_id: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <Sip>sip:{retell_call_id}@sip.retellai.com</Sip>
    </Dial>
</Response>"""

    @classmethod
    async def create_phone_call(
        cls,
        from_number: str,
        to_number: str,
        client_name: str = "",
        phone_number: str = "",
        follow_up_first_message: str = "",
        call_type: str = "outbound",
    ) -> Dict[str, Any]:
        """Create an outbound call via Retell telephony (number must be imported in Retell)."""
        payload: Dict[str, Any] = {
            "from_number": from_number,
            "to_number": to_number,
            "override_agent_id": Config.RETELL_AGENT_ID,
            "metadata": cls.build_metadata(client_name, phone_number or to_number, call_type),
        }
        dynamic_vars = cls.build_dynamic_variables(client_name, phone_number or to_number, follow_up_first_message)
        if dynamic_vars:
            payload["retell_llm_dynamic_variables"] = dynamic_vars

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{RETELL_API_BASE}/v2/create-phone-call",
                headers=cls._headers(),
                json=payload,
            )
            if response.status_code not in (200, 201):
                logger.error("[Retell] create-phone-call failed: %s %s", response.status_code, response.text)
                response.raise_for_status()
            data = response.json()

        logger.info("[Retell] Outbound call created call_id=%s to=%s", data.get("call_id"), to_number)
        return data

    @classmethod
    async def register_phone_call(
        cls,
        direction: str,
        from_number: str = "",
        to_number: str = "",
        client_name: str = "",
        phone_number: str = "",
        follow_up_first_message: str = "",
        call_type: str = "outbound",
        twilio_call_sid: str = "",
    ) -> Dict[str, Any]:
        """Register a call for custom telephony (SIP bridge via Twilio)."""
        payload: Dict[str, Any] = {
            "agent_id": Config.RETELL_AGENT_ID,
            "direction": direction,
            "metadata": cls.build_metadata(client_name, phone_number or (to_number if direction == "outbound" else from_number), call_type),
        }
        if from_number:
            payload["from_number"] = from_number
        if to_number:
            payload["to_number"] = to_number
        if twilio_call_sid:
            payload["telephony_identifier"] = {"twilio_call_sid": twilio_call_sid}

        dynamic_vars = cls.build_dynamic_variables(
            client_name,
            phone_number or (from_number if direction == "inbound" else to_number),
            follow_up_first_message,
        )
        if dynamic_vars:
            payload["retell_llm_dynamic_variables"] = dynamic_vars

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{RETELL_API_BASE}/v2/register-phone-call",
                headers=cls._headers(),
                json=payload,
            )
            if response.status_code not in (200, 201):
                logger.error("[Retell] register-phone-call failed: %s %s", response.status_code, response.text)
                response.raise_for_status()
            data = response.json()

        logger.info(
            "[Retell] Registered %s call call_id=%s from=%s to=%s",
            direction,
            data.get("call_id"),
            from_number,
            to_number,
        )
        return data

    @classmethod
    async def initiate_outbound_call(
        cls,
        to_number: str,
        client_name: str,
        follow_up_first_message: str = "",
        status_callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start an outbound call using the configured Retell integration mode.

        direct: Retell dials via create-phone-call (Twilio number imported to Retell).
        sip:    Register with Retell, then Twilio dials customer and bridges SIP.
        """
        from .twilio_service import TwilioService

        phone_number = to_number
        mode = (Config.RETELL_INTEGRATION_MODE or "direct").lower()

        if mode == "sip":
            registration = await cls.register_phone_call(
                direction="outbound",
                from_number=Config.TWILIO_PHONE_NUMBER,
                to_number=to_number,
                client_name=client_name,
                phone_number=phone_number,
                follow_up_first_message=follow_up_first_message,
                call_type="outbound",
            )
            retell_call_id = registration["call_id"]
            base_url = Config.NGROK_URL
            if not base_url:
                raise ValueError("NGROK_URL not configured (required for SIP mode)")

            params = {"retell_call_id": retell_call_id}
            twiml_url = f"{base_url}/retell-sip-twiml?{urlencode(params)}"
            twilio_service = TwilioService()
            twilio_result = await twilio_service.initiate_call(
                to_number=to_number,
                twiml_url=twiml_url,
                status_callback=status_callback_url,
            )
            return {
                "call_id": retell_call_id,
                "call_sid": twilio_result.get("call_sid"),
                "status": twilio_result.get("status", "initiated"),
                "mode": "sip",
            }

        call_data = await cls.create_phone_call(
            from_number=Config.TWILIO_PHONE_NUMBER,
            to_number=to_number,
            client_name=client_name,
            phone_number=phone_number,
            follow_up_first_message=follow_up_first_message,
            call_type="outbound",
        )
        telephony = call_data.get("telephony_identifier") or {}
        return {
            "call_id": call_data.get("call_id"),
            "call_sid": telephony.get("twilio_call_sid"),
            "status": "initiated",
            "mode": "direct",
        }

    @classmethod
    async def initiate_sequential_calls(cls, call_requests: list) -> list:
        """Initiate multiple outbound calls one at a time."""
        results = []
        total = len(call_requests)
        for idx, request in enumerate(call_requests, 1):
            client_name = request.get("client_name", "")
            to_number = request["to_number"]
            logger.info("[Retell] Sequential call %s/%s: %s at %s", idx, total, client_name, to_number)
            try:
                call_info = await cls.initiate_outbound_call(
                    to_number=to_number,
                    client_name=client_name,
                )
                results.append({
                    "success": True,
                    "call_id": call_info.get("call_id"),
                    "call_sid": call_info.get("call_sid"),
                    "to_number": to_number,
                    "client_name": client_name,
                    "status": call_info.get("status"),
                })
            except Exception as exc:
                logger.error("[Retell] Failed outbound call to %s: %s", to_number, exc)
                results.append({
                    "success": False,
                    "call_id": None,
                    "call_sid": None,
                    "to_number": to_number,
                    "client_name": client_name,
                    "error": str(exc),
                })
            if idx < total:
                await asyncio.sleep(1)
        return results
