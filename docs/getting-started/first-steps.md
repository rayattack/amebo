# First Steps

Now that you have Amebo installed and configured, let's walk through creating your first complete event flow. This tutorial will guide you through the four core concepts with practical examples.

## Prerequisites

Before starting, ensure you have:

- ✅ Amebo running (see [Quick Start](quick-start.md))
- ✅ Access to the API (http://localhost:3310 or your configured URL)
- ✅ A tool for making HTTP requests (curl, Postman, or similar)

## Step 1: Register Your First Application

Applications are the foundation of Amebo. Let's register a user service:

```bash
curl -X POST http://localhost/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "application": "user-service",
    "address": "https://api.myapp.com",
    "secret": "user-service-webhook-secret-2024"
  }'
```

**Expected Response:**
```json
{
  "data": {
    "rowid": 1,
    "application": "user-service",
    "address": "https://api.myapp.com",
    "secret": "user-service-webhook-secret-2024",
    "timestamped": "2024-12-10T10:30:00Z"
  }
}
```

!!! tip "Application Naming"
    Use descriptive, kebab-case names like `user-service`, `payment-gateway`, or `notification-engine`.

## Step 2: Define Your First Action

Actions define the types of events your application can publish. Let's create a "user created" action:

```bash
curl -X POST http://localhost/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "description": "Unique user identifier"
        },
        "email": {
          "type": "string",
          "format": "email",
          "description": "User email address"
        },
        "name": {
          "type": "string",
          "minLength": 1,
          "description": "User full name"
        },
        "created_at": {
          "type": "string",
          "format": "date-time",
          "description": "When the user was created"
        },
        "source": {
          "type": "string",
          "enum": ["web", "mobile", "api"],
          "description": "Registration source"
        }
      },
      "required": ["id", "email", "name", "created_at"],
      "additionalProperties": false
    }
  }'
```

**Expected Response:**
```json
{
  "data": {
    "rowid": 1,
    "action": "user.created",
    "application": "user-service",
    "schemata": { ... },
    "timestamped": "2024-12-10T10:31:00Z"
  }
}
```

### Understanding the Schema

The JSON Schema defines:

- **Required fields**: `id`, `email`, `name`, `created_at`
- **Optional fields**: `source`
- **Validation rules**: Email format, minimum name length
- **Allowed values**: Source must be "web", "mobile", or "api"
- **No extra fields**: `additionalProperties: false`

## Step 3: Register a Consumer Application

Now let's register an application that will receive user creation events:

```bash
curl -X POST http://localhost/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "application": "email-service",
    "address": "https://email.myapp.com",
    "secret": "email-service-webhook-secret-2024"
  }'
```

## Step 4: Create a Subscription

Subscriptions tell Amebo where to send events. Let's subscribe the email service to user creation events:

```bash
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "email-service",
    "subscription": "welcome-email-sender",
    "action": "user.created",
    "handler": "https://email.myapp.com/webhooks/user-created",
    "max_retries": 3
  }'
```

**Expected Response:**
```json
{
  "data": {
    "rowid": 1,
    "application": "email-service",
    "subscription": "welcome-email-sender",
    "action": "user.created",
    "handler": "https://email.myapp.com/webhooks/user-created",
    "max_retries": 3,
    "timestamped": "2024-12-10T10:32:00Z"
  }
}
```

## Step 5: Publish Your First Event

Now for the exciting part - publishing an event! When a user registers in your application:

```bash
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "payload": {
      "id": "user-12345",
      "email": "alice@example.com",
      "name": "Alice Johnson",
      "created_at": "2024-12-10T10:33:00Z",
      "source": "web"
    }
  }'
```

**Expected Response:**
```json
{
  "data": {
    "rowid": 1,
    "action": "user.created",
    "payload": { ... },
    "timestamped": "2024-12-10T10:33:00Z"
  }
}
```

## What Happens Next?

After publishing the event, Amebo automatically:

1. **Validates** the payload against the schema
2. **Stores** the event in the database
3. **Finds** all subscriptions for `user.created`
4. **Delivers** webhooks to subscriber endpoints
5. **Retries** failed deliveries automatically

## Step 6: Verify Event Delivery

Let's check that everything worked:

=== "List Events"

    ```bash
    curl http://localhost/v1/events
    ```

    You should see your published event in the response.

=== "Check Delivery Status"

    ```bash
    curl http://localhost/v1/gists
    ```

    This shows the delivery status of events to subscribers.

=== "View Applications"

    ```bash
    curl http://localhost/v1/applications
    ```

    Verify both applications are registered.

=== "List Subscriptions"

    ```bash
    curl http://localhost/v1/subscriptions
    ```

    Confirm your subscription is active.

## Building a Complete Flow

Let's extend our example with a more realistic scenario:

### Register Additional Applications

```bash
# Analytics service
curl -X POST http://localhost/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "application": "analytics-service",
    "address": "https://analytics.myapp.com",
    "secret": "analytics-webhook-secret-2024"
  }'

# Notification service
curl -X POST http://localhost/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "application": "notification-service",
    "address": "https://notifications.myapp.com",
    "secret": "notification-webhook-secret-2024"
  }'
```

### Create Additional Actions

```bash
# User updated action
curl -X POST http://localhost/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.updated",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "changes": {
          "type": "object",
          "properties": {
            "email": {"type": "string", "format": "email"},
            "name": {"type": "string"}
          }
        },
        "updated_at": {"type": "string", "format": "date-time"},
        "updated_by": {"type": "string"}
      },
      "required": ["id", "changes", "updated_at"],
      "additionalProperties": false
    }
  }'

# User deleted action
curl -X POST http://localhost/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.deleted",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "deleted_at": {"type": "string", "format": "date-time"},
        "deleted_by": {"type": "string"},
        "reason": {"type": "string"}
      },
      "required": ["id", "deleted_at"],
      "additionalProperties": false
    }
  }'
```

### Set Up Multiple Subscriptions

```bash
# Analytics tracks all user events
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "analytics-service",
    "subscription": "user-analytics",
    "action": "user.created",
    "handler": "https://analytics.myapp.com/webhooks/user-events",
    "max_retries": 5
  }'

curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "analytics-service",
    "subscription": "user-analytics-updates",
    "action": "user.updated",
    "handler": "https://analytics.myapp.com/webhooks/user-events",
    "max_retries": 5
  }'

# Notifications for user deletions
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "notification-service",
    "subscription": "user-deletion-alerts",
    "action": "user.deleted",
    "handler": "https://notifications.myapp.com/webhooks/user-deleted",
    "max_retries": 3
  }'
```

### Test the Complete Flow

```bash
# Create a user
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "payload": {
      "id": "user-67890",
      "email": "bob@example.com",
      "name": "Bob Smith",
      "created_at": "2024-12-10T11:00:00Z",
      "source": "mobile"
    }
  }'

# Update the user
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.updated",
    "payload": {
      "id": "user-67890",
      "changes": {
        "email": "bob.smith@example.com"
      },
      "updated_at": "2024-12-10T11:30:00Z",
      "updated_by": "user-67890"
    }
  }'

# Delete the user
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.deleted",
    "payload": {
      "id": "user-67890",
      "deleted_at": "2024-12-10T12:00:00Z",
      "deleted_by": "admin",
      "reason": "User requested account deletion"
    }
  }'
```

## Common Patterns

### 1. Event Versioning

As your schemas evolve, version your actions:

```bash
curl -X POST http://localhost/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created.v2",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string", "format": "email"},
        "name": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "source": {"type": "string", "enum": ["web", "mobile", "api"]},
        "metadata": {
          "type": "object",
          "properties": {
            "ip_address": {"type": "string"},
            "user_agent": {"type": "string"}
          }
        }
      },
      "required": ["id", "email", "name", "created_at"],
      "additionalProperties": false
    }
  }'
```

### 2. Conditional Subscriptions

Use different handlers for different scenarios:

```bash
# High-priority user events
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "notification-service",
    "subscription": "vip-user-notifications",
    "action": "user.created",
    "handler": "https://notifications.myapp.com/webhooks/vip-users",
    "max_retries": 5
  }'
```

### 3. Error Handling

Monitor failed deliveries:

```bash
# Check delivery failures
curl "http://localhost/v1/gists?status=failed"

# Replay failed events
curl -X POST http://localhost/v1/regists/event-123
```

## Troubleshooting

### Schema Validation Errors

If event publishing fails with validation errors:

```json
{
  "error": "Schema validation failed",
  "details": {
    "field": "email",
    "message": "Invalid email format",
    "value": "not-an-email"
  }
}
```

**Solution**: Fix the payload to match the schema requirements.

### Webhook Delivery Failures

Check the gists endpoint for delivery status:

```bash
curl http://localhost/v1/gists
```

Common issues:
- **Endpoint not reachable**: Check network connectivity
- **Wrong HTTP status**: Ensure webhook returns 200-299
- **Timeout**: Increase webhook response time

### Application Not Found

```json
{
  "error": "Application not found",
  "details": {
    "application": "unknown-service"
  }
}
```

**Solution**: Register the application first.

## Next Steps

Congratulations! You've successfully:

- ✅ Registered applications
- ✅ Defined event schemas
- ✅ Created subscriptions
- ✅ Published events
- ✅ Verified delivery

Now you're ready to:

- **[Explore Core Concepts](../user-guide/concepts.md)** - Deep dive into Amebo's architecture
- **[Learn API Details](../api/overview.md)** - Master the complete API
- **[See Real Examples](../examples/basic-usage.md)** - Practical implementation patterns
- **[Deploy to Production](../deployment/production.md)** - Production deployment guide
