# Subscriptions API

The Subscriptions API manages event subscriptions and webhook delivery configuration.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/subscriptions` | List subscriptions |
| `POST` | `/v1/subscriptions` | Create subscription |
| `PUT` | `/v1/subscriptions/:id` | Update subscription |
| `DELETE` | `/v1/subscriptions/:id` | Delete subscription |

## Create Subscription

Subscribe to receive events via webhook.

### Request

```bash
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "application": "email-service",
    "subscription": "welcome-emails",
    "action": "user.created",
    "handler": "https://email.myapp.com/webhooks/user-created",
    "max_retries": 3
  }'
```

### Response

```json
{
  "data": {
    "rowid": 1,
    "application": "email-service",
    "subscription": "welcome-emails",
    "action": "user.created",
    "handler": "https://email.myapp.com/webhooks/user-created",
    "max_retries": 3,
    "timestamped": "2024-12-10T10:30:00Z"
  }
}
```

## List Subscriptions

Retrieve all subscriptions.

### Request

```bash
curl http://localhost/v1/subscriptions \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `application` | string | Filter by application |
| `action` | string | Filter by action |
| `active` | boolean | Filter by active status |

## Webhook Delivery

When events are published, Amebo delivers them to subscribed endpoints:

### Webhook Format

```json
{
  "event_id": "evt_123",
  "action": "user.created",
  "payload": {
    "id": "user-123",
    "email": "john@example.com",
    "name": "John Doe"
  },
  "timestamp": "2024-12-10T10:30:00Z",
  "delivery_attempt": 1
}
```

### Headers

```http
Content-Type: application/json
Authorization: Bearer webhook-secret
X-Amebo-Event: user.created
X-Amebo-Delivery: evt_123_1
X-Amebo-Signature: sha256=...
```

## Retry Policy

Failed deliveries are automatically retried:

1. Immediate retry
2. 2 seconds delay
3. 4 seconds delay
4. 8 seconds delay
5. 16 seconds delay

## Best Practices

1. **Return 200-299** for successful processing
2. **Verify signatures** for security
3. **Implement idempotency** for duplicate handling
4. **Process quickly** to avoid timeouts
5. **Monitor delivery** status

## Next Steps
- [Webhook Implementation](../user-guide/subscriptions.md)
- [Events API](events.md)
- [API Overview](overview.md)
