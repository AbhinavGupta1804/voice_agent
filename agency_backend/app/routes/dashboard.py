"""Routes for dashboard APIs and WebSocket broadcasting."""
import logging
import re
from typing import List
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import JSONResponse

from ..config import Config
from ..handlers.dashboard_ws import dashboard_manager
from ..models import (
    CallRecordResponse,
    PaginatedCallsResponse,
    CallSummaryResponse,
    OutboundCallRequest,
)
from ..models.call_models import BulkOutboundCallRequest, BulkOutboundCallResponse, CallResult, CallRecipient
from ..services.call_record_service import CallRecordService
from ..services.twilio_service import TwilioService
from ..utils.csv_processor import CSVProcessor

logger = logging.getLogger(__name__)


def validate_phone_number(phone: str) -> bool:
    """Validate E.164 phone number format."""
    pattern = r'^\+?[1-9]\d{1,14}$'
    clean = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    return bool(re.match(pattern, clean))


def sanitize_phone_number(phone: str) -> str:
    """Clean and format phone number to E.164."""
    clean = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('.', '')
    if not clean.startswith('+'):
        if len(clean) == 10:
            clean = '+1' + clean
        elif len(clean) == 11 and clean.startswith('1'):
            clean = '+' + clean
        else:
            clean = '+' + clean
    return clean


def register_dashboard_routes(app):
    """Register dashboard REST and WebSocket endpoints."""
    router = APIRouter(tags=["Dashboard"])
    twilio_service = TwilioService()

    @router.get("/api/calls", response_model=PaginatedCallsResponse)
    async def list_calls(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        records, total = await CallRecordService.fetch_calls(page, page_size)
        items = [CallRecordResponse(**record) for record in records]
        return PaginatedCallsResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=items,
        )

    @router.get("/api/calls/summary", response_model=CallSummaryResponse)
    async def get_calls_summary():
        summary = await CallRecordService.get_summary()
        return CallSummaryResponse(**summary)

    @router.get("/api/call/{call_id}", response_model=CallRecordResponse)
    async def get_call(call_id: str):
        record = await CallRecordService.fetch_call(call_id)
        if not record:
            raise HTTPException(status_code=404, detail="Call not found")
        return CallRecordResponse(**record)

    @router.post("/api/initiate_call")
    async def initiate_call(request_data: OutboundCallRequest, request: Request):
        if not request_data.number:
            raise HTTPException(status_code=400, detail="Phone number is required")
        if not request_data.client_name:
            raise HTTPException(status_code=400, detail="Client name is required")

        try:
            base_url = Config.NGROK_URL or f"https://{request.headers.get('host', 'localhost')}"
            twiml_url = f"{base_url}/outbound-call-twiml"
            params = {
                "client_name": request_data.client_name,
                "phone_number": request_data.number,
            }
            twiml_url_with_params = f"{twiml_url}?{urlencode(params)}"

            call_info = await twilio_service.initiate_call(
                to_number=request_data.number,
                twiml_url=twiml_url_with_params,
            )

            # Store client name for later retrieval in webhook
            call_sid = call_info.get("call_sid")
            await CallRecordService.store_call_metadata(
                call_sid=call_sid,
                client_name=request_data.client_name,
                phone_number=request_data.number,
                call_type="outbound"
            )

            payload = {
                "call_sid": call_info.get("call_sid"),
                "client_name": request_data.client_name,
                "phone_number": request_data.number,
                "status": call_info.get("status"),
            }
            await dashboard_manager.broadcast("call_in_progress", payload)

            return JSONResponse(
                content={
                    "success": True,
                    "message": "Call initiated",
                    "callSid": call_info.get("call_sid"),
                    "clientName": request_data.client_name,
                    "phoneNumber": request_data.number,
                }
            )
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - network errors
            logger.error("[Dashboard] Error initiating call: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to initiate call")

    @router.post("/api/outbound-calls/bulk", response_model=BulkOutboundCallResponse)
    async def initiate_bulk_calls(request_data: BulkOutboundCallRequest, request: Request):
        """Initiate multiple outbound calls concurrently."""
        if not request_data.recipients:
            raise HTTPException(status_code=400, detail="Recipients list is required")

        try:
            base_url = Config.NGROK_URL or f"https://{request.headers.get('host', 'localhost')}"
            twiml_base_url = f"{base_url}/outbound-call-twiml"

            # Prepare call requests for all recipients
            call_requests = []
            for recipient in request_data.recipients:
                params = {
                    "client_name": recipient.client_name,
                    "phone_number": recipient.number
                }
                twiml_url = f"{twiml_base_url}?{urlencode(params)}"

                call_requests.append({
                    "to_number": recipient.number,
                    "twiml_url": twiml_url,
                    "client_name": recipient.client_name
                })

            # Initiate all calls sequentially
            logger.info(f"[Bulk Call] Initiating {len(call_requests)} calls sequentially")
            results = await twilio_service.initiate_sequential_calls(call_requests)

            # Process results and broadcast to dashboard
            call_results: List[CallResult] = []
            successful = 0
            failed = 0

            for result in results:
                if result["success"]:
                    successful += 1
                    call_sid = result["call_sid"]
                    
                    # Store metadata for each successful call
                    await CallRecordService.store_call_metadata(
                        call_sid=call_sid,
                        client_name=result["client_name"],
                        phone_number=result["to_number"],
                        call_type="outbound"
                    )
                    
                    # Broadcast to dashboard
                    payload = {
                        "call_sid": call_sid,
                        "client_name": result["client_name"],
                        "phone_number": result["to_number"],
                        "status": result["status"],
                    }
                    await dashboard_manager.broadcast("call_in_progress", payload)
                    
                    call_results.append(CallResult(
                        success=True,
                        call_sid=call_sid,
                        client_name=result["client_name"],
                        phone_number=result["to_number"]
                    ))
                else:
                    failed += 1
                    call_results.append(CallResult(
                        success=False,
                        call_sid=None,
                        client_name=result["client_name"],
                        phone_number=result["to_number"],
                        error=result.get("error", "Unknown error")
                    ))

            logger.info(f"[Bulk Call] Completed: {successful} successful, {failed} failed")

            return BulkOutboundCallResponse(
                total_requested=len(request_data.recipients),
                successful=successful,
                failed=failed,
                results=call_results
            )

        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - network errors
            logger.error("[Dashboard] Error initiating bulk calls: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to initiate bulk calls")

    @router.post("/api/outbound-calls/bulk-csv", response_model=BulkOutboundCallResponse)
    async def initiate_bulk_calls_from_csv(
        request: Request,
        file: UploadFile = File(..., description="CSV file with exact columns: client_name and client_phone")
    ):
        """
        Upload CSV file and initiate calls sequentially.
        
        CSV file must have exact column names: 'client_name' and 'client_phone'.
        Calls are made sequentially (one at a time) to avoid overwhelming the system.
        """
        # Validate file type
        if not CSVProcessor.validate_csv_format(file.filename or ""):
            raise HTTPException(status_code=400, detail="File must be a CSV file (.csv or .txt)")
        
        # Read file content
        try:
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="CSV file is empty")
            
            # Parse CSV
            recipients_data, parse_errors = CSVProcessor.parse_csv(content)
            
            if parse_errors and not recipients_data:
                raise HTTPException(
                    status_code=400, 
                    detail=f"CSV parsing errors: {'; '.join(parse_errors[:5])}"  # Show first 5 errors
                )
            
            if not recipients_data:
                raise HTTPException(status_code=400, detail="No valid recipients found in CSV")
            
            # Validate and sanitize phone numbers
            valid_recipients: List[CallRecipient] = []
            validation_errors = []
            
            for idx, recipient_data in enumerate(recipients_data, 1):
                name = recipient_data['client_name'].strip()
                phone = sanitize_phone_number(recipient_data['number'])
                
                # Validate
                if len(name) < 2 or len(name) > 255:
                    validation_errors.append(f"Row {idx}: Invalid name length")
                    continue
                
                if not validate_phone_number(phone):
                    validation_errors.append(f"Row {idx}: Invalid phone number: {recipient_data['number']}")
                    continue
                
                valid_recipients.append(CallRecipient(client_name=name, number=phone))
            
            if not valid_recipients:
                error_msg = "No valid recipients after validation"
                if validation_errors:
                    error_msg += f": {'; '.join(validation_errors[:5])}"
                raise HTTPException(status_code=400, detail=error_msg)
            
            logger.info(f"[CSV Upload] Processing {len(valid_recipients)} valid recipients from CSV")
            if validation_errors:
                logger.warning(f"[CSV Upload] {len(validation_errors)} validation errors: {validation_errors[:3]}")
            
            # Prepare call requests
            base_url = Config.NGROK_URL or f"https://{request.headers.get('host', 'localhost')}"
            twiml_base_url = f"{base_url}/outbound-call-twiml"
            
            call_requests = []
            for recipient in valid_recipients:
                params = {
                    "client_name": recipient.client_name,
                    "phone_number": recipient.number
                }
                twiml_url = f"{twiml_base_url}?{urlencode(params)}"
                
                call_requests.append({
                    "to_number": recipient.number,
                    "twiml_url": twiml_url,
                    "client_name": recipient.client_name
                })
            
            # Initiate calls sequentially
            logger.info(f"[CSV Bulk Call] Initiating {len(call_requests)} calls sequentially")
            results = await twilio_service.initiate_sequential_calls(call_requests)
            
            # Process results and broadcast to dashboard
            call_results: List[CallResult] = []
            successful = 0
            failed = 0
            
            for result in results:
                if result["success"]:
                    successful += 1
                    call_sid = result["call_sid"]
                    
                    # Store metadata
                    await CallRecordService.store_call_metadata(
                        call_sid=call_sid,
                        client_name=result["client_name"],
                        phone_number=result["to_number"],
                        call_type="outbound"
                    )
                    
                    # Broadcast to dashboard
                    payload = {
                        "call_sid": call_sid,
                        "client_name": result["client_name"],
                        "phone_number": result["to_number"],
                        "status": result["status"],
                    }
                    await dashboard_manager.broadcast("call_in_progress", payload)
                    
                    call_results.append(CallResult(
                        success=True,
                        call_sid=call_sid,
                        client_name=result["client_name"],
                        phone_number=result["to_number"]
                    ))
                else:
                    failed += 1
                    call_results.append(CallResult(
                        success=False,
                        call_sid=None,
                        client_name=result["client_name"],
                        phone_number=result["to_number"],
                        error=result.get("error", "Unknown error")
                    ))
            
            logger.info(f"[CSV Bulk Call] Completed: {successful} successful, {failed} failed")
            
            return BulkOutboundCallResponse(
                total_requested=len(valid_recipients),
                successful=successful,
                failed=failed,
                results=call_results
            )
        
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("[Dashboard] Error processing CSV bulk calls: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to process CSV: {str(exc)}")

    @router.websocket("/ws/dashboard")
    async def dashboard_websocket(websocket: WebSocket):
        await dashboard_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            logger.info("[Dashboard] WebSocket disconnected")
        except Exception as exc:  # pragma: no cover - client errors
            logger.debug("[Dashboard] WebSocket error: %s", exc)
        finally:
            await dashboard_manager.disconnect(websocket)

    app.include_router(router)
