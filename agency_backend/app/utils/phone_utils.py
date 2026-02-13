
def normalize_phone_number(phone: str) -> str:
    """
    Normalize a phone number to E.164 format.
    Specifically handles Indian numbers by ensuring +91 prefix.
    
    Args:
        phone: meaningful phone number string
        
    Returns:
        Normalized phone number string (e.g. +919876543210)
    """
    if not phone:
        return ""
        
    # Remove common prefixes that might be duplicated or malformed
    cleaned = phone.replace("whatsapp:", "").strip()
    
    # Remove all non-digit characters except leading +
    # If it starts with +, keep it. If not, just digits.
    digits_only = "".join(c for c in cleaned if c.isdigit())
    
    if not digits_only:
        return phone # Return original if we can't parse digits
        
    # Logic for Indian numbers (common case for this app)
    # If 10 digits, assume India and add +91
    if len(digits_only) == 10:
        return f"+91{digits_only}"
        
    # If 12 digits and starts with 91, assume India and ensure +
    if len(digits_only) == 12 and digits_only.startswith("91"):
        return f"+{digits_only}"
        
    # For other cases, ensure it starts with + if it's meant to be E.164
    # If the original had a +, assume the digits are correct country code
    if cleaned.startswith("+"):
        return f"+{digits_only}"
        
    # Fallback: if no +, and not 10 digits, we just add + to whatever digits we found
    # assuming the user provided a full country code
    return f"+{digits_only}"
