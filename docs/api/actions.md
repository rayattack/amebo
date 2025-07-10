# Actions API

The Actions API manages event type definitions and their JSON schemas in Amebo.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/actions` | List all actions |
| `POST` | `/v1/actions` | Create new action |
| `GET` | `/v1/actions/:name` | Get specific action |
| `PUT` | `/v1/actions/:name` | Update action schema |

## Create Action

Define a new event type with its schema.

### Request

```bash
curl -X POST http://localhost/v1/actions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "action": "user.created",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string", "format": "email"},
        "name": {"type": "string"}
      },
      "required": ["id", "email", "name"]
    }
  }'
```

### Response

```json
{
  "data": {
    "rowid": 1,
    "action": "user.created",
    "application": "user-service",
    "schemata": {...},
    "timestamped": "2024-12-10T10:30:00Z"
  }
}
```

## List Actions

Retrieve all defined actions.

### Request

```bash
curl http://localhost/v1/actions \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Response

```json
{
  "data": [
    {
      "rowid": 1,
      "action": "user.created",
      "application": "user-service",
      "schemata": {...},
      "timestamped": "2024-12-10T10:30:00Z"
    }
  ]
}
```

## Schema Validation

Actions use JSON Schema Draft 7 for validation:

```json
{
  "type": "object",
  "properties": {
    "id": {"type": "string", "format": "uuid"},
    "email": {"type": "string", "format": "email"},
    "created_at": {"type": "string", "format": "date-time"}
  },
  "required": ["id", "email"],
  "additionalProperties": false
}
```

## Best Practices

1. **Plan schemas** carefully
2. **Version breaking changes**
3. **Use descriptive names**
4. **Document schemas** thoroughly
5. **Test validation** before deployment

## Next Steps
- [Events API](events.md)
- [Schema Registry](../user-guide/schema-registry.md)
- [API Overview](overview.md)
