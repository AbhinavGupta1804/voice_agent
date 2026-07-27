"""
Fix premature hangup issues in Agent 15.

Changes:
1. Disable voicemail detection (biggest culprit for false positives)
2. Increase endpointing from 500ms -> 800ms (less aggressive)
3. Lower interruption sensitivity from 0.9 -> 0.7 (reduce false triggers)
4. Increase max call duration from 598s -> 900s (15 min)
5. Increase silence timeout from 119s -> 180s (3 min for WhatsApp flow)
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "docs", "New Claude Agent (15).json"))
DST = os.path.normpath(os.path.join(HERE, "..", "docs", "New Claude Agent (15).json"))

with open(SRC, "r", encoding="utf-8") as f:
    data = json.load(f)

# 1. Disable voicemail detection (don't hangup on suspected voicemail)
data["voicemail_option"] = {
    "action": {
        "type": "ignore"  # changed from "hangup"
    }
}

# 2. Increase endpointing - give users more time to pause naturally
data["custom_stt_config"]["endpointing_ms"] = 800  # was 500

# 3. Lower interruption sensitivity - reduce false positives
data["interruption_sensitivity"] = 0.7  # was 0.9

# 4. Increase max call duration for longer booking flows
data["max_call_duration_ms"] = 900000  # 15 minutes (was ~10 min)

# 5. Increase silence timeout for WhatsApp email wait
data["end_call_after_silence_ms"] = 180000  # 3 minutes (was ~2 min)

with open(DST, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Fixed hangup settings in:", DST)
print("\nChanges:")
print("- Voicemail detection: hangup -> ignore")
print("- Endpointing: 500ms -> 800ms")
print("- Interruption sensitivity: 0.9 -> 0.7")
print("- Max call duration: 598s -> 900s (15 min)")
print("- Silence timeout: 119s -> 180s (3 min)")
