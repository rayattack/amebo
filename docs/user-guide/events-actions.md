# Events & Actions

Master the creation and management of events and actions in Amebo for robust event-driven architectures.

## Understanding Actions vs Events

| Concept | Description | Example |
|---------|-------------|---------|
| **Action** | Event type definition with schema | `user.created` |
| **Event** | Actual occurrence with data | User "john@example.com" was created |

## Action Design

### Schema Best Practices

Create robust, evolvable schemas:

```json
{
  "action": "user.created",
  "application": "user-service",
  "schemata": {
    "type": "object",
    "properties": {
      "id": {"type": "string", "format": "uuid"},
      "email": {"type": "string", "format": "email"},
      "name": {"type": "string", "minLength": 1},
      "created_at": {"type": "string", "format": "date-time"},
      "metadata": {
        "type": "object",
        "properties": {
          "source": {"type": "string", "enum": ["web", "mobile", "api"]},
          "ip_address": {"type": "string", "format": "ipv4"},
          "user_agent": {"type": "string"}
        }
      }
    },
    "required": ["id", "email", "name", "created_at"],
    "additionalProperties": false
  }
}
```

### Schema Evolution

Handle schema changes gracefully:

=== "Additive Changes (Safe)"

    ```json
    // Version 1
    {
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string"}
      }
    }
    
    // Version 2 - Add optional field
    {
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"}  // New optional field
      }
    }
    ```

=== "Breaking Changes"

    ```json
    // Create new action version
    {
      "action": "user.created.v2",
      "schemata": {
        // New schema with breaking changes
      }
    }
    ```

## Event Publishing

### Basic Publishing

```bash
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "payload": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "alice@example.com",
      "name": "Alice Johnson",
      "created_at": "2024-12-10T10:30:00Z",
      "metadata": {
        "source": "web",
        "ip_address": "192.168.1.100",
        "user_agent": "Mozilla/5.0..."
      }
    }
  }'
```

### Batch Publishing

For high-throughput scenarios:

```bash
curl -X POST http://localhost/v1/events/batch \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {
        "action": "user.created",
        "payload": {"id": "user-1", "email": "user1@example.com", "name": "User 1"}
      },
      {
        "action": "user.created", 
        "payload": {"id": "user-2", "email": "user2@example.com", "name": "User 2"}
      }
    ]
  }'
```

## Event Patterns

### Domain Events

Capture business-significant occurrences:

```json
{
  "action": "order.placed",
  "payload": {
    "order_id": "ord-123",
    "customer_id": "cust-456",
    "items": [...],
    "total_amount": 99.99,
    "currency": "USD"
  }
}
```

### State Change Events

Track entity lifecycle:

```json
{
  "action": "user.status_changed",
  "payload": {
    "user_id": "user-123",
    "old_status": "pending",
    "new_status": "active",
    "changed_by": "admin-456",
    "reason": "email_verified"
  }
}
```

### Integration Events

External system interactions:

```json
{
  "action": "payment.processed",
  "payload": {
    "payment_id": "pay-789",
    "order_id": "ord-123",
    "amount": 99.99,
    "currency": "USD",
    "provider": "stripe",
    "transaction_id": "txn_abc123"
  }
}
```

## Event Sourcing

Use events as the source of truth:

### Event Store Pattern

```json
// Events in sequence
[
  {"action": "user.created", "payload": {"id": "user-123", "email": "john@example.com"}},
  {"action": "user.email_verified", "payload": {"id": "user-123", "verified_at": "2024-12-10T11:00:00Z"}},
  {"action": "user.profile_updated", "payload": {"id": "user-123", "name": "John Doe"}}
]
```

### Projection Building

Reconstruct current state from events:

```python
def build_user_projection(user_id, events):
    user = {}
    
    for event in events:
        if event['action'] == 'user.created':
            user.update(event['payload'])
        elif event['action'] == 'user.email_verified':
            user['email_verified'] = True
        elif event['action'] == 'user.profile_updated':
            user.update(event['payload'])
    
    return user
```

## Validation & Testing

### Schema Validation

Test your schemas:

```python
import jsonschema

schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "email": {"type": "string", "format": "email"}
    },
    "required": ["id", "email"]
}

# Valid payload
payload = {"id": "123", "email": "test@example.com"}
jsonschema.validate(payload, schema)  # Passes

# Invalid payload
payload = {"id": "123", "email": "invalid-email"}
jsonschema.validate(payload, schema)  # Raises ValidationError
```

### Event Testing

Test event publishing:

```python
def test_user_created_event():
    response = requests.post('http://localhost/v1/events', json={
        'action': 'user.created',
        'payload': {
            'id': 'test-user',
            'email': 'test@example.com',
            'name': 'Test User',
            'created_at': '2024-12-10T10:30:00Z'
        }
    })
    
    assert response.status_code == 201
    assert 'rowid' in response.json()['data']
```

## Performance Considerations

### Payload Size

Keep payloads reasonable:

- **Recommended**: < 1MB per event
- **Maximum**: Configurable via `AMEBO_ENVELOPE`
- **Best practice**: Include references, not full objects

### Event Frequency

Monitor event rates:

- **Burst handling**: Amebo handles traffic spikes
- **Rate limiting**: Consider application-level limits
- **Batching**: Use batch endpoints for high volume

## Monitoring & Observability

### Key Metrics

Track these metrics:

- Event publishing rate
- Schema validation failures
- Event processing latency
- Storage growth

### Logging

Log important events:

```python
import logging

logger = logging.getLogger(__name__)

def publish_event(action, payload):
    try:
        response = amebo_client.publish_event(action, payload)
        logger.info(f"Published event {action} with ID {response['rowid']}")
        return response
    except ValidationError as e:
        logger.error(f"Schema validation failed for {action}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to publish event {action}: {e}")
        raise
```

## Next Steps

- [Subscriptions](subscriptions.md) - Set up event consumption
- [Schema Registry](schema-registry.md) - Advanced schema management
- [API Reference](../api/events.md) - Complete Events API documentation
