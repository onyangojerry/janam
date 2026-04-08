# Janam Multi-Platform Connector Templates

This guide shows how to wire up WhatsApp, Signal, Facebook Messenger, Gmail, and Outlook to Janam's open-source ingest pipeline using n8n Function nodes.

## Overview

All connectors follow the same pattern:
1. **Receive webhook** from the platform (e.g., WhatsApp message event)
2. **Normalize fields** to Janam's `IngestEventRequest` schema
3. **Generate HMAC-SHA256 signature** for webhook security
4. **POST to `/ingest/n8n`** with signed headers

## Signature Generation

Every request to `/ingest/n8n` requires:
- `X-Janam-Webhook-Signature: sha256=<hex_signature>`
- `X-Janam-Webhook-Timestamp: <unix_seconds>`

The signature is computed as:
```
HMAC-SHA256(JANAM_N8N_WEBHOOK_SECRET, timestamp + "." + raw_body)
```

### n8n Helper Function

Paste this into any n8n Function node to generate signatures:

```javascript
// Helper: Generate HMAC-SHA256 signature for Janam /ingest/n8n
const crypto = require('crypto');

function generateJanamSignature(payload, secret) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const payloadString = typeof payload === 'string' ? payload : JSON.stringify(payload);
  const message = `${timestamp}.${payloadString}`;
  const signature = crypto
    .createHmac('sha256', secret)
    .update(message)
    .digest('hex');
  
  return {
    timestamp,
    signature: `sha256=${signature}`,
    headers: {
      'X-Janam-Webhook-Timestamp': timestamp,
      'X-Janam-Webhook-Signature': `sha256=${signature}`,
      'Content-Type': 'application/json'
    }
  };
}

// Usage:
// const sig = generateJanamSignature(payloadObject, $env.JANAM_N8N_WEBHOOK_SECRET);
// return { signature: sig };
```

---

## WhatsApp (via Meta Cloud API)

### n8n Setup

1. **Receive webhook** from Meta Cloud API
   - Webhook URL: `https://your-n8n-server.com/webhook/whatsapp`
   - Subscribe to: `messages` event

2. **Message event format** (from Meta):
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "123456",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "999888777", "display_phone_number": "1234567890"},
        "messages": [{
          "from": "919876543210",
          "type": "text",
          "id": "msg_id_xyz",
          "text": {"body": "Help! There is armed conflict in my area"},
          "timestamp": "1234567890"
        }]
      }
    }]
  }]
}
```

### n8n Function Node: WhatsApp Normalizer

```javascript
// Input: $node["Webhook"].json (Meta Cloud API message event)
// Output: Janam IngestEventRequest with signature headers

const crypto = require('crypto');
const input = $input.first().json;

// Extract WhatsApp message data
const message = input.entry?.[0]?.changes?.[0]?.value?.messages?.[0];
const metadata = input.entry?.[0]?.changes?.[0]?.value?.metadata;

if (!message) {
  throw new Error('Invalid WhatsApp message structure');
}

// Normalize to Janam schema
const janamPayload = {
  channel: 'whatsapp',
  platform: 'meta-cloud-api',
  sender_id: message.from,
  message_text: message.text?.body || '',
  external_event_id: message.id,
  timestamp_iso: new Date(parseInt(message.timestamp) * 1000).toISOString(),
  media_type: 'text',
  anonymous_mode: true,  // WhatsApp sources stay anonymous by default
  raw_payload: null      // Don't store raw Meta payload for privacy
};

// Generate signature
const secret = $env.JANAM_N8N_WEBHOOK_SECRET;
if (!secret) {
  throw new Error('Missing JANAM_N8N_WEBHOOK_SECRET in n8n environment');
}
const timestamp = Math.floor(Date.now() / 1000).toString();
const payloadString = JSON.stringify(janamPayload);
const message_to_sign = `${timestamp}.${payloadString}`;
const signature = crypto
  .createHmac('sha256', secret)
  .update(message_to_sign)
  .digest('hex');

return {
  payload: janamPayload,
  headers: {
    'X-Janam-Webhook-Timestamp': timestamp,
    'X-Janam-Webhook-Signature': `sha256=${signature}`,
    'Content-Type': 'application/json'
  },
  url: $env.JANAM_INGEST_URL || 'http://localhost:8000/api/ingest/n8n'
};
```

### Post to Janam (HTTP Request Node)

```
Method: POST
URL: {{ $json.url }}
Headers:
  X-Janam-Webhook-Timestamp: {{ $json.headers['X-Janam-Webhook-Timestamp'] }}
  X-Janam-Webhook-Signature: {{ $json.headers['X-Janam-Webhook-Signature'] }}
  Content-Type: application/json
Body:
  {{ JSON.stringify($json.payload) }}
```

---

## Signal (via Signal Bot API + n8n Webhook)

### Signal Bot Setup

Signal doesn't have native webhooks, but you can use:
- **Option A**: Run [signal-cli](https://github.com/AsamK/signal-cli) + n8n's HTTP Request node on a scheduled interval to poll
- **Option B**: Use a third-party Signal webhook service like [Signalwire](https://www.signalwire.com/)

For this example, we assume Signal messages are forwarded to n8n via `GET /webhook/signal?sender=+1234567890&text=...`.

### n8n Function Node: Signal Normalizer

```javascript
// Input: Query parameters from Signal webhook
//   ?sender=+1234567890&text=Help%20needed%20at%20coordinates...&id=msg_xyz
// Output: Janam IngestEventRequest with signature

const crypto = require('crypto');
const input = $input.first().json;

const janamPayload = {
  channel: 'signal',
  platform: 'signal-cli',
  sender_id: input.sender || 'unknown',
  message_text: input.text || '',
  external_event_id: input.id || `signal-${Date.now()}`,
  timestamp_iso: new Date().toISOString(),
  media_type: 'text',
  anonymous_mode: true,  // Signal sources stay anonymous
  raw_payload: null
};

// Generate signature
const secret = $env.JANAM_N8N_WEBHOOK_SECRET;
if (!secret) {
  throw new Error('Missing JANAM_N8N_WEBHOOK_SECRET in n8n environment');
}
const timestamp = Math.floor(Date.now() / 1000).toString();
const payloadString = JSON.stringify(janamPayload);
const message_to_sign = `${timestamp}.${payloadString}`;
const signature = crypto
  .createHmac('sha256', secret)
  .update(message_to_sign)
  .digest('hex');

return {
  payload: janamPayload,
  headers: {
    'X-Janam-Webhook-Timestamp': timestamp,
    'X-Janam-Webhook-Signature': `sha256=${signature}`,
    'Content-Type': 'application/json'
  },
  url: $env.JANAM_INGEST_URL || 'http://localhost:8000/api/ingest/n8n'
};
```

---

## Facebook Messenger (via Messenger Platform)

### Messenger Webhook Format

Facebook sends message events to your webhook URL (set in Messenger settings):

```json
{
  "object": "page",
  "entry": [{
    "id": "page_id_123",
    "time": 1234567890000,
    "messaging": [{
      "sender": {"id": "user_id_456"},
      "recipient": {"id": "page_id_123"},
      "timestamp": 1234567890000,
      "message": {
        "mid": "msg_id_xyz",
        "text": "Violence reported at central market area"
      }
    }]
  }]
}
```

### n8n Function Node: Facebook Messenger Normalizer

```javascript
// Input: $node["Webhook"].json (Messenger platform event)
// Output: Janam IngestEventRequest

const crypto = require('crypto');
const input = $input.first().json;

const messaging = input.entry?.[0]?.messaging?.[0];
if (!messaging?.message) {
  throw new Error('Invalid Messenger message structure');
}

const janamPayload = {
  channel: 'facebook_messenger',
  platform: 'meta-messenger-api',
  sender_id: messaging.sender?.id || 'unknown',
  message_text: messaging.message?.text || '',
  external_event_id: messaging.message?.mid || `fb-${Date.now()}`,
  timestamp_iso: new Date(messaging.timestamp).toISOString(),
  media_type: 'text',
  anonymous_mode: true,  // Messenger reporters stay anonymous
  raw_payload: null
};

// Generate signature
const secret = $env.JANAM_N8N_WEBHOOK_SECRET;
if (!secret) {
  throw new Error('Missing JANAM_N8N_WEBHOOK_SECRET in n8n environment');
}
const timestamp = Math.floor(Date.now() / 1000).toString();
const payloadString = JSON.stringify(janamPayload);
const message_to_sign = `${timestamp}.${payloadString}`;
const signature = crypto
  .createHmac('sha256', secret)
  .update(message_to_sign)
  .digest('hex');

return {
  payload: janamPayload,
  headers: {
    'X-Janam-Webhook-Timestamp': timestamp,
    'X-Janam-Webhook-Signature': `sha256=${signature}`,
    'Content-Type': 'application/json'
  },
  url: $env.JANAM_INGEST_URL || 'http://localhost:8000/api/ingest/n8n'
};
```

---

## Gmail (via Google Cloud Pub/Sub + n8n)

### Gmail Push Notifications Setup

Gmail doesn't support direct webhooks, but you can use **Google Cloud Pub/Sub**:

1. Enable Gmail API + Cloud Pub/Sub
2. Set up a Pub/Sub subscription that pushes to your n8n webhook
3. Configure Gmail watch on a specific label (e.g., "Janam Alerts")

### Pub/Sub Message Format

```json
{
  "message": {
    "data": "base64_encoded_pubsub_message",
    "attributes": {
      "emailAddress": "alerts@example.com"
    }
  }
}
```

The `data` field contains a base64-encoded Gmail message ID:
```
{
  "emailAddress": "alerts@example.com",
  "historyId": "123456"
}
```

### n8n Workflow: Gmail Normalizer

1. **n8n HTTP Trigger** receives Pub/Sub push
2. **Function Node** extracts email from Pub/Sub, calls Gmail API to fetch message
3. **Function Node** normalizes and signs for Janam

```javascript
// Function Node 1: Parse Pub/Sub, fetch from Gmail API
// Input: Pub/Sub message
// Output: Gmail message details

const input = $input.first().json;
const decodedData = Buffer.from(input.message.data, 'base64').toString('utf-8');
const pubsubMessage = JSON.parse(decodedData);

// Use Gmail API to fetch the message (requires a separate HTTP call)
// For simplicity, assume we have access to the email via credential store
return {
  emailAddress: input.message.attributes.emailAddress,
  historyId: pubsubMessage.historyId,
  // In real scenario, call Gmail API here to fetch actual message body
  messageId: pubsubMessage.historyId,
  subject: 'Alert Email',
  body: 'Message content from Gmail'
};

// Function Node 2: Normalize to Janam
// Input: Gmail message details
// Output: Janam payload + signature

const crypto = require('crypto');
const input = $input.first().json;

const janamPayload = {
  channel: 'gmail',
  platform: 'google-cloud-pub-sub',
  sender_id: input.emailAddress,
  message_text: `${input.subject}\n\n${input.body}`,
  external_event_id: input.messageId,
  timestamp_iso: new Date().toISOString(),
  media_type: 'text',
  anonymous_mode: true,  // Gmail reporters stay anonymous
  raw_payload: null
};

const secret = $env.JANAM_N8N_WEBHOOK_SECRET;
if (!secret) {
  throw new Error('Missing JANAM_N8N_WEBHOOK_SECRET in n8n environment');
}
const timestamp = Math.floor(Date.now() / 1000).toString();
const payloadString = JSON.stringify(janamPayload);
const message_to_sign = `${timestamp}.${payloadString}`;
const signature = crypto
  .createHmac('sha256', secret)
  .update(message_to_sign)
  .digest('hex');

return {
  payload: janamPayload,
  headers: {
    'X-Janam-Webhook-Timestamp': timestamp,
    'X-Janam-Webhook-Signature': `sha256=${signature}`,
    'Content-Type': 'application/json'
  },
  url: $env.JANAM_INGEST_URL || 'http://localhost:8000/api/ingest/n8n'
};
```

---

## Outlook (via Microsoft Graph Webhooks)

### Outlook Subscription Format

Microsoft Graph sends change notifications to your webhook URL (set in subscription):

```json
{
  "value": [{
    "subscriptionId": "sub_id_123",
    "changeType": "created",
    "resource": "me/mailFolders('Inbox')/messages/message_id_xyz",
    "resourceData": {
      "@odata.type": "#microsoft.graph.message",
      "@odata.id": "AAMkADU5Njc5M2Q1ZWU...",
      "id": "message_id_xyz",
      "from": {
        "emailAddress": {
          "address": "reporter@example.com",
          "name": "Anonymous Reporter"
        }
      },
      "subject": "Urgent: Conflict in residential area",
      "bodyPreview": "There is active armed conflict...",
      "receivedDateTime": "2026-04-07T10:15:00Z"
    }
  }]
}
```

### n8n Function Node: Outlook Normalizer

```javascript
// Input: $node["Webhook"].json (Microsoft Graph change notification)
// Output: Janam IngestEventRequest

const crypto = require('crypto');
const input = $input.first().json;

const notification = input.value?.[0];
if (!notification?.resourceData) {
  throw new Error('Invalid Outlook notification structure');
}

const message = notification.resourceData;
const janamPayload = {
  channel: 'outlook',
  platform: 'microsoft-graph-api',
  sender_id: message.from?.emailAddress?.address || 'unknown',
  message_text: `${message.subject || 'No subject'}\n\n${message.bodyPreview || ''}`,
  external_event_id: message.id,
  timestamp_iso: message.receivedDateTime || new Date().toISOString(),
  media_type: 'text',
  anonymous_mode: true,  // Outlook reporters stay anonymous
  raw_payload: null
};

// Generate signature
const secret = $env.JANAM_N8N_WEBHOOK_SECRET;
if (!secret) {
  throw new Error('Missing JANAM_N8N_WEBHOOK_SECRET in n8n environment');
}
const timestamp = Math.floor(Date.now() / 1000).toString();
const payloadString = JSON.stringify(janamPayload);
const message_to_sign = `${timestamp}.${payloadString}`;
const signature = crypto
  .createHmac('sha256', secret)
  .update(message_to_sign)
  .digest('hex');

return {
  payload: janamPayload,
  headers: {
    'X-Janam-Webhook-Timestamp': timestamp,
    'X-Janam-Webhook-Signature': `sha256=${signature}`,
    'Content-Type': 'application/json'
  },
  url: $env.JANAM_INGEST_URL || 'http://localhost:8000/api/ingest/n8n'
};
```

---

## IngestEventRequest Schema Reference

All normalized payloads must conform to this Janam schema:

```python
class IngestEventRequest(BaseModel):
    channel: str  # 'whatsapp', 'signal', 'facebook_messenger', 'gmail', 'outlook'
    platform: str  # 'meta-cloud-api', 'signal-cli', 'meta-messenger-api', etc.
    sender_id: str  # Phone, email, user ID (gets fingerprinted by default)
    message_text: str  # The report text
    external_event_id: str  # Unique ID from source platform
    timestamp_iso: str  # ISO 8601 timestamp
    media_type: Literal['text', 'audio', 'image', 'video']  # Always 'text' unless transcoded
    media_url: Optional[str] = None  # URL to audio/image/video if applicable
    latitude: Optional[float] = None  # Device GPS (optional)
    longitude: Optional[float] = None  # Device GPS (optional)
    anonymous_mode: bool = True  # Keep reporter identity pseudonymized
    raw_payload: Optional[dict] = None  # Original platform event (off by default)
```

---

## Error Handling in n8n

All Function nodes should include try/catch:

```javascript
try {
  // ... normalization logic ...
  return { payload, headers, url };
} catch (error) {
  return {
    error: true,
    message: error.message,
    input: $input.first().json
  };
}
```

Then use an **Error Handler** node in your n8n workflow:
- **On Success**: HTTP Request → POST to Janam
- **On Error**: Send alert to ops team or webhook

---

## Testing Locally

### Test WhatsApp Normalizer

```bash
curl -X POST http://localhost:3000/webhook/test \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messaging_product": "whatsapp",
          "metadata": {"phone_number_id": "999", "display_phone_number": "1234567890"},
          "messages": [{
            "from": "919876543210",
            "type": "text",
            "id": "msg_123",
            "text": {"body": "Armed attack with gunshots in downtown area"},
            "timestamp": "1234567890"
          }]
        }
      }]
    }]
  }'
```

### Test Janam /ingest/n8n Directly

```bash
# Generate signature
TIMESTAMP=$(date +%s)
PAYLOAD='{"channel":"test","platform":"manual","sender_id":"tester","message_text":"Test message","external_event_id":"test-123","timestamp_iso":"2026-04-07T10:00:00Z","media_type":"text","anonymous_mode":true}'
SIGNATURE=$(echo -n "${TIMESTAMP}.${PAYLOAD}" | openssl dgst -sha256 -hmac "your-secret" -hex | cut -d' ' -f2)

curl -X POST http://localhost:8000/api/ingest/n8n \
  -H "Content-Type: application/json" \
  -H "X-Janam-Webhook-Timestamp: ${TIMESTAMP}" \
  -H "X-Janam-Webhook-Signature: sha256=${SIGNATURE}" \
  -d "${PAYLOAD}"
```

### Starter Workflow Blueprint (Importable Layout)

Use this node order in n8n for any connector:

1. `Webhook` (or platform trigger node)
2. `Code: Normalize + Sign`
3. `HTTP Request: POST /api/ingest/n8n`

`Code: Normalize + Sign` can return this object shape for the next node:

```javascript
return {
  payload: janamPayload,
  headers: {
    'X-Janam-Webhook-Timestamp': timestamp,
    'X-Janam-Webhook-Signature': `sha256=${signature}`,
    'Content-Type': 'application/json'
  },
  url: $env.JANAM_INGEST_URL || 'http://localhost:8000/api/ingest/n8n'
};
```

Configure `HTTP Request` as:

- Method: `POST`
- URL: `{{ $json.url }}`
- Send Headers: `true`
- Header `X-Janam-Webhook-Timestamp`: `{{ $json.headers["X-Janam-Webhook-Timestamp"] }}`
- Header `X-Janam-Webhook-Signature`: `{{ $json.headers["X-Janam-Webhook-Signature"] }}`
- Header `Content-Type`: `application/json`
- Body Content Type: `RAW/JSON`
- Body: `{{ JSON.stringify($json.payload) }}`

---

## Checklist: Adding a New Connector

1. ✅ Choose platform (WhatsApp, Signal, Facebook, Gmail, Outlook, etc.)
2. ✅ Document webhook event format from platform
3. ✅ Create n8n Function node to normalize fields → IngestEventRequest
4. ✅ Generate HMAC-SHA256 signature with timestamp
5. ✅ POST to `/ingest/n8n` with signed headers
6. ✅ Set `anonymous_mode: true` for untrusted reporter sources
7. ✅ Add error handling (try/catch in Function node)
8. ✅ Test with real event from platform
9. ✅ Monitor alerts in Janam dashboard

---

## Environment Setup

Required in `.env` for n8n:

```bash
JANAM_N8N_WEBHOOK_SECRET=your-very-long-random-secret
JANAM_INGEST_URL=http://localhost:8000/api/ingest/n8n
# Or cloud: JANAM_INGEST_URL=https://janam.example.com/api/ingest/n8n
```

Required in n8n Function nodes:

```javascript
$env.JANAM_N8N_WEBHOOK_SECRET  // Set in n8n environment variables
$env.JANAM_INGEST_URL          // Set in n8n environment variables
```

---

## Next Steps

1. **Deploy n8n** (Docker container or cloud: n8n.cloud)
2. **Configure platform webhooks** to point to n8n (WhatsApp, Messenger, etc.)
3. **Copy a Function node template** above and customize for your platform
4. **Test with sample events** from each platform
5. **Monitor Janam alerts** as messages arrive
6. **(Optional) Enable opt-out anonymization** for trusted ops teams via trusted-partner API keys

Happy connector building! 
