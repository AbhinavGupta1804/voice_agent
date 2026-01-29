# Twilio Voice Configuration Guide: Inbound & Outbound Calls

This guide explains how to set up **both inbound and outbound calls** using the **same Twilio phone number** with ElevenLabs.

## Problem

Twilio only allows you to set **one webhook URL** per phone number for voice calls. However:
- **Outbound calls** need to use your backend's TwiML endpoint (`/outbound-call-twiml`)
- **Inbound calls** need to route to ElevenLabs' webhook (`https://api.us.elevenlabs.io/twilio/inbound_call`)

## Solution

We've created a **unified webhook endpoint** (`/voice-webhook`) that automatically detects whether a call is inbound or outbound and routes it appropriately.

## How It Works

1. **For Inbound Calls** (when someone calls your Twilio number):
   - Twilio calls your `/voice-webhook` endpoint
   - The endpoint detects it's an inbound call
   - It proxies/forwards the request to ElevenLabs' webhook: `https://api.us.elevenlabs.io/twilio/inbound_call`
   - ElevenLabs processes the call and returns TwiML
   - The TwiML is forwarded back to Twilio

2. **For Outbound Calls** (when your backend initiates a call):
   - Your backend uses Twilio API to initiate a call with a specific TwiML URL: `/outbound-call-twiml`
   - This endpoint is called directly by Twilio (not through `/voice-webhook`)
   - The existing outbound call flow continues to work as before

## Setup Instructions

### Step 1: Configure Twilio Voice Webhook

In your Twilio Console:

1. Go to **Phone Numbers** → **Manage** → **Active numbers**
2. Click on your phone number
3. Scroll to **Voice & Fax** section
4. Under **A CALL COMES IN**, set:
   - **Webhook URL**: `https://08ffb542bc52.ngrok-free.app/voice-webhook`
   - **HTTP Method**: `POST`
5. Click **Save**

> **Note**: Replace `https://08ffb542bc52.ngrok-free.app` with your actual ngrok URL or production domain.

### Step 2: Verify Your Backend is Running

Make sure your backend server is running and accessible at the ngrok URL. Test the endpoint:

```bash
curl https://08ffb542bc52.ngrok-free.app/voice-webhook
```

### Step 3: Test Inbound Calls

1. Call your Twilio phone number from another phone
2. The call should route to your ElevenLabs agent
3. Check your backend logs to see the webhook being processed

### Step 4: Test Outbound Calls

Outbound calls continue to work as before - no changes needed. Your existing `/outbound-call` endpoint will use `/outbound-call-twiml` which is specified in the Twilio API call.

## Architecture Diagram

```
┌─────────────┐
│   Caller    │
└──────┬──────┘
       │
       │ Inbound Call
       ▼
┌─────────────────────┐
│   Twilio Number     │
└──────┬──────────────┘
       │
       │ POST /voice-webhook
       ▼
┌─────────────────────────────────────┐
│  Your Backend                       │
│  /voice-webhook                     │
│  (Detects inbound call)             │
└──────┬──────────────────────────────┘
       │
       │ Proxies to ElevenLabs
       ▼
┌─────────────────────────────────────┐
│  ElevenLabs                         │
│  /twilio/inbound_call               │
│  (Processes call, returns TwiML)    │
└──────┬──────────────────────────────┘
       │
       │ Returns TwiML
       ▼
┌─────────────────────┐
│   Twilio            │
│   (Connects call)   │
└─────────────────────┘
```

For Outbound Calls:

```
┌─────────────────────┐
│  Your Backend       │
│  /outbound-call     │
│  (Initiates call)   │
└──────┬──────────────┘
       │
       │ Twilio API call with URL
       ▼
┌─────────────────────┐
│   Twilio            │
└──────┬──────────────┘
       │
       │ GET /outbound-call-twiml
       ▼
┌─────────────────────┐
│  Your Backend       │
│  /outbound-call-twiml│
│  (Returns TwiML)    │
└──────┬──────────────┘
       │
       │ TwiML with WebSocket
       ▼
┌─────────────────────┐
│   Twilio            │
│   (Connects call)   │
└─────────────────────┘
```

## Configuration Details

### Inbound Call Detection

The `/voice-webhook` endpoint detects inbound calls by checking:
- `Direction` parameter: `inbound`
- `To` number matches your Twilio phone number
- `CallStatus` is `ringing` (initial webhook)

### Environment Variables

Ensure these are set in your `.env`:

```env
TWILIO_PHONE_NUMBER=+1234567890
NGROK_URL=https://08ffb542bc52.ngrok-free.app
ELEVENLABS_API_KEY=your_key
ELEVENLABS_AGENT_ID=your_agent_id
```

## Troubleshooting

### Calls not routing to ElevenLabs

1. Check that `/voice-webhook` is accessible
2. Verify Twilio webhook is set correctly in console
3. Check backend logs for webhook requests
4. Ensure ElevenLabs webhook URL is correct: `https://api.us.elevenlabs.io/twilio/inbound_call`

### Outbound calls not working

1. Outbound calls use a different endpoint (`/outbound-call-twiml`) - they shouldn't go through `/voice-webhook`
2. Check that your ngrok URL is accessible
3. Verify Twilio API credentials are correct

### Mixed call routing

- Inbound calls go to `/voice-webhook` → ElevenLabs
- Outbound calls go directly to `/outbound-call-twiml` → Your backend WebSocket

These are handled separately, so there's no conflict.

## Alternative Approach: Native ElevenLabs Integration

If you prefer a simpler setup without managing webhooks yourself, you can use ElevenLabs' **Native Integration**:

1. Import your Twilio number into ElevenLabs dashboard
2. Assign it to your agent
3. ElevenLabs manages the webhooks automatically

However, this approach gives you less control over custom routing logic and dynamic variables.

## Support

If you encounter issues:
1. Check the backend logs for detailed webhook information
2. Verify all environment variables are set correctly
3. Test the endpoints individually using curl or Postman
