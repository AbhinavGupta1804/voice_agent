# ElevenLabs: Append-to-Ticket Tool Setup

Backend exposes a new tool **append_to_ticket** so the agent can add a second (or more) complaint to the **same** ticket on one call. Follow these steps in the ElevenLabs dashboard.

---

## 1. Add the new tool in ElevenLabs

In your **Conversational AI** agent → **Tools** (or **Custom Tools**):

- **Add a new tool** (same way you added `create_ticket` and others).
- **Name:** `append_to_ticket` (must match the URL path below).
- **URL:**  
  `https://YOUR_BACKEND_URL/api/elevenlabs/append_to_ticket`  
  (e.g. `https://your-ngrok-or-domain.com/api/elevenlabs/append_to_ticket`)
- **Method:** `POST`
- **Headers:** same as your other tools (e.g. if you use auth, add it here).
- **Request body (JSON):**
  - `ticket_id` (number, required) – The ticket ID from the **first** complaint on this call (e.g. `5`).
  - `additional_issue_description` (string, required) – The new complaint to add to that same ticket.

Example body the agent should send:

```json
{
  "ticket_id": 5,
  "additional_issue_description": "Delivery was late and packaging was damaged."
}
```

Map your agent’s “function” or “parameters” so that:
- When the user gives a **second complaint on the same call**, the agent calls **append_to_ticket** with the **ticket_id** it received from the first **create_ticket** response and the new issue as **additional_issue_description**.

---

## 2. Agent instructions (prompt)

In the agent’s **Instructions** or **System prompt**, add (or merge) something like:

- **One ticket per call:** For the **first** complaint on a call → use **create_ticket** (ask name, then create). For **any further** complaint on the **same** call → use **append_to_ticket** with the **same ticket_id** and the new issue. Do **not** create a new ticket for the second complaint.
- **Remember the ticket number:** After create_ticket returns, the agent is told the ticket number (e.g. “Ticket number hai 5”). The agent must **remember this number** for the rest of the call and use it as `ticket_id` when calling append_to_ticket.
- **Wording:** When confirming, say “complain ticket” (e.g. “Maine aapki yeh complaint bhi isi complain ticket mein add kar di hai” after append).

Example instruction block you can paste or adapt:

```
Complaint handling:
- First complaint on the call: ask customer's name, then call create_ticket. Remember the ticket_id returned (e.g. 5).
- If the customer has another complaint on the SAME call: call append_to_ticket with that same ticket_id and the new issue. Do NOT create a second ticket.
- Always say "complain ticket" (not "support ticket") when creating or confirming.
```

---

## 3. Summary

| Action | Tool | When |
|--------|------|------|
| First complaint on call | **create_ticket** | After getting customer name. |
| Second (or more) complaint on same call | **append_to_ticket** | Use the ticket_id from the first create_ticket response. |

Backend will:
- Append the new issue to the same row in the DB and update the product website.
- Update the same ticket in Zoho (using stored `zoho_ticket_id`) so CRM stays in sync.
