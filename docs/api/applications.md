# Applications API

Applications represent microservices, modules, or any system component that creates or receives events in Amebo. Each application must be registered before it can publish events or receive notifications.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/applications` | List all applications |
| `POST` | `/v1/applications` | Register a new application |
| `PUT` | `/v1/applications/:id` | Update an application |

## Application Schema

```json
{
  "type": "object",
  "properties": {
    "application": {
      "type": "string",
      "description": "Unique application identifier",
      "pattern": "^[a-zA-Z0-9_-]+$",
      "minLength": 1,
      "maxLength": 100
    },
    "address": {
      "type": "string",
      "description": "Base URL or hostname for the application",
      "format": "uri"
    },
    "secret": {
      "type": "string",
      "description": "Secret key for webhook authentication",
      "minLength": 8,
      "maxLength": 255
    }
  },
  "required": ["application", "address", "secret"],
  "additionalProperties": false
}
```

## List Applications

Retrieve all registered applications.

=== "Request"

    ```bash
    curl -X GET http://localhost/v1/applications \
      -H "Authorization: Bearer YOUR_TOKEN"
    ```

=== "Response"

    ```json
    {
      "data": [
        {
          "rowid": 1,
          "application": "user-service",
          "address": "https://api.example.com",
          "secret": "webhook-secret-key",
          "timestamped": "2024-12-10T10:30:00Z"
        },
        {
          "rowid": 2,
          "application": "notification-service",
          "address": "https://notifications.example.com",
          "secret": "another-secret-key",
          "timestamped": "2024-12-10T11:15:00Z"
        }
      ],
      "meta": {
        "total": 2,
        "page": 1,
        "per_page": 20
      }
    }
    ```

### Query Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `page` | integer | Page number | 1 |
| `per_page` | integer | Items per page (max 100) | 20 |
| `search` | string | Search in application names | - |
| `sort` | string | Sort field (`application`, `timestamped`) | `timestamped` |
| `order` | string | Sort order (`asc`, `desc`) | `desc` |

=== "Filtered Request"

    ```bash
    curl "http://localhost/v1/applications?search=user&sort=application&order=asc"
    ```

## Register Application

Register a new application in Amebo.

=== "Request"

    ```bash
    curl -X POST http://localhost/v1/applications \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer YOUR_TOKEN" \
      -d '{
        "application": "user-service",
        "address": "https://api.example.com",
        "secret": "webhook-secret-key"
      }'
    ```

=== "Success Response"

    ```json
    {
      "data": {
        "rowid": 1,
        "application": "user-service",
        "address": "https://api.example.com",
        "secret": "webhook-secret-key",
        "timestamped": "2024-12-10T10:30:00Z"
      }
    }
    ```

=== "Error Response"

    ```json
    {
      "error": "Application already exists",
      "details": {
        "field": "application",
        "value": "user-service"
      },
      "code": 409
    }
    ```

### Validation Rules

- **application**: Must be unique, alphanumeric with hyphens/underscores
- **address**: Must be a valid URL (HTTP/HTTPS)
- **secret**: Minimum 8 characters, used for webhook authentication

## Update Application

Update an existing application's details.

=== "Request"

    ```bash
    curl -X PUT http://localhost/v1/applications/user-service \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer YOUR_TOKEN" \
      -d '{
        "address": "https://new-api.example.com",
        "secret": "new-webhook-secret"
      }'
    ```

=== "Response"

    ```json
    {
      "data": {
        "rowid": 1,
        "application": "user-service",
        "address": "https://new-api.example.com",
        "secret": "new-webhook-secret",
        "timestamped": "2024-12-10T10:30:00Z"
      }
    }
    ```

!!! note "Partial Updates"
    You can update individual fields. The `application` name cannot be changed.

## Examples

### Microservices Registration

=== "User Service"

    ```bash
    curl -X POST http://localhost/v1/applications \
      -H "Content-Type: application/json" \
      -d '{
        "application": "user-service",
        "address": "https://users.myapp.com",
        "secret": "user-webhook-secret-2024"
      }'
    ```

=== "Payment Service"

    ```bash
    curl -X POST http://localhost/v1/applications \
      -H "Content-Type: application/json" \
      -d '{
        "application": "payment-service",
        "address": "https://payments.myapp.com",
        "secret": "payment-webhook-secret-2024"
      }'
    ```

=== "Notification Service"

    ```bash
    curl -X POST http://localhost/v1/applications \
      -H "Content-Type: application/json" \
      -d '{
        "application": "notification-service",
        "address": "https://notifications.myapp.com",
        "secret": "notification-webhook-secret-2024"
      }'
    ```

### Bulk Registration

```bash
#!/bin/bash
# Register multiple applications

APPLICATIONS=(
  "user-service:https://users.myapp.com:user-secret"
  "order-service:https://orders.myapp.com:order-secret"
  "inventory-service:https://inventory.myapp.com:inventory-secret"
  "email-service:https://email.myapp.com:email-secret"
)

for app_data in "${APPLICATIONS[@]}"; do
  IFS=':' read -r app address secret <<< "$app_data"
  
  curl -X POST http://localhost/v1/applications \
    -H "Content-Type: application/json" \
    -d "{
      \"application\": \"$app\",
      \"address\": \"$address\",
      \"secret\": \"$secret\"
    }"
  
  echo "Registered: $app"
done
```

## Security Considerations

### Secret Management

- **Rotation**: Regularly rotate webhook secrets
- **Strength**: Use strong, unique secrets for each application
- **Storage**: Store secrets securely in your application

=== "Generate Strong Secret"

    ```bash
    # Generate a secure random secret
    openssl rand -hex 32
    
    # Or use uuidgen
    uuidgen | tr -d '-'
    ```

### Webhook Authentication

Applications should verify webhook authenticity:

=== "Python Example"

    ```python
    import hmac
    import hashlib
    
    def verify_webhook(payload, signature, secret):
        expected = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(f"sha256={expected}", signature)
    
    # In your webhook handler
    if verify_webhook(request.body, request.headers['X-Amebo-Signature'], webhook_secret):
        # Process webhook
        pass
    else:
        # Reject webhook
        return 401
    ```

=== "Node.js Example"

    ```javascript
    const crypto = require('crypto');
    
    function verifyWebhook(payload, signature, secret) {
      const expected = crypto
        .createHmac('sha256', secret)
        .update(payload)
        .digest('hex');
      
      return crypto.timingSafeEqual(
        Buffer.from(`sha256=${expected}`),
        Buffer.from(signature)
      );
    }
    ```

## Error Handling

Common error scenarios and responses:

=== "Duplicate Application"

    ```json
    {
      "error": "Application already exists",
      "details": {
        "field": "application",
        "value": "user-service"
      },
      "code": 409
    }
    ```

=== "Invalid URL"

    ```json
    {
      "error": "Validation failed",
      "details": {
        "field": "address",
        "message": "Invalid URL format"
      },
      "code": 400
    }
    ```

=== "Application Not Found"

    ```json
    {
      "error": "Application not found",
      "details": {
        "application": "nonexistent-service"
      },
      "code": 404
    }
    ```

## Best Practices

1. **Naming Convention**: Use kebab-case for application names
2. **URL Format**: Always use HTTPS in production
3. **Secret Rotation**: Implement regular secret rotation
4. **Monitoring**: Monitor application registration and updates
5. **Documentation**: Document all registered applications

## Related APIs

- **[Actions API](actions.md)** - Define event types for applications
- **[Events API](events.md)** - Publish events from applications
- **[Subscriptions API](subscriptions.md)** - Subscribe to events from other applications
