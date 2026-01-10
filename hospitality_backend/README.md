# Hospitality AI Caller Backend

Inbound call handling system for restaurants, hotels, and bars.

## Setup

1. Create virtual environment using uv:
```bash
cd hospitality_backend
uv venv
.venv\Scripts\activate  # On Windows
source .venv/bin/activate  # On Linux/Mac
```

2. Install dependencies:
```bash
uv pip install -r requirements.txt
```

3. Create `.env` file (copy from `.env.example`):
```bash
cp .env.example .env
```

4. Configure your environment variables in `.env`

5. Run the server:
```bash
cd app
python main.py
```

The server will run on port 8001 by default.

## Features

- **Inbound Call Handling**: WebSocket-based media streaming between Twilio and ElevenLabs
- **Order Management**: Extract order details from call transcripts and create orders
- **WhatsApp Notifications**: Send order confirmations with estimated time via WhatsApp
- **Call History**: Track all inbound calls with transcripts and summaries
- **Analytics**: Restaurant analytics including revenue, orders, and popular items

