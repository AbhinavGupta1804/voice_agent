"""Service for Twilio API interactions."""
import asyncio
import logging
from typing import List, Dict

from twilio.rest import Client as TwilioClient

from ..config import Config

logger = logging.getLogger(__name__)


class TwilioService:
    """Service for Twilio API operations."""
    
    def __init__(self):
        """Initialize Twilio client."""
        Config.validate_twilio_config()
        self.client = TwilioClient(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
    
    async def initiate_call(self, to_number: str, twiml_url: str) -> dict:
        """
        Initiate an outbound call using Twilio.
        
        Args:
            to_number: Phone number to call
            twiml_url: URL for TwiML instructions
            
        Returns:
            dict: Call information including call SID
            
        Raises:
            Exception: If the call fails to initiate
        """
        try:
            call = await asyncio.to_thread(
                self.client.calls.create,
                from_=Config.TWILIO_PHONE_NUMBER,
                to=to_number,
                url=twiml_url,
            )
            
            return {
                "call_sid": call.sid,
                "to": to_number,
                "from": Config.TWILIO_PHONE_NUMBER,
                "status": call.status
            }
        
        except Exception as e:
            logger.error(f"[Twilio] Error initiating call: {e}")
            raise
    
    async def initiate_concurrent_calls(self, call_requests: List[Dict[str, str]]) -> List[Dict]:
        """
        Initiate multiple outbound calls concurrently.
        
        Args:
            call_requests: List of dicts containing 'to_number' and 'twiml_url' for each call
            
        Returns:
            List[dict]: List of call results, including successful calls and errors
        """
        async def initiate_single_call(request: Dict[str, str]) -> Dict:
            """Wrapper to handle individual call initiation with error handling."""
            try:
                result = await self.initiate_call(
                    to_number=request["to_number"],
                    twiml_url=request["twiml_url"]
                )
                return {
                    "success": True,
                    "call_sid": result["call_sid"],
                    "to_number": request["to_number"],
                    "client_name": request.get("client_name", ""),
                    "status": result["status"]
                }
            except Exception as e:
                logger.error(f"[Twilio] Failed to initiate call to {request['to_number']}: {e}")
                return {
                    "success": False,
                    "call_sid": None,
                    "to_number": request["to_number"],
                    "client_name": request.get("client_name", ""),
                    "error": str(e)
                }
        
        # Execute all calls concurrently
        results = await asyncio.gather(
            *[initiate_single_call(request) for request in call_requests],
            return_exceptions=False
        )
        
        return results
    
    async def initiate_batched_calls(self, call_requests: List[Dict[str, str]], batch_size: int = 5) -> List[Dict]:
        """
        Initiate multiple outbound calls in batches to avoid overwhelming the system.
        
        Args:
            call_requests: List of dicts containing 'to_number' and 'twiml_url' for each call
            batch_size: Number of concurrent calls per batch (default: 5)
            
        Returns:
            List[dict]: List of call results for all batches
        """
        all_results = []
        total_batches = (len(call_requests) + batch_size - 1) // batch_size
        
        logger.info(f"[Twilio] Processing {len(call_requests)} calls in {total_batches} batches of {batch_size}")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(call_requests))
            batch = call_requests[start_idx:end_idx]
            
            logger.info(f"[Twilio] Processing batch {batch_num + 1}/{total_batches} ({len(batch)} calls)")
            
            # Process this batch concurrently
            batch_results = await self.initiate_concurrent_calls(batch)
            all_results.extend(batch_results)
            
            # Optional: Add a small delay between batches if needed
            if batch_num < total_batches - 1:
                await asyncio.sleep(0.5)  # 500ms delay between batches
        
        logger.info(f"[Twilio] Completed all {total_batches} batches")
        return all_results
    
    async def initiate_sequential_calls(self, call_requests: List[Dict[str, str]]) -> List[Dict]:
        """
        Initiate multiple outbound calls sequentially (one at a time).
        
        Args:
            call_requests: List of dicts containing 'to_number' and 'twiml_url' for each call
            
        Returns:
            List[dict]: List of call results, including successful calls and errors
        """
        results = []
        total = len(call_requests)
        
        logger.info(f"[Twilio] Initiating {total} calls sequentially")
        
        for idx, request in enumerate(call_requests, 1):
            logger.info(f"[Twilio] Processing call {idx}/{total}: {request.get('client_name', 'Unknown')} - {request['to_number']}")
            
            try:
                result = await self.initiate_call(
                    to_number=request["to_number"],
                    twiml_url=request["twiml_url"]
                )
                results.append({
                    "success": True,
                    "call_sid": result["call_sid"],
                    "to_number": request["to_number"],
                    "client_name": request.get("client_name", ""),
                    "status": result["status"]
                })
                logger.info(f"[Twilio] Call {idx}/{total} initiated successfully: {result['call_sid']}")
            except Exception as e:
                logger.error(f"[Twilio] Failed to initiate call {idx}/{total} to {request['to_number']}: {e}")
                results.append({
                    "success": False,
                    "call_sid": None,
                    "to_number": request["to_number"],
                    "client_name": request.get("client_name", ""),
                    "error": str(e)
                })
            
            # Small delay between calls to avoid overwhelming the system
            if idx < total:
                await asyncio.sleep(1)  # 1 second delay between calls
        
        logger.info(f"[Twilio] Completed {total} sequential calls: {sum(1 for r in results if r['success'])} successful, {sum(1 for r in results if not r['success'])} failed")
        return results

