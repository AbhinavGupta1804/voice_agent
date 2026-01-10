"""Webhook security utilities for HMAC verification."""
import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)


def verify_hmac_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify HMAC signature from ElevenLabs webhook.
    
    ElevenLabs sends signatures in the format: "t=<timestamp>,v0=<signature>"
    The HMAC is computed as: HMAC-SHA256(secret, timestamp + "." + payload)
    
    Args:
        payload: Raw request body as bytes
        signature: Signature from ElevenLabs-Signature header
        secret: Shared secret from ElevenLabs console
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        # Parse the signature header: "t=<timestamp>,v0=<signature>"
        parts = {}
        for part in signature.split(','):
            if '=' in part:
                key, value = part.split('=', 1)
                parts[key] = value
        
        timestamp = parts.get('t')
        received_signature = parts.get('v0')
        
        if not timestamp or not received_signature:
            logger.warning("[Webhook Security] Invalid signature format")
            return False
        
        # Compute HMAC-SHA256 signature: HMAC(secret, timestamp + "." + payload)
        signed_payload = f"{timestamp}.".encode('utf-8') + payload
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        is_valid = hmac.compare_digest(expected_signature, received_signature)
        
        if not is_valid:
            logger.warning("[Webhook Security] Invalid HMAC signature")
        
        return is_valid
    
    except Exception as e:
        logger.error(f"[Webhook Security] Error verifying signature: {e}")
        return False
