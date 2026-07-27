"""Exchange Zoho auth code for refresh token; reads/writes agency_backend/.env."""
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv, set_key
import os

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
load_dotenv(ENV)

code = (sys.argv[1] if len(sys.argv) > 1 else None) or os.getenv("ZOHO_AUTH_CODE")
client_id = os.getenv("ZOHO_CLIENT_ID")
client_secret = os.getenv("ZOHO_CLIENT_SECRET")
accounts = (os.getenv("ZOHO_ACCOUNTS_DOMAIN") or "https://accounts.zoho.in").rstrip("/")

if not client_id or not client_secret:
    print("ERROR: Set ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET in .env")
    sys.exit(1)
if not code:
    print("ERROR: Pass code as argument or set ZOHO_AUTH_CODE in .env")
    print("  python scripts/get_zoho_refresh.py YOUR_CODE")
    sys.exit(1)

r = httpx.post(
    f"{accounts}/oauth/v2/token",
    data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
    },
    timeout=30,
)
data = r.json()
if r.status_code != 200 or not data.get("refresh_token"):
    print("FAILED:", r.text)
    sys.exit(1)

token = data["refresh_token"]
print("SUCCESS refresh_token:", token)

text = ENV.read_text(encoding="utf-8")
if re.search(r"^ZOHO_REFRESH_TOKEN=", text, re.M):
    text = re.sub(r"^ZOHO_REFRESH_TOKEN=.*$", f"ZOHO_REFRESH_TOKEN={token}", text, flags=re.M)
else:
    text = text.rstrip() + f"\nZOHO_REFRESH_TOKEN={token}\n"
text = re.sub(r"^ZOHO_AUTH_CODE=.*\n?", "", text, flags=re.M)
ENV.write_text(text, encoding="utf-8")
print("Updated .env ZOHO_REFRESH_TOKEN (cleared ZOHO_AUTH_CODE)")
