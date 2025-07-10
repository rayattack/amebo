# Subscriptions Management

Master event consumption patterns and subscription management in Amebo for reliable event delivery.

## Overview

Subscriptions define how applications receive events. This guide covers advanced subscription patterns, delivery guarantees, and troubleshooting.

## Subscription Patterns

### Basic Subscription

Subscribe to a specific event type:

```bash
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "email-service",
    "subscription": "user-welcome-emails",
    "action": "user.created",
    "handler": "https://email.myapp.com/webhooks/user-created",
    "max_retries": 3
  }'
```

### Multiple Subscriptions

One application can have multiple subscriptions:

```bash
# Subscribe to user events
curl -X POST http://localhost/v1/subscriptions \
  -d '{
    "application": "analytics-service",
    "subscription": "user-analytics",
    "action": "user.created",
    "handler": "https://analytics.myapp.com/webhooks/user-events"
  }'

# Subscribe to order events
curl -X POST http://localhost/v1/subscriptions \
  -d '{
    "application": "analytics-service", 
    "subscription": "order-analytics",
    "action": "order.placed",
    "handler": "https://analytics.myapp.com/webhooks/order-events"
  }'
```

### Conditional Subscriptions

Use different handlers for different scenarios:

```bash
# High-priority notifications
curl -X POST http://localhost/v1/subscriptions \
  -d '{
    "application": "notification-service",
    "subscription": "urgent-alerts",
    "action": "system.error",
    "handler": "https://notifications.myapp.com/webhooks/urgent",
    "max_retries": 5
  }'

# Standard notifications  
curl -X POST http://localhost/v1/subscriptions \
  -d '{
    "application": "notification-service",
    "subscription": "standard-alerts", 
    "action": "user.login",
    "handler": "https://notifications.myapp.com/webhooks/standard",
    "max_retries": 2
  }'
```

## Webhook Implementation

### Basic Webhook Handler

```python
from flask import Flask, request, jsonify
import hmac
import hashlib

app = Flask(__name__)
WEBHOOK_SECRET = "your-webhook-secret"

@app.route('/webhooks/user-created', methods=['POST'])
def handle_user_created():
    # Verify signature
    signature = request.headers.get('X-Amebo-Signature')
    if not verify_signature(request.data, signature):
        return jsonify({'error': 'Invalid signature'}), 401
    
    # Parse event
    event = request.json
    action = event.get('action')
    payload = event.get('payload')
    
    # Process event
    if action == 'user.created':
        send_welcome_email(payload['email'], payload['name'])
    
    return jsonify({'status': 'processed'}), 200

def verify_signature(payload, signature):
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### Idempotent Processing

Handle duplicate deliveries:

```python
import redis

redis_client = redis.Redis()

@app.route('/webhooks/user-created', methods=['POST'])
def handle_user_created():
    event = request.json
    event_id = event.get('event_id')
    
    # Check if already processed
    if redis_client.exists(f"processed:{event_id}"):
        return jsonify({'status': 'already_processed'}), 200
    
    # Process event
    try:
        process_user_created(event['payload'])
        
        # Mark as processed (expire after 24 hours)
        redis_client.setex(f"processed:{event_id}", 86400, "1")
        
        return jsonify({'status': 'processed'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### Async Processing

Handle events asynchronously:

```python
from celery import Celery

celery_app = Celery('webhook_processor')

@app.route('/webhooks/user-created', methods=['POST'])
def handle_user_created():
    event = request.json
    
    # Queue for async processing
    process_user_event.delay(event)
    
    return jsonify({'status': 'queued'}), 200

@celery_app.task
def process_user_event(event):
    payload = event['payload']
    
    # Heavy processing here
    send_welcome_email(payload['email'], payload['name'])
    update_analytics(payload)
    sync_to_crm(payload)
```

## Delivery Guarantees

### Retry Behavior

Amebo automatically retries failed deliveries:

1. **Immediate retry** (0s delay)
2. **Exponential backoff**: 2s, 4s, 8s, 16s
3. **Max retries**: Configurable per subscription
4. **Dead letter queue**: After max retries exceeded

### Success Criteria

Webhooks are considered successful when:

- HTTP status code: 200-299
- Response received within timeout (30s default)
- No connection errors

### Failure Handling

```python
@app.route('/webhooks/user-created', methods=['POST'])
def handle_user_created():
    try:
        event = request.json
        process_event(event)
        return jsonify({'status': 'success'}), 200
    except ValidationError as e:
        # Don't retry validation errors
        return jsonify({'error': 'Invalid payload', 'details': str(e)}), 400
    except TemporaryError as e:
        # Retry temporary errors
        return jsonify({'error': 'Temporary failure', 'details': str(e)}), 500
    except PermanentError as e:
        # Don't retry permanent errors
        return jsonify({'error': 'Permanent failure', 'details': str(e)}), 422
```

## Advanced Patterns

### Fan-out Pattern

Multiple services process the same event:

```bash
# Email service
curl -X POST http://localhost/v1/subscriptions \
  -d '{"application": "email-service", "action": "user.created", "handler": "https://email.myapp.com/webhooks/user-created"}'

# Analytics service  
curl -X POST http://localhost/v1/subscriptions \
  -d '{"application": "analytics-service", "action": "user.created", "handler": "https://analytics.myapp.com/webhooks/user-created"}'

# CRM service
curl -X POST http://localhost/v1/subscriptions \
  -d '{"application": "crm-service", "action": "user.created", "handler": "https://crm.myapp.com/webhooks/user-created"}'
```

### Event Filtering

Filter events at the application level:

```python
@app.route('/webhooks/user-events', methods=['POST'])
def handle_user_events():
    event = request.json
    payload = event['payload']
    
    # Only process premium users
    if payload.get('plan') == 'premium':
        process_premium_user_event(payload)
    
    return jsonify({'status': 'processed'}), 200
```

### Event Transformation

Transform events for downstream systems:

```python
def transform_user_event(amebo_event):
    """Transform Amebo event to CRM format"""
    payload = amebo_event['payload']
    
    return {
        'customer_id': payload['id'],
        'email_address': payload['email'],
        'full_name': payload['name'],
        'registration_date': payload['created_at'],
        'source': 'web_app'
    }

@app.route('/webhooks/user-created', methods=['POST'])
def handle_user_created():
    amebo_event = request.json
    crm_event = transform_user_event(amebo_event)
    
    # Send to CRM
    crm_client.create_customer(crm_event)
    
    return jsonify({'status': 'processed'}), 200
```

## Monitoring & Debugging

### Delivery Status

Check delivery status:

```bash
# View delivery attempts
curl http://localhost/v1/gists

# Filter by subscription
curl "http://localhost/v1/gists?subscription=user-welcome-emails"

# Filter by status
curl "http://localhost/v1/gists?status=failed"
```

### Webhook Testing

Test webhook endpoints:

```bash
# Test with curl
curl -X POST https://your-app.com/webhooks/user-created \
  -H "Content-Type: application/json" \
  -H "X-Amebo-Signature: sha256=test" \
  -d '{
    "event_id": "test-123",
    "action": "user.created",
    "payload": {
      "id": "test-user",
      "email": "test@example.com",
      "name": "Test User"
    }
  }'
```

### Logging

Comprehensive webhook logging:

```python
import logging

logger = logging.getLogger(__name__)

@app.route('/webhooks/user-created', methods=['POST'])
def handle_user_created():
    event = request.json
    event_id = event.get('event_id')
    
    logger.info(f"Received event {event_id} for action {event.get('action')}")
    
    try:
        process_event(event)
        logger.info(f"Successfully processed event {event_id}")
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Failed to process event {event_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
```

## Troubleshooting

### Common Issues

1. **Webhook timeouts**
   - Optimize processing time
   - Use async processing
   - Return 200 quickly

2. **Signature verification failures**
   - Check secret configuration
   - Verify signature calculation
   - Handle encoding correctly

3. **Duplicate processing**
   - Implement idempotency
   - Use event IDs for deduplication
   - Handle retries gracefully

### Performance Optimization

```python
# Use connection pooling
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Batch processing
@app.route('/webhooks/batch', methods=['POST'])
def handle_batch():
    events = request.json.get('events', [])
    
    # Process in batches
    for batch in chunks(events, 10):
        process_batch(batch)
    
    return jsonify({'status': 'processed', 'count': len(events)}), 200
```

## Next Steps

- [Schema Registry](schema-registry.md) - Advanced schema management
- [API Reference](../api/subscriptions.md) - Complete Subscriptions API
- [Examples](../examples/basic-usage.md) - Real-world implementation examples
