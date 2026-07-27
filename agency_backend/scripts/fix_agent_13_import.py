"""Fix New Claude Agent (13).json so Retell dashboard import/API validation succeeds."""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "New Claude Agent (13).json"
data = json.loads(path.read_text(encoding="utf-8"))
cf = data["conversationFlow"]

# concise_agent_13.py wrongly lowercased Else edges — Retell requires exact "Else"
for node in cf["nodes"]:
    else_edge = node.get("else_edge")
    if not else_edge:
        continue
    tc = else_edge.get("transition_condition") or {}
    if tc.get("type") == "prompt" and (tc.get("prompt") or "").lower() == "else":
        tc["prompt"] = "Else"

# gemini-3.0-flash may not be enabled on all accounts; use stable default
cf["model_choice"] = {
    "type": "cascading",
    "model": "gpt-4.1-mini",
    "high_priority": False,
}

# Valid voice id (11labs-Cimo works but fish_audio-Cimo matches current Retell defaults)
data["voice_id"] = data.get("voice_id") or "fish_audio-Cimo"
if data.get("voice_id") == "11labs-Cimo":
    data["voice_id"] = "fish_audio-Cimo"

# Import expects a new agent draft, not an existing published id
data["agent_id"] = ""
data["is_published"] = False
cf["is_published"] = False

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Fixed {path.name}")
