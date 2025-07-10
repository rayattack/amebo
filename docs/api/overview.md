# API Reference Overview

Amebo provides a comprehensive RESTful HTTP API for managing applications, events, actions, and subscriptions. All endpoints return JSON responses and support standard HTTP methods.

## Base URL

```
http://localhost:3310  # Single instance
http://localhost       # Load balanced cluster
```

## Authentication

Amebo uses JWT-based authentication for API access:

=== "Get Token"

    ```bash
    curl -X POST http://localhost/v1/tokens \
      -H "Content-Type: application/json" \
      -d '{
        "username": "administrator",
        "password": "N0.open.Sesame!"
      }'
    ```

    Response:
    ```json
    {
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "expires_in": 3600
    }
    ```

=== "Use Token"

    ```bash
    curl -H "Authorization: Bearer YOUR_TOKEN" \
      http://localhost/v1/applications
    ```

## API Endpoints

### Core Resources

| Resource | Endpoint | Description |
|----------|----------|-------------|
| **Applications** | `/v1/applications` | Manage microservices and modules |
| **Actions** | `/v1/actions` | Define event types with schemas |
| **Events** | `/v1/events` | Publish and query events |
| **Subscriptions** | `/v1/subscriptions` | Manage event subscriptions |
| **Gists** | `/v1/gists` | View event delivery status |

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/tokens` | POST | Authenticate and get JWT token |
| `/v8/tokens` | POST | Alternative authentication endpoint |

### Web Interface

| Endpoint | Description |
|----------|-------------|
| `/` | Login page |
| `/p/:page` | Web interface pages |

## HTTP Methods

Amebo follows RESTful conventions:

- **GET** - Retrieve resources
- **POST** - Create new resources
- **PUT** - Update existing resources
- **DELETE** - Remove resources (limited endpoints)

## Response Format

All API responses follow a consistent format:

=== "Success Response"

    ```json
    {
      "data": [...],
      "meta": {
        "total": 100,
        "page": 1,
        "per_page": 20
      }
    }
    ```

=== "Error Response"

    ```json
    {
      "error": "Validation failed",
      "details": {
        "field": "email",
        "message": "Invalid email format"
      },
      "code": 400
    }
    ```

## Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| **200** | OK | Request successful |
| **201** | Created | Resource created successfully |
| **400** | Bad Request | Invalid request data |
| **401** | Unauthorized | Authentication required |
| **403** | Forbidden | Insufficient permissions |
| **404** | Not Found | Resource not found |
| **409** | Conflict | Resource already exists |
| **422** | Unprocessable Entity | Validation failed |
| **500** | Internal Server Error | Server error |

## Rate Limiting

Amebo implements rate limiting to prevent abuse:

- **Default**: 1000 requests per minute per IP
- **Authenticated**: 5000 requests per minute per token
- **Headers**: Rate limit info in response headers

```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1640995200
```

## Pagination

List endpoints support pagination:

=== "Request"

    ```bash
    curl "http://localhost/v1/events?page=2&per_page=50"
    ```

=== "Response"

    ```json
    {
      "data": [...],
      "meta": {
        "total": 1000,
        "page": 2,
        "per_page": 50,
        "total_pages": 20,
        "has_next": true,
        "has_prev": true
      }
    }
    ```

## Filtering & Sorting

Most list endpoints support filtering and sorting:

=== "Filtering"

    ```bash
    # Filter by application
    curl "http://localhost/v1/events?application=user-service"
    
    # Filter by date range
    curl "http://localhost/v1/events?from=2024-01-01&to=2024-12-31"
    
    # Filter by action
    curl "http://localhost/v1/events?action=user.created"
    ```

=== "Sorting"

    ```bash
    # Sort by timestamp (default: desc)
    curl "http://localhost/v1/events?sort=timestamped&order=asc"
    
    # Sort by multiple fields
    curl "http://localhost/v1/events?sort=action,timestamped&order=asc,desc"
    ```

## Content Types

Amebo supports multiple content types:

- **JSON** (default): `application/json`
- **Form Data**: `application/x-www-form-urlencoded`
- **Multipart**: `multipart/form-data`

## CORS Support

Cross-Origin Resource Sharing (CORS) is enabled by default:

```http
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

## Webhooks

Amebo delivers events via webhooks with the following features:

=== "Delivery Format"

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

=== "Headers"

    ```http
    Content-Type: application/json
    Authorization: Bearer webhook-secret
    X-Amebo-Event: user.created
    X-Amebo-Delivery: evt_123_1
    X-Amebo-Signature: sha256=...
    ```

=== "Retry Policy"

    - **Attempts**: Up to 5 retries
    - **Backoff**: Exponential (1s, 2s, 4s, 8s, 16s)
    - **Timeout**: 30 seconds per attempt
    - **Success**: HTTP 200-299 response

## Schema Validation

All event payloads are validated against JSON Schema:

=== "Schema Definition"

    ```json
    {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string", "format": "email"},
        "name": {"type": "string", "minLength": 1}
      },
      "required": ["id", "email", "name"],
      "additionalProperties": false
    }
    ```

=== "Validation Error"

    ```json
    {
      "error": "Schema validation failed",
      "details": {
        "field": "email",
        "message": "Invalid email format",
        "value": "invalid-email"
      }
    }
    ```

## SDK & Libraries

Official SDKs and community libraries:

=== "Python"

    ```python
    from amebo import AmeboClient
    
    client = AmeboClient(
        base_url="http://localhost:3310",
        token="your-jwt-token"
    )
    
    # Publish event
    client.events.create({
        "action": "user.created",
        "payload": {"id": "123", "email": "john@example.com"}
    })
    ```

=== "JavaScript"

    ```javascript
    import { AmeboClient } from '@amebo/client';
    
    const client = new AmeboClient({
      baseUrl: 'http://localhost:3310',
      token: 'your-jwt-token'
    });
    
    // Publish event
    await client.events.create({
      action: 'user.created',
      payload: { id: '123', email: 'john@example.com' }
    });
    ```

=== "cURL"

    ```bash
    # Set base URL and token
    export AMEBO_URL="http://localhost:3310"
    export AMEBO_TOKEN="your-jwt-token"
    
    # Publish event
    curl -X POST "$AMEBO_URL/v1/events" \
      -H "Authorization: Bearer $AMEBO_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "action": "user.created",
        "payload": {"id": "123", "email": "john@example.com"}
      }'
    ```

## OpenAPI Specification

Amebo provides an OpenAPI 3.0 specification:

- **Specification**: `/openapi.json`
- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`

## Testing

Use the built-in test endpoints for development:

```bash
# Health check
curl http://localhost/health

# API status
curl http://localhost/v1/status

# Database connectivity
curl http://localhost/v1/health/database
```

## Next Steps

Explore the detailed API documentation:

- **[Authentication](authentication.md)** - JWT tokens and security
- **[Applications API](applications.md)** - Manage applications
- **[Events API](events.md)** - Publish and query events
- **[Actions API](actions.md)** - Define event schemas
- **[Subscriptions API](subscriptions.md)** - Manage subscriptions
