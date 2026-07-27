"""Webhook security utilities for HMAC verification."""
import hmac
import hashlib
import logging
import re
import time

logger = logging.getLogger(__name__)


def verify_retell_signature(payload: str, signature: str, api_key: str) -> bool:
    """
    Verify x-retell-signature header from Retell webhooks.

    Uses Retell's official algorithm (same as retell-sdk):
    HMAC-SHA256(api_key, raw_body + timestamp_ms)
    Header format: v=<timestamp_ms>,d=<hex_digest>

  Requires the API key with the **webhook badge** from Retell Dashboard.
    """
    try:
        if not signature or not api_key:
            return False

        try:
            from retell.lib.webhook_auth import verify as retell_verify

            return bool(retell_verify(payload, api_key, signature.strip()))
        except ImportError:
            pass

        match = re.match(r"v=(\d+),d=(.*)", signature.strip())
        if not match:
            logger.warning("[Webhook Security] Invalid Retell signature format: %s", signature[:40])
            return False

        timestamp_ms = int(match.group(1))
        received_digest = match.group(2)

        if abs(int(time.time() * 1000) - timestamp_ms) > 5 * 60 * 1000:
            logger.warning("[Webhook Security] Retell signature timestamp expired")
            return False

        signed_content = f"{payload}{timestamp_ms}"
        expected_digest = hmac.new(
            api_key.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(expected_digest, received_digest)
        if not is_valid:
            logger.warning(
                "[Webhook Security] Invalid Retell signature (body_len=%s). "
                "Ensure RETELL_API_KEY is the key with the webhook badge in Retell Dashboard.",
                len(payload),
            )
        return is_valid
    except Exception as exc:
        logger.error("[Webhook Security] Error verifying Retell signature: %s", exc)
        return False


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
