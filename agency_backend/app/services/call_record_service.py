"""Service layer for PostgreSQL call records."""
import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional

import asyncpg

from ..config import Config
from ..db.postgres import get_db_pool
from ..models.call_record_models import CallCompletePayload

logger = logging.getLogger(__name__)

# Maximum retry attempts for database operations
MAX_DB_RETRIES = 3


def _normalize_timestamp(value: datetime) -> datetime:
    """Ensure timestamp is timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_call_record(row: asyncpg.Record, topics: List[str] = None, notification_prefs: Dict = None) -> Dict:
    """Convert PostgreSQL row to dictionary format."""
    if not row:
        return {}
    
    record = dict(row)
    # Convert timestamp to ISO format string
    if record.get("call_timestamp"):
        ts = record["call_timestamp"]
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            record["timestamp"] = ts.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            record["timestamp"] = ts
    
    # Add topics as insights object
    if topics is not None:
        record["insights"] = {
            "topics": topics,
            "duration_sec": record.get("duration_sec", 0)
        }
    
    # Add notification preferences if provided
    if notification_prefs:
        record["notification_preferences"] = notification_prefs
    
    # Remove call_timestamp as we've converted it to timestamp
    record.pop("call_timestamp", None)
    record.pop("id", None)
    record.pop("created_at", None)
    record.pop("updated_at", None)
    
    return record


class CallRecordService:
    """PostgreSQL-backed operations for call records."""
    
    # In-memory store for call metadata (call_sid -> client info)
    _call_metadata: Dict[str, Dict[str, str]] = {}
    
    # In-memory store for linking conversation_id to call_sid
    _conversation_to_call: Dict[str, str] = {}

    @staticmethod
    async def store_call_metadata(call_sid: str, client_name: str, phone_number: str, call_type: str = None):
        """Store client name, phone number, and call type for a call."""
        CallRecordService._call_metadata[call_sid] = {
            "client_name": client_name,
            "phone_number": phone_number,
            "call_type": call_type
        }
        logger.info(f"[CallRecord] Stored metadata for call_sid={call_sid}: {client_name}, call_type={call_type}")

    @staticmethod
    async def link_conversation_to_call(conversation_id: str, call_sid: str):
        """Link an ElevenLabs conversation_id to a Twilio call_sid."""
        CallRecordService._conversation_to_call[conversation_id] = call_sid
        logger.info(f"[CallRecord] Linked conversation_id={conversation_id} to call_sid={call_sid}")

    @staticmethod
    async def get_phone_number_from_conversation(conversation_id: str) -> Optional[str]:
        """Retrieve phone number from call metadata using conversation_id."""
        call_sid = CallRecordService._conversation_to_call.get(conversation_id)
        if call_sid:
            metadata = CallRecordService._call_metadata.get(call_sid, {})
            phone_number = metadata.get("phone_number")
            if phone_number:
                logger.info(f"[CallRecord] Retrieved phone number from metadata for conversation_id={conversation_id}: {phone_number}")
                return phone_number
        logger.warning(f"[CallRecord] No phone number found in metadata for conversation_id={conversation_id}")
        return None
    
    @staticmethod
    async def get_call_type_from_conversation(conversation_id: str) -> Optional[str]:
        """Retrieve call_type from call metadata using conversation_id."""
        call_sid = CallRecordService._conversation_to_call.get(conversation_id)
        if call_sid:
            metadata = CallRecordService._call_metadata.get(call_sid, {})
            call_type = metadata.get("call_type")
            if call_type:
                logger.info(f"[CallRecord] Retrieved call_type from metadata for conversation_id={conversation_id}: {call_type}")
                return call_type
        return None
    
    @staticmethod
    async def get_client_name_from_conversation(conversation_id: str) -> Optional[str]:
        """Retrieve client_name from call metadata using conversation_id."""
        call_sid = CallRecordService._conversation_to_call.get(conversation_id)
        if call_sid:
            metadata = CallRecordService._call_metadata.get(call_sid, {})
            client_name = metadata.get("client_name")
            if client_name:
                logger.info(f"[CallRecord] Retrieved client_name from metadata for conversation_id={conversation_id}: {client_name}")
                return client_name
        return None

    @staticmethod
    async def cleanup_call_metadata(conversation_id: str):
        """Clean up metadata after webhook processing."""
        call_sid = CallRecordService._conversation_to_call.get(conversation_id)
        if call_sid:
            CallRecordService._call_metadata.pop(call_sid, None)
            CallRecordService._conversation_to_call.pop(conversation_id, None)
            logger.info(f"[CallRecord] Cleaned up metadata for conversation_id={conversation_id}")

    @staticmethod
    async def save_audio_recording(conversation_id: str, audio_base64: str) -> Optional[str]:
        """
        Upload base64-encoded audio to Cloudflare R2 storage and return the public URL.
        
        Args:
            conversation_id: The conversation/call ID
            audio_base64: Base64-encoded audio data
            
        Returns:
            Public URL to the audio file in R2, or None if upload failed
        """
        try:
            import boto3
            from botocore.client import Config as BotoConfig
            from botocore.exceptions import ClientError
            import tempfile
            import os
            
            logger.info(f"[CallRecord] Starting R2 upload for {conversation_id}")
            logger.info(f"[CallRecord] Audio data length (base64): {len(audio_base64)} chars")
            
            # Validate R2 configuration
            if not all([Config.R2_ACCOUNT_ID, Config.R2_ACCESS_KEY_ID, Config.R2_SECRET_ACCESS_KEY, Config.R2_BUCKET_NAME]):
                logger.error("[CallRecord] Missing R2 configuration. Please set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME")
                return None
            
            if not Config.R2_PUBLIC_BASE_URL:
                logger.error("[CallRecord] Missing R2_PUBLIC_BASE_URL. Please set it in environment variables")
                return None
            
            # Decode base64 audio
            try:
                audio_bytes = base64.b64decode(audio_base64)
                logger.info(f"[CallRecord] Decoded audio bytes: {len(audio_bytes)} bytes")
            except Exception as decode_error:
                logger.error(f"[CallRecord] Failed to decode base64 audio: {decode_error}")
                return None
            
            # Detect audio format from magic bytes
            def detect_audio_format(data: bytes) -> str:
                """Detect audio format from file header bytes."""
                if len(data) < 12:
                    return "mp3"  # Default fallback
                
                # Check for WAV (RIFF...WAVE)
                if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
                    logger.info("[CallRecord] Detected WAV format")
                    return "wav"
                
                # Check for OGG (OggS)
                if data[:4] == b'OggS':
                    logger.info("[CallRecord] Detected OGG format")
                    return "ogg"
                
                # Check for MP3 (ID3 tag or MPEG header)
                if data[:3] == b'ID3':
                    logger.info("[CallRecord] Detected MP3 format (ID3 tag)")
                    return "mp3"
                
                # MPEG-1 Layer 3: starts with FF FB, FF F3, FF F2, or FF FA
                if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
                    logger.info("[CallRecord] Detected MP3 format (MPEG header)")
                    return "mp3"
                
                # Default to MP3 if unknown
                logger.warning("[CallRecord] Unknown audio format, defaulting to MP3")
                return "mp3"
            
            audio_format = detect_audio_format(audio_bytes)
            object_name = f"{conversation_id}.{audio_format}"
            
            # Create R2 client
            endpoint_url = Config.R2_ENDPOINT_URL or f"https://{Config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            
            s3_client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=Config.R2_ACCESS_KEY_ID,
                aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
                config=BotoConfig(signature_version='s3v4'),
                region_name='auto'
            )
            
            # Upload to R2 using temporary file
            def _upload_to_r2():
                try:
                    # Create temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{audio_format}') as temp_file:
                        temp_file.write(audio_bytes)
                        temp_file_path = temp_file.name
                    
                    try:
                        # Upload to R2
                        s3_client.upload_file(
                            temp_file_path,
                            Config.R2_BUCKET_NAME,
                            object_name
                        )
                        logger.info(f"[CallRecord] Successfully uploaded {object_name} to R2 bucket {Config.R2_BUCKET_NAME}")
                    finally:
                        # Clean up temporary file
                        if os.path.exists(temp_file_path):
                            os.unlink(temp_file_path)
                    
                except ClientError as e:
                    logger.error(f"[CallRecord] R2 upload error: {e}")
                    raise
                except Exception as e:
                    logger.error(f"[CallRecord] Error during R2 upload: {e}", exc_info=True)
                    raise
            
            # Run upload in thread pool to avoid blocking
            await asyncio.to_thread(_upload_to_r2)
            
            # Generate public URL
            public_url = f"{Config.R2_PUBLIC_BASE_URL.rstrip('/')}/call-recordings/{object_name}"
            
            logger.info(f"[CallRecord] Generated public URL for {conversation_id}: {public_url}")
            
            return public_url

        except Exception as e:
            logger.error(f"[CallRecord] Failed to upload audio to R2 for {conversation_id}: {e}", exc_info=True)
            return None

    @staticmethod
    async def update_recording_url(conversation_id: str, recording_url: str) -> bool:
        """
        Update or create a call record with recording_url.
        
        Since audio webhook arrives first, this creates a minimal record
        if one doesn't exist, which will be updated later by the transcript webhook.
        """
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                # Try to update existing record first
                result = await conn.execute("""
                    UPDATE calls SET recording_url = $1, updated_at = NOW()
                    WHERE call_id = $2
                """, recording_url, conversation_id)
                
                updated = result.split()[-1] != '0'
                if updated:
                    logger.info(f"[CallRecord] Updated recording_url for existing record {conversation_id}")
                    return True
                
                # If no record exists, create a minimal one with just call_id and recording_url
                # This will be updated later when the transcript webhook arrives
                logger.info(f"[CallRecord] No record found for {conversation_id}, creating minimal record with recording_url")
                await conn.execute("""
                    INSERT INTO calls (call_id, recording_url, client_name, transcript, conversion_status, duration_sec, call_timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (call_id) DO UPDATE SET
                        recording_url = EXCLUDED.recording_url,
                        updated_at = NOW()
                """,
                    conversation_id,
                    recording_url,
                    "Unknown",  # Placeholder, will be updated by transcript webhook
                    "",  # Placeholder, will be updated by transcript webhook
                    False,  # Default conversion_status
                    0,  # Default duration
                    datetime.now(timezone.utc)  # Current timestamp as placeholder
                )
                logger.info(f"[CallRecord] Created minimal record for {conversation_id} with recording_url")
                return True
                
        except Exception as e:
            logger.error(f"[CallRecord] Failed to update/create recording_url for {conversation_id}: {e}", exc_info=True)
            return False

    @staticmethod
    async def upsert_call_record(payload: CallCompletePayload) -> Dict:
        """Insert or update a call record with retry logic."""
        record = payload.model_dump()
        
        # Handle timestamp - normalize to UTC datetime
        timestamp_value = record.get("timestamp")
        if isinstance(timestamp_value, str):
            # Try to parse ISO format string
            try:
                if timestamp_value.endswith('Z'):
                    timestamp_value = timestamp_value[:-1] + '+00:00'
                timestamp = datetime.fromisoformat(timestamp_value.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Fallback: use current time if parsing fails
                logger.warning(f"[CallRecord] Failed to parse timestamp '{timestamp_value}', using current time")
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = timestamp_value
        
        timestamp = _normalize_timestamp(timestamp)
        
        # Handle follow_up_date - convert string to date if needed
        follow_up_date_value = record.get("follow_up_date")
        if isinstance(follow_up_date_value, str):
            try:
                from datetime import date as date_type
                follow_up_date_value = date_type.fromisoformat(follow_up_date_value)
            except (ValueError, AttributeError):
                follow_up_date_value = None
        record["follow_up_date"] = follow_up_date_value
        
        logger.info(f"[CallRecord] Upserting call_id={record['call_id']}, timestamp={timestamp}")
        logger.info(f"[CallRecord] Record data: client_name={record.get('client_name')}, duration={record['insights']['duration_sec']}")
        
        last_error = None
        for attempt in range(MAX_DB_RETRIES):
            try:
                pool = await get_db_pool()
                async with pool.acquire() as conn:
                    # Start transaction
                    async with conn.transaction():
                        # Upsert call record
                        # Note: recording_url is only set by audio webhook, so we preserve existing one if transcript webhook doesn't provide it
                        logger.info(f"[CallRecord] Executing INSERT for call_id={record['call_id']}")
                        result = await conn.execute("""
                        INSERT INTO calls (
                            call_id, client_name, phone_number, transcript, summary,
                            follow_up_date, conversion_status, duration_sec, call_timestamp, recording_url, sentiment, call_type
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                            ON CONFLICT (call_id) DO UPDATE SET
                                client_name = EXCLUDED.client_name,
                                phone_number = EXCLUDED.phone_number,
                                transcript = EXCLUDED.transcript,
                                summary = EXCLUDED.summary,
                                follow_up_date = EXCLUDED.follow_up_date,
                                conversion_status = EXCLUDED.conversion_status,
                                duration_sec = EXCLUDED.duration_sec,
                                call_timestamp = EXCLUDED.call_timestamp,
                                recording_url = COALESCE(EXCLUDED.recording_url, calls.recording_url),
                                sentiment = EXCLUDED.sentiment,
                                call_type = CASE 
                                    WHEN EXCLUDED.call_type IS NOT NULL THEN EXCLUDED.call_type
                                    WHEN calls.call_type IS NOT NULL THEN calls.call_type
                                    ELSE NULL
                                END,
                                updated_at = NOW()
                        """,
                            record["call_id"],
                            record["client_name"],
                            record.get("phone_number"),
                            record["transcript"],
                            record.get("summary"),
                            record.get("follow_up_date"),
                            record["conversion_status"],
                            record["insights"]["duration_sec"],
                            timestamp,
                            record.get("recording_url"),  # Will be None from transcript webhook, preserved by COALESCE
                            record.get("sentiment"),
                            record.get("call_type")  # call_type: 'inbound' or 'outbound'
                        )
                        logger.info(f"[CallRecord] Insert/update result: {result}")
                        
                        # Verify the insert worked (within same transaction)
                        count = await conn.fetchval("SELECT COUNT(*) FROM calls WHERE call_id = $1", record["call_id"])
                        logger.info(f"[CallRecord] Verification: Found {count} record(s) with call_id={record['call_id']}")
                        
                        if count == 0:
                            logger.error(f"[CallRecord] CRITICAL: Insert appeared to succeed but record not found!")
                        
                        # Handle topics (DB column topic is VARCHAR(255))
                        topics = record["insights"].get("topics", [])
                        if topics:
                            await conn.execute(
                                "DELETE FROM call_topics WHERE call_id = $1",
                                record["call_id"]
                            )
                            for topic in topics:
                                topic_text = str(topic or "").strip()[:255]
                                if not topic_text:
                                    continue
                                await conn.execute(
                                    "INSERT INTO call_topics (call_id, topic) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                    record["call_id"],
                                    topic_text,
                                )
                            logger.info(f"[CallRecord] Inserted {len(topics)} topics for call_id={record['call_id']}")
                        
                        # Handle notification preferences
                        notif_prefs = record.get("notification_preferences")
                        if notif_prefs:
                            await conn.execute("""
                                INSERT INTO notification_preferences (
                                    call_id, notify_email, notify_whatsapp, email_address,
                                    whatsapp_number, email_sent, whatsapp_sent
                                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                                ON CONFLICT (call_id) DO UPDATE SET
                                    notify_email = EXCLUDED.notify_email,
                                    notify_whatsapp = EXCLUDED.notify_whatsapp,
                                    email_address = EXCLUDED.email_address,
                                    whatsapp_number = EXCLUDED.whatsapp_number,
                                    email_sent = EXCLUDED.email_sent,
                                    whatsapp_sent = EXCLUDED.whatsapp_sent,
                                    updated_at = NOW()
                            """,
                                record["call_id"],
                                notif_prefs.get("notify_email", False),
                                notif_prefs.get("notify_whatsapp", False),
                                notif_prefs.get("email_address"),
                                notif_prefs.get("whatsapp_number"),
                                notif_prefs.get("email_sent", False),
                                notif_prefs.get("whatsapp_sent", False)
                            )
                            logger.info(f"[CallRecord] Inserted notification preferences for call_id={record['call_id']}")
                    
                    # Fetch the complete record with all related data (after transaction commits)
                    fetched_record = await CallRecordService.fetch_call(record["call_id"])
                    if not fetched_record:
                        logger.error(f"[CallRecord] CRITICAL: Record was inserted but fetch returned empty!")
                    else:
                        logger.info(f"[CallRecord] Successfully upserted and fetched call_id={record['call_id']}")

                    return fetched_record
                
            except (asyncpg.ConnectionDoesNotExistError, asyncpg.InterfaceError, ConnectionResetError) as exc:
                last_error = exc
                logger.warning(f"[PostgreSQL] Connection error on attempt {attempt + 1}/{MAX_DB_RETRIES}: {exc}")
                if attempt < MAX_DB_RETRIES - 1:
                    import asyncio
                    await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                    
            except asyncpg.PostgresError as exc:
                logger.error(f"[PostgreSQL] Database error for call_id={record.get('call_id', 'unknown')}: {exc}", exc_info=True)
                raise
                
            except Exception as exc:
                logger.error(f"[PostgreSQL] Unexpected error for call_id={record.get('call_id', 'unknown')}: {exc}", exc_info=True)
                raise
        
        # If we get here, all retries failed
        logger.error(f"[PostgreSQL] All {MAX_DB_RETRIES} attempts failed for call_id={record.get('call_id', 'unknown')}")
        raise last_error

    @staticmethod
    async def fetch_calls(page: int, page_size: int) -> Tuple[List[Dict], int]:
        """Fetch paginated call records."""
        pool = await get_db_pool()
        offset = max(page - 1, 0) * page_size
        
        try:
            async with pool.acquire() as conn:
                # Get total count
                total = await conn.fetchval("SELECT COUNT(*) FROM calls")
                
                # Fetch calls with pagination
                rows = await conn.fetch("""
                    SELECT c.*, 
                           COALESCE(ARRAY_AGG(ct.topic) FILTER (WHERE ct.topic IS NOT NULL), ARRAY[]::TEXT[]) as topics,
                           np.notify_email, np.notify_whatsapp, np.email_address, np.whatsapp_number,
                           np.email_sent, np.whatsapp_sent
                    FROM calls c
                    LEFT JOIN call_topics ct ON c.call_id = ct.call_id
                    LEFT JOIN notification_preferences np ON c.call_id = np.call_id
                    GROUP BY c.id, c.call_id, c.client_name, c.phone_number, c.transcript, 
                             c.summary, c.follow_up_date, c.conversion_status, c.duration_sec, 
                             c.call_timestamp, c.recording_url, c.sentiment, c.call_type, c.created_at, c.updated_at,
                             np.notify_email, np.notify_whatsapp, np.email_address, np.whatsapp_number,
                             np.email_sent, np.whatsapp_sent
                    ORDER BY c.call_timestamp DESC
                    LIMIT $1 OFFSET $2
                """, page_size, offset)
                
                records = []
                for row in rows:
                    topics_list = row.get("topics", [])
                    notif_prefs = None
                    if row.get("notify_email") is not None:
                        notif_prefs = {
                            "notify_email": row.get("notify_email", False),
                            "notify_whatsapp": row.get("notify_whatsapp", False),
                            "email_address": row.get("email_address"),
                            "whatsapp_number": row.get("whatsapp_number"),
                            "email_sent": row.get("email_sent", False),
                            "whatsapp_sent": row.get("whatsapp_sent", False)
                        }
                    records.append(_serialize_call_record(row, topics_list, notif_prefs))
                
                return records, total
        except asyncpg.PostgresError as exc:
            logger.error(f"[PostgreSQL] Fetch calls failed: {exc}")
            raise

    @staticmethod
    async def fetch_call(call_id: str) -> Dict:
        """Fetch a single call record by call_id."""
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT c.*, 
                           COALESCE(ARRAY_AGG(ct.topic) FILTER (WHERE ct.topic IS NOT NULL), ARRAY[]::TEXT[]) as topics,
                           np.notify_email, np.notify_whatsapp, np.email_address, np.whatsapp_number,
                           np.email_sent, np.whatsapp_sent
                    FROM calls c
                    LEFT JOIN call_topics ct ON c.call_id = ct.call_id
                    LEFT JOIN notification_preferences np ON c.call_id = np.call_id
                    WHERE c.call_id = $1
                    GROUP BY c.id, c.call_id, c.client_name, c.phone_number, c.transcript, 
                             c.summary, c.follow_up_date, c.conversion_status, c.duration_sec, 
                             c.call_timestamp, c.recording_url, c.sentiment, c.created_at, c.updated_at,
                             np.notify_email, np.notify_whatsapp, np.email_address, np.whatsapp_number,
                             np.email_sent, np.whatsapp_sent
                """, call_id)
                
                if not row:
                    return {}
                
                topics_list = row.get("topics", [])
                notif_prefs = None
                if row.get("notify_email") is not None:
                    notif_prefs = {
                        "notify_email": row.get("notify_email", False),
                        "notify_whatsapp": row.get("notify_whatsapp", False),
                        "email_address": row.get("email_address"),
                        "whatsapp_number": row.get("whatsapp_number"),
                        "email_sent": row.get("email_sent", False),
                        "whatsapp_sent": row.get("whatsapp_sent", False)
                    }
                
                return _serialize_call_record(row, topics_list, notif_prefs)
        except asyncpg.PostgresError as exc:
            logger.error(f"[PostgreSQL] Fetch call failed for call_id={call_id}: {exc}")
            raise

    @staticmethod
    async def try_acquire_post_call_notification_lock(call_id: str) -> bool:
        """
        Atomically claim post-call notification dispatch for this call_id.

        Returns True only for the first caller; prevents duplicate WhatsApp/SMS
        when Retell retries call_analyzed webhooks.
        """
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
                        f"post_call_notify:{call_id}",
                    )
                    row = await conn.fetchrow(
                        """
                        SELECT whatsapp_sent FROM notification_preferences
                        WHERE call_id = $1
                        FOR UPDATE
                        """,
                        call_id,
                    )
                    if row and row["whatsapp_sent"]:
                        logger.info(
                            "[CallRecord] Post-call notifications already sent for call_id=%s",
                            call_id,
                        )
                        return False

                    if row:
                        await conn.execute(
                            """
                            UPDATE notification_preferences
                            SET whatsapp_sent = TRUE
                            WHERE call_id = $1
                            """,
                            call_id,
                        )
                    else:
                        await conn.execute(
                            """
                            INSERT INTO notification_preferences (
                                call_id, notify_email, notify_whatsapp,
                                email_sent, whatsapp_sent
                            ) VALUES ($1, FALSE, FALSE, FALSE, TRUE)
                            """,
                            call_id,
                        )
                    return True
        except asyncpg.PostgresError as exc:
            logger.error(
                "[CallRecord] Notification lock failed for call_id=%s: %s",
                call_id,
                exc,
            )
            return False

    @staticmethod
    async def release_post_call_notification_lock(call_id: str) -> None:
        """Allow a retry if notification dispatch was claimed but nothing was sent."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE notification_preferences
                    SET whatsapp_sent = FALSE
                    WHERE call_id = $1 AND COALESCE(email_sent, FALSE) = FALSE
                    """,
                    call_id,
                )
        except asyncpg.PostgresError as exc:
            logger.warning(
                "[CallRecord] Failed to release notification lock for call_id=%s: %s",
                call_id,
                exc,
            )

    @staticmethod
    async def is_call_analyzed_processed(call_id: str) -> bool:
        """True if this call was already saved from a prior call_analyzed webhook."""
        existing = await CallRecordService.fetch_call(call_id)
        if not existing:
            return False
        has_transcript = bool((existing.get("transcript") or "").strip())
        has_summary = bool((existing.get("summary") or "").strip())
        return has_transcript and has_summary

    @staticmethod
    async def get_summary() -> Dict:
        """Compute summary metrics."""
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                total_calls = await conn.fetchval("SELECT COUNT(*) FROM calls")
                conversions = await conn.fetchval(
                    "SELECT COUNT(*) FROM calls WHERE conversion_status = TRUE"
                )
                conversion_rate = conversions / total_calls if total_calls else 0.0
                return {
                    "total_calls": total_calls,
                    "conversions": conversions,
                    "conversion_rate": round(conversion_rate, 4),
                }
        except asyncpg.PostgresError as exc:
            logger.error(f"[PostgreSQL] Get summary failed: {exc}")
            raise
