# Authentication API

Amebo uses JWT-based authentication for API access. This guide covers authentication methods and security best practices.

## Overview

All API endpoints (except public health checks) require authentication using JWT tokens.

## Getting a Token

### Request Token

```bash
curl -X POST http://localhost/v1/tokens \
  -H "Content-Type: application/json" \
  -d '{
    "username": "administrator",
    "password": "N0.open.Sesame!"
  }'
```

### Response

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

## Using Tokens

### Authorization Header

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost/v1/applications
```

### Token Validation

Tokens are validated on each request:
- Signature verification
- Expiration check
- User permissions

## Token Management

### Token Expiration
- Default: 1 hour (3600 seconds)
- Configurable via `JWT_EXPIRATION`
- Refresh before expiration

### Token Refresh

```bash
curl -X POST http://localhost/v1/tokens/refresh \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Security Best Practices

### Secure Storage
- Store tokens securely
- Never log tokens
- Use HTTPS in production
- Implement token rotation

### Error Handling

```json
{
  "error": "Invalid token",
  "code": 401,
  "details": "Token has expired"
}
```

## Next Steps
- [Applications API](applications.md)
- [Events API](events.md)
- [API Overview](overview.md)
