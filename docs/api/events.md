# Events API

The Events API allows you to publish events and query event history in Amebo.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/events` | List events |
| `POST` | `/v1/events` | Publish an event |
| `GET` | `/v1/events/:id` | Get specific event |

## Publish Event

Create a new event in Amebo.

### Request

```bash
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "action": "user.created",
    "payload": {
      "id": "user-123",
      "email": "john@example.com",
      "name": "John Doe",
      "created_at": "2024-12-10T10:30:00Z"
    }
  }'
```

### Response

```json
{
  "data": {
    "rowid": 1,
    "action": "user.created",
    "payload": {
      "id": "user-123",
      "email": "john@example.com",
      "name": "John Doe",
      "created_at": "2024-12-10T10:30:00Z"
    },
    "timestamped": "2024-12-10T10:30:00Z"
  }
}
```

## List Events

Retrieve events with filtering and pagination.

### Request

```bash
curl "http://localhost/v1/events?action=user.created&limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string | Filter by action type |
| `from` | string | Start date (ISO 8601) |
| `to` | string | End date (ISO 8601) |
| `page` | integer | Page number |
| `limit` | integer | Items per page |

### Response

```json
{
  "data": [
    {
      "rowid": 1,
      "action": "user.created",
      "payload": {...},
      "timestamped": "2024-12-10T10:30:00Z"
    }
  ],
  "meta": {
    "total": 100,
    "page": 1,
    "per_page": 10
  }
}
```

## Event Schema

Events must conform to their action's schema:

```json
{
  "action": "string (required)",
  "payload": "object (required, validated against action schema)"
}
```

## Error Handling

### Schema Validation Error

```json
{
  "error": "Schema validation failed",
  "details": {
    "field": "email",
    "message": "Invalid email format",
    "value": "not-an-email"
  },
  "code": 422
}
```

### Action Not Found

```json
{
  "error": "Action not found",
  "details": {
    "action": "unknown.action"
  },
  "code": 404
}
```

## Best Practices

1. **Validate locally** before publishing
2. **Handle errors** gracefully
3. **Use batch publishing** for high volume
4. **Monitor delivery** status
5. **Implement idempotency** in consumers

## Next Steps
- [Actions API](actions.md)
- [Subscriptions API](subscriptions.md)
- [Event Examples](../examples/basic-usage.md)
