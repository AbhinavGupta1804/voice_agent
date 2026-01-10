"""Service layer for call record metadata storage (in-memory) and R2 audio storage."""
import asyncio
import base64
import logging
import os
import tempfile
from typing import Dict, Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from config import Config
from db.postgres import get_db_pool

logger = logging.getLogger(__name__)


class CallRecordService:
    """In-memory storage for call metadata linking."""
    
    # In-memory store for call metadata (call_sid -> caller info)
    _call_metadata: Dict[str, Dict[str, str]] = {}
    
    # In-memory store for linking conversation_id to call_sid
    _conversation_to_call: Dict[str, str] = {}
    
    @staticmethod
    async def store_call_metadata(call_sid: str, caller_name: str, phone_number: str):
        """Store caller name and phone number for a call."""
        CallRecordService._call_metadata[call_sid] = {
            "caller_name": caller_name,
            "phone_number": phone_number
        }
        logger.info(f"[CallRecord] Stored metadata for call_sid={call_sid}: {caller_name}, {phone_number}")
    
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
    async def get_caller_name_from_conversation(conversation_id: str) -> Optional[str]:
        """Retrieve caller name from call metadata using conversation_id."""
        call_sid = CallRecordService._conversation_to_call.get(conversation_id)
        if call_sid:
            metadata = CallRecordService._call_metadata.get(call_sid, {})
            caller_name = metadata.get("caller_name")
            if caller_name:
                return caller_name
        return None
    
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
            
            logger.info(f"[CallRecord] Generated public URL: {public_url}")
            return public_url
            
        except Exception as e:
            logger.error(f"[CallRecord] Failed to upload audio to R2 for {conversation_id}: {e}", exc_info=True)
            return None
    
    @staticmethod
    async def update_recording_url(conversation_id: str, recording_url: str) -> bool:
        """
        Update or create a call record with recording_url.
        
        Args:
            conversation_id: The conversation/call ID
            recording_url: Public URL to the audio recording
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from datetime import datetime, timezone
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Try to update existing record
                    result = await conn.execute("""
                        UPDATE "Hospitality".calls 
                        SET recording_url = $1, updated_at = NOW()
                        WHERE call_id = $2
                    """, recording_url, conversation_id)
                    
                    # Check if update was successful (result format: "UPDATE 1" or "UPDATE 0")
                    if result and "UPDATE" in result and result.split()[-1] != '0':
                        logger.info(f"[CallRecord] Updated recording_url for existing record {conversation_id}")
                        return True
                    
                    # If no record exists, create a minimal one with just call_id and recording_url
                    logger.info(f"[CallRecord] No record found for {conversation_id}, creating minimal record with recording_url")
                    await conn.execute("""
                        INSERT INTO "Hospitality".calls (call_id, recording_url, caller_name, transcript, summary, duration_sec, call_timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (call_id) DO UPDATE SET
                            recording_url = EXCLUDED.recording_url,
                            updated_at = NOW()
                    """,
                        conversation_id,
                        recording_url,
                        "Customer",  # Placeholder, will be updated by transcript webhook
                        "",  # Placeholder
                        "",  # Placeholder
                        0,  # Default duration
                        datetime.now(timezone.utc)  # Current timestamp
                    )
                    logger.info(f"[CallRecord] Created minimal record for {conversation_id} with recording_url")
                    return True
                    
        except Exception as e:
            logger.error(f"[CallRecord] Failed to update/create recording_url for {conversation_id}: {e}", exc_info=True)
            return False

