"""
Test script to simulate what ElevenLabs sends to the groq_proxy.
Run: python test_groq_proxy.py
"""
import requests
import json
import sys

# Fix encoding for Windows
sys.stdout.reconfigure(encoding='utf-8')

NGROK_URL = "https://maya-unanemic-honey.ngrok-free.dev"
LOCAL_URL = "http://localhost:8000"
BASE_URL = LOCAL_URL

elevenlabs_tools = [
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": "Create a support ticket for customer complaints",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "issue_description": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
                },
                "required": ["customer_name", "issue_description"],
            },
        },
    }
]


def check_streaming_response(resp):
    """Check streaming response for errors."""
    errors = []
    chunks = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        if line == "data: [DONE]":
            continue
        payload = line[len("data: "):]
        try:
            d = json.loads(payload)
            if "error" in d:
                errors.append(d["error"])
            else:
                chunks.append(d)
        except json.JSONDecodeError:
            pass
    return chunks, errors


def run_test(name, url, body, stream=False):
    """Run a single test and print result."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    try:
        r = requests.post(
            url,
            json=body,
            headers={
                "Content-Type": "application/json",
                "ngrok-skip-browser-warning": "true",
            },
            timeout=30,
            stream=stream,
        )
        print(f"  Status: {r.status_code}")

        if "<html" in r.text[:200].lower():
            print(f"  RESULT: FAIL - Got HTML page (ngrok warning?)")
            return

        if stream:
            chunks, errors = check_streaming_response(r)
            if errors:
                print(f"  ERRORS FOUND:")
                for e in errors:
                    print(f"    >> {json.dumps(e, indent=4)}")
                print(f"  RESULT: FAIL")
            else:
                # Reconstruct content from chunks
                content = ""
                for c in chunks:
                    delta = c.get("choices", [{}])[0].get("delta", {})
                    content += delta.get("content", "")
                print(f"  Content: {content[:200]}")
                print(f"  Chunks received: {len(chunks)}")
                print(f"  RESULT: PASS")
        else:
            data = r.json()
            if "error" in data:
                print(f"  ERROR: {json.dumps(data['error'], indent=4)}")
                print(f"  RESULT: FAIL")
            else:
                msg = data.get("choices", [{}])[0].get("message", {})
                print(f"  Content: {(msg.get('content') or '')[:200]}")
                print(f"  Tool calls: {msg.get('tool_calls')}")
                print(f"  RESULT: PASS")

    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        print(f"  RESULT: FAIL")


# ── Run all tests ────────────────────────────────────────

# Test 1: Basic non-streaming
run_test(
    "Non-streaming, no tools (LOCAL)",
    f"{BASE_URL}/v1/chat/completions",
    {"messages": [{"role": "user", "content": "hello"}], "stream": False},
)

# Test 2: Basic streaming
run_test(
    "Streaming, no tools (LOCAL)",
    f"{BASE_URL}/v1/chat/completions",
    {"messages": [{"role": "user", "content": "hello"}], "stream": True},
    stream=True,
)

# Test 3: Streaming + tools + tool_choice as OBJECT
run_test(
    "Streaming + tools + tool_choice OBJECT (LOCAL) -- ElevenLabs format",
    f"{BASE_URL}/v1/chat/completions",
    {
        "messages": [{"role": "user", "content": "mera order galat aaya"}],
        "stream": True,
        "tools": elevenlabs_tools,
        "tool_choice": {"type": "function", "function": {"name": "create_ticket"}},
    },
    stream=True,
)

# Test 4: Streaming + tools + tool_choice as STRING
run_test(
    "Streaming + tools + tool_choice STRING 'auto' (LOCAL)",
    f"{BASE_URL}/v1/chat/completions",
    {
        "messages": [{"role": "user", "content": "mera order galat aaya"}],
        "stream": True,
        "tools": elevenlabs_tools,
        "tool_choice": "auto",
    },
    stream=True,
)

# Test 5: Same as Test 3 but through NGROK
run_test(
    "Streaming + tools + tool_choice OBJECT (NGROK) -- Real ElevenLabs path",
    f"{NGROK_URL}/v1/chat/completions",
    {
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "tools": elevenlabs_tools,
        "tool_choice": {"type": "function", "function": {"name": "create_ticket"}},
    },
    stream=True,
)

# Test 6: Non-streaming + tools (ElevenLabs sometimes uses this)
run_test(
    "Non-streaming + tools + tool_choice OBJECT (LOCAL)",
    f"{BASE_URL}/v1/chat/completions",
    {
        "messages": [{"role": "user", "content": "mera order galat aaya"}],
        "stream": False,
        "tools": elevenlabs_tools,
        "tool_choice": {"type": "function", "function": {"name": "create_ticket"}},
    },
)

print(f"\n{'='*60}")
print("ALL TESTS COMPLETE")
print(f"{'='*60}")
