"""Read-only Twilio SIP trunk diagnostics. Do not commit."""
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
sid = os.getenv("TWILIO_ACCOUNT_SID")
token = os.getenv("TWILIO_AUTH_TOKEN")
phone = (os.getenv("TWILIO_PHONE_NUMBER") or "").strip()
auth = (sid, token)
base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
trunk_base = "https://trunking.twilio.com/v1"


def get(url):
    r = httpx.get(url, auth=auth, timeout=30)
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.status_code, r.json()
    return r.status_code, r.text


def main():
    report = {}
    code, data = get(f"{base}.json")
    report["account"] = {
        "ok": code == 200,
        "friendly_name": data.get("friendly_name") if code == 200 else None,
        "status": data.get("status") if code == 200 else str(data)[:300],
    }

    code, data = get(f"{base}/IncomingPhoneNumbers.json?PageSize=50")
    nums = []
    if code == 200:
        for n in data.get("incoming_phone_numbers", []):
            nums.append(
                {
                    "phone": n.get("phone_number"),
                    "voice_url": n.get("voice_url"),
                    "voice_application_sid": n.get("voice_application_sid"),
                    "trunk_sid": n.get("trunk_sid"),
                    "sms_url": n.get("sms_url"),
                }
            )
    report["phone_numbers"] = nums
    report["target_number"] = next((n for n in nums if n["phone"] == phone), None)

    code, data = get(f"{trunk_base}/Trunks")
    trunks = []
    if code == 200:
        for t in data.get("trunks", []):
            tsid = t["sid"]
            trunk_info = {
                "sid": tsid,
                "friendly_name": t.get("friendly_name"),
                "domain_name": t.get("domain_name"),
            }
            c, term = get(f"{trunk_base}/Trunks/{tsid}")
            if c == 200:
                trunk_info["domain_name"] = term.get("domain_name")
            c, creds = get(f"{trunk_base}/Trunks/{tsid}/CredentialLists")
            if c == 200:
                trunk_info["credential_list_sids"] = [
                    x.get("sid") for x in creds.get("credential_lists", [])
                ]
            c, ipacl = get(f"{trunk_base}/Trunks/{tsid}/IpAccessControlLists")
            if c == 200:
                trunk_info["ip_acl_sids"] = [
                    x.get("sid") for x in ipacl.get("ip_access_control_lists", [])
                ]
            c, orig = get(f"{trunk_base}/Trunks/{tsid}/OriginationUrls")
            if c == 200:
                trunk_info["origination_urls"] = [
                    u.get("sip_url") for u in orig.get("origination_urls", [])
                ]
            trunks.append(trunk_info)
    report["sip_trunks"] = trunks

    code, data = get(f"{trunk_base}/CredentialLists")
    cred_lists = []
    if code == 200:
        for cl in data.get("credential_lists", []):
            clsid = cl["sid"]
            c2, creds = get(f"{trunk_base}/CredentialLists/{clsid}/Credentials")
            usernames = []
            if c2 == 200:
                usernames = [cr.get("username") for cr in creds.get("credentials", [])]
            cred_lists.append(
                {
                    "friendly_name": cl.get("friendly_name"),
                    "sid": clsid,
                    "usernames": usernames,
                }
            )
    report["credential_lists"] = cred_lists

    code, data = get(f"{trunk_base}/IpAccessControlLists")
    ipacls = []
    if code == 200:
        for acl in data.get("ip_access_control_lists", []):
            asid = acl["sid"]
            c2, ips = get(f"{trunk_base}/IpAccessControlLists/{asid}/IpAddresses")
            ip_list = []
            if c2 == 200:
                for i in ips.get("ip_addresses", []):
                    prefix = i.get("cidr_prefix_length", 32)
                    ip_list.append(f"{i.get('ip_address')}/{prefix}")
            ipacls.append(
                {"friendly_name": acl.get("friendly_name"), "sid": asid, "ips": ip_list}
            )
    report["ip_acls"] = ipacls

    issues = []
    target = report.get("target_number")
    if not target:
        issues.append(f"Phone {phone} not found in this Twilio account")
    elif not target.get("trunk_sid"):
        issues.append(f"{phone} is NOT attached to an Elastic SIP Trunk (voice_url={target.get('voice_url')})")
    else:
        trunk_match = next((t for t in trunks if t["sid"] == target["trunk_sid"]), None)
        if trunk_match:
            report["attached_trunk"] = trunk_match
            has_creds = bool(trunk_match.get("credential_list_sids"))
            has_ip = bool(trunk_match.get("ip_acl_sids"))
            if not has_creds and not has_ip:
                issues.append("SIP trunk has NO credential list AND NO IP ACL — Retell cannot authenticate outbound")
            orig = trunk_match.get("origination_urls") or []
            if not any("sip.retellai.com" in (u or "") for u in orig):
                issues.append(f"Origination missing sip.retellai.com (current: {orig})")
            retell_ip = "18.98.16.120"
            all_ips = [ip for acl in ipacls for ip in acl.get("ips", [])]
            if has_ip and not any(retell_ip in ip for ip in all_ips):
                issues.append(f"IP ACLs do not include Retell range 18.98.16.120/30 (found: {all_ips})")

    report["issues"] = issues
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
