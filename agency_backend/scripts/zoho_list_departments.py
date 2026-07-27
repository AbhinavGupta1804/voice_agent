"""List Zoho Desk org ID and department IDs (paste into .env)."""
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ORG_ID = os.getenv("ZOHO_ORG_ID")
API_DOMAIN = (os.getenv("ZOHO_API_DOMAIN") or "https://desk.zoho.in").rstrip("/")
ACCOUNTS = (os.getenv("ZOHO_ACCOUNTS_DOMAIN") or "https://accounts.zoho.in").rstrip("/")


async def refresh_token() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{ACCOUNTS}/oauth/v2/token",
            data={
                "refresh_token": REFRESH_TOKEN,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
        )
        if r.status_code != 200:
            print("Token refresh failed:", r.text)
            sys.exit(1)
        return r.json()["access_token"]


async def main():
    missing = [k for k, v in {
        "ZOHO_CLIENT_ID": CLIENT_ID,
        "ZOHO_CLIENT_SECRET": CLIENT_SECRET,
        "ZOHO_REFRESH_TOKEN": REFRESH_TOKEN,
    }.items() if not v]
    if missing:
        print("Missing in .env:", ", ".join(missing))
        sys.exit(1)

    token = await refresh_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # Organizations (org ID)
        r = await client.get(f"{API_DOMAIN}/api/v1/organizations", headers=headers)
        if r.status_code != 200:
            print("Organizations API failed:", r.status_code, r.text)
            sys.exit(1)
        orgs = r.json().get("data") or []
        if not orgs:
            print("No organizations found for this token.")
            sys.exit(1)

        print("\n=== Zoho Desk organizations ===")
        for o in orgs:
            oid = o.get("id")
            print(f"  ZOHO_ORG_ID={oid}  ({o.get('companyName', o.get('portalName', ''))})")

        org_id = ORG_ID or str(orgs[0]["id"])
        if not ORG_ID:
            print(f"\n(Using first org: {org_id})")

        # Departments
        h = {**headers, "orgId": str(org_id)}
        r = await client.get(f"{API_DOMAIN}/api/v1/departments", headers=h)
        if r.status_code != 200:
            print("\nDepartments API failed:", r.status_code, r.text)
            print("Tip: add Desk.basic.READ or Desk.settings.READ scope to your OAuth client.")
            sys.exit(1)

        depts = r.json().get("data") or []
        print(f"\n=== Departments (org {org_id}) ===")
        if not depts:
            print("  No departments. Create one: Setup → Organization → Departments")
        for d in depts:
            print(
                f"  ZOHO_DEPARTMENT_ID={d.get('id')}  "
                f"name={d.get('name')}  "
                f"default={'yes' if d.get('isDefault') else 'no'}"
            )
        print("\nCopy the IDs into agency_backend/.env and restart uvicorn.")


if __name__ == "__main__":
    asyncio.run(main())
