"""
Fix New Claude Agent (15).json for Retell dashboard import + optional API deploy.

Import failure root cause: voicemail_option.action.type "ignore" is invalid.
Valid values: hangup | prompt | static_text | bridge_transfer.
To disable voicemail detection, set voicemail_option to null.

Usage:
  python scripts/fix_agent_15_import.py           # fix JSON only
  python scripts/fix_agent_15_import.py --deploy  # fix JSON + push to Retell
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "docs" / "New Claude Agent (15).json"
RETELL_API = "https://api.retellai.com"


def fix_agent_data(data: dict) -> dict:
    cf = data["conversationFlow"]

    # --- import blockers ---
    data["voicemail_option"] = None  # disable voicemail detection (was invalid "ignore")
    data["agent_id"] = ""
    data["is_published"] = False
    cf["is_published"] = False

    # stable voice + model for import
    if data.get("voice_id") in (None, "", "retell-Cimo", "11labs-Cimo"):
        data["voice_id"] = "fish_audio-Cimo"

    cf["model_choice"] = {
        "type": "cascading",
        "model": "gpt-4.1",
        "high_priority": False,
    }
    cf["tool_call_strict_mode"] = False

    # remove broken global-node placeholder (causes bad routing on import)
    for node in cf["nodes"]:
        gns = node.get("global_node_setting")
        if gns and "Describe the" in str(gns.get("condition", "")):
            node.pop("global_node_setting", None)

        # Retell requires exact "Else" on else_edge prompts
        else_edge = node.get("else_edge")
        if else_edge:
            tc = else_edge.get("transition_condition") or {}
            if tc.get("type") == "prompt" and (tc.get("prompt") or "").strip().lower() == "else":
                tc["prompt"] = "Else"

        mc = node.get("model_choice")
        if mc and mc.get("model") in ("gemini-3.0-flash", "gpt-4.1-mini"):
            mc["model"] = "gpt-4.1"
            mc["high_priority"] = False

    return data


def build_flow_payload(cf: dict) -> dict:
    return {
        "global_prompt": cf["global_prompt"],
        "nodes": cf["nodes"],
        "tools": cf["tools"],
        "start_node_id": cf["start_node_id"],
        "start_speaker": cf.get("start_speaker", "agent"),
        "model_choice": cf["model_choice"],
        "tool_call_strict_mode": cf.get("tool_call_strict_mode", False),
        "flex_mode": cf.get("flex_mode", True),
        "kb_config": cf.get("kb_config"),
        "knowledge_base_ids": cf.get("knowledge_base_ids", []),
    }


def deploy(data: dict, api_key: str, agent_id: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    cf = data["conversationFlow"]

    with httpx.Client(timeout=60) as client:
        # get current agent to find conversation_flow_id
        agent_resp = client.get(f"{RETELL_API}/get-agent/{agent_id}", headers=headers)
        agent_resp.raise_for_status()
        agent = agent_resp.json()
        flow_id = agent["response_engine"]["conversation_flow_id"]
        print(f"Existing agent: {agent_id} flow: {flow_id}")

        flow_payload = build_flow_payload(cf)
        update_flow = client.patch(
            f"{RETELL_API}/update-conversation-flow/{flow_id}",
            headers=headers,
            json=flow_payload,
        )
        if update_flow.status_code not in (200, 201):
            print("update-conversation-flow failed:", update_flow.status_code, update_flow.text[:800])
            update_flow.raise_for_status()
        print("Updated conversation flow:", flow_id)

        agent_payload = {
            "agent_name": data.get("agent_name", "New Claude Agent"),
            "voice_id": data["voice_id"],
            "language": data.get("language", "en-US"),
            "webhook_url": data.get("webhook_url"),
            "end_call_after_silence_ms": data.get("end_call_after_silence_ms", 180000),
            "max_call_duration_ms": data.get("max_call_duration_ms", 900000),
            "interruption_sensitivity": data.get("interruption_sensitivity", 0.7),
            "responsiveness": data.get("responsiveness", 0.8),
            "voicemail_option": None,
            "custom_stt_config": data.get("custom_stt_config"),
            "stt_mode": data.get("stt_mode"),
            "post_call_analysis_model": data.get("post_call_analysis_model", "gpt-4.1-mini"),
        }
        update_agent = client.patch(
            f"{RETELL_API}/update-agent/{agent_id}",
            headers=headers,
            json=agent_payload,
        )
        if update_agent.status_code not in (200, 201):
            print("update-agent failed:", update_agent.status_code, update_agent.text[:800])
            update_agent.raise_for_status()
        print("Updated agent:", agent_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true", help="Push fixed config to Retell API")
    args = parser.parse_args()

    data = json.loads(SRC.read_text(encoding="utf-8"))
    data = fix_agent_data(data)
    SRC.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Fixed import JSON: {SRC}")
    print("  voicemail_option -> null")
    print("  model -> gpt-4.1")
    print("  voice -> fish_audio-Cimo")

    if args.deploy:
        load_dotenv(ROOT / ".env")
        api_key = os.getenv("RETELL_API_KEY")
        agent_id = os.getenv("RETELL_AGENT_ID")
        if not api_key or not agent_id:
            print("ERROR: RETELL_API_KEY and RETELL_AGENT_ID required for --deploy", file=sys.stderr)
            sys.exit(1)
        deploy(data, api_key, agent_id)
        print("Deploy complete. Re-test a call — no manual import needed.")


if __name__ == "__main__":
    main()
