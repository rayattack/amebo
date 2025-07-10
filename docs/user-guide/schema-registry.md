# Schema Registry

Advanced schema management and evolution strategies for robust event-driven systems.

## Overview

Amebo's built-in schema registry ensures data consistency and enables safe schema evolution across your event-driven architecture.

## Schema Design Principles

### 1. Be Explicit

Define clear, unambiguous schemas:

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique identifier for the user"
    },
    "email": {
      "type": "string", 
      "format": "email",
      "description": "User's email address"
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when user was created"
    }
  },
  "required": ["user_id", "email", "created_at"],
  "additionalProperties": false
}
```

### 2. Plan for Evolution

Design schemas that can evolve:

```json
{
  "type": "object",
  "properties": {
    "version": {
      "type": "string",
      "enum": ["1.0"],
      "description": "Schema version"
    },
    "user_id": {"type": "string"},
    "email": {"type": "string"},
    "metadata": {
      "type": "object",
      "description": "Extensible metadata object",
      "additionalProperties": true
    }
  },
  "required": ["version", "user_id", "email"]
}
```

### 3. Use Semantic Types

Leverage JSON Schema formats:

```json
{
  "properties": {
    "id": {"type": "string", "format": "uuid"},
    "email": {"type": "string", "format": "email"},
    "website": {"type": "string", "format": "uri"},
    "created_at": {"type": "string", "format": "date-time"},
    "age": {"type": "integer", "minimum": 0, "maximum": 150},
    "score": {"type": "number", "minimum": 0.0, "maximum": 1.0}
  }
}
```

## Schema Evolution Strategies

### Backward Compatible Changes

Safe changes that don't break existing consumers:

=== "Adding Optional Fields"

    ```json
    // Version 1
    {
      "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"}
      },
      "required": ["id", "name"]
    }
    
    // Version 2 - Add optional field
    {
      "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "phone": {"type": "string"}  // New optional field
      },
      "required": ["id", "name"]
    }
    ```

=== "Relaxing Constraints"

    ```json
    // Version 1 - Strict enum
    {
      "properties": {
        "status": {
          "type": "string",
          "enum": ["active", "inactive"]
        }
      }
    }
    
    // Version 2 - Add new enum value
    {
      "properties": {
        "status": {
          "type": "string", 
          "enum": ["active", "inactive", "pending"]
        }
      }
    }
    ```

### Breaking Changes

Changes that require new schema versions:

=== "Removing Fields"

    ```json
    // Create new action version
    {
      "action": "user.created.v2",
      "schemata": {
        "properties": {
          "id": {"type": "string"},
          // "legacy_field" removed
          "name": {"type": "string"}
        }
      }
    }
    ```

=== "Changing Field Types"

    ```json
    // Version 1
    {
      "properties": {
        "age": {"type": "string"}  // String age
      }
    }
    
    // Version 2 - Breaking change
    {
      "action": "user.created.v2", 
      "properties": {
        "age": {"type": "integer"}  // Integer age
      }
    }
    ```

## Versioning Strategies

### 1. Action-Level Versioning

Version the entire action:

```bash
# Version 1
curl -X POST http://localhost/v1/actions \
  -d '{
    "action": "user.created.v1",
    "schemata": {...}
  }'

# Version 2  
curl -X POST http://localhost/v1/actions \
  -d '{
    "action": "user.created.v2", 
    "schemata": {...}
  }'
```

### 2. Schema Versioning

Include version in schema:

```json
{
  "type": "object",
  "properties": {
    "schema_version": {
      "type": "string",
      "enum": ["2.0"]
    },
    "data": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string"}
      }
    }
  }
}
```

### 3. Namespace Versioning

Use namespaces for versions:

```bash
# Version 1
"action": "v1.user.created"

# Version 2
"action": "v2.user.created"
```

## Advanced Schema Features

### Conditional Schemas

Use `if/then/else` for conditional validation:

```json
{
  "type": "object",
  "properties": {
    "user_type": {"type": "string", "enum": ["individual", "business"]},
    "name": {"type": "string"},
    "company_name": {"type": "string"}
  },
  "if": {
    "properties": {"user_type": {"const": "business"}}
  },
  "then": {
    "required": ["name", "company_name"]
  },
  "else": {
    "required": ["name"]
  }
}
```

### Composition

Use `allOf`, `anyOf`, `oneOf`:

```json
{
  "allOf": [
    {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "type": {"type": "string"}
      }
    },
    {
      "oneOf": [
        {
          "properties": {
            "type": {"const": "user"},
            "email": {"type": "string", "format": "email"}
          },
          "required": ["email"]
        },
        {
          "properties": {
            "type": {"const": "system"},
            "service": {"type": "string"}
          },
          "required": ["service"]
        }
      ]
    }
  ]
}
```

### References

Reuse schema definitions:

```json
{
  "definitions": {
    "address": {
      "type": "object",
      "properties": {
        "street": {"type": "string"},
        "city": {"type": "string"},
        "country": {"type": "string"}
      }
    }
  },
  "type": "object",
  "properties": {
    "billing_address": {"$ref": "#/definitions/address"},
    "shipping_address": {"$ref": "#/definitions/address"}
  }
}
```

## Schema Validation

### Client-Side Validation

Validate before publishing:

```python
import jsonschema
import requests

def publish_event(action, payload):
    # Get schema from Amebo
    schema_response = requests.get(f'http://localhost/v1/actions/{action}')
    schema = schema_response.json()['data']['schemata']
    
    # Validate payload
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"Invalid payload: {e.message}")
    
    # Publish event
    return requests.post('http://localhost/v1/events', json={
        'action': action,
        'payload': payload
    })
```

### Schema Testing

Test your schemas:

```python
import pytest
import jsonschema

def test_user_created_schema():
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "email": {"type": "string", "format": "email"}
        },
        "required": ["id", "email"]
    }
    
    # Valid payload
    valid_payload = {"id": "123", "email": "test@example.com"}
    jsonschema.validate(valid_payload, schema)  # Should not raise
    
    # Invalid payload - missing required field
    invalid_payload = {"id": "123"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_payload, schema)
    
    # Invalid payload - wrong format
    invalid_payload = {"id": "123", "email": "not-an-email"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_payload, schema)
```

## Migration Strategies

### Dual Publishing

Publish to both old and new schemas during transition:

```python
def publish_user_created(user_data):
    # Publish to v1 (legacy)
    v1_payload = transform_to_v1(user_data)
    publish_event('user.created.v1', v1_payload)
    
    # Publish to v2 (new)
    v2_payload = transform_to_v2(user_data)
    publish_event('user.created.v2', v2_payload)
```

### Schema Translation

Translate between schema versions:

```python
def translate_v1_to_v2(v1_payload):
    """Translate v1 user.created to v2 format"""
    return {
        'user_id': v1_payload['id'],  # Renamed field
        'email_address': v1_payload['email'],  # Renamed field
        'full_name': v1_payload['name'],  # Renamed field
        'registration_timestamp': v1_payload['created_at'],  # Renamed field
        'schema_version': '2.0'  # Added version
    }
```

### Gradual Migration

Migrate consumers gradually:

1. **Phase 1**: Dual publishing (old + new)
2. **Phase 2**: Update consumers to new schema
3. **Phase 3**: Stop publishing old schema
4. **Phase 4**: Remove old action definition

## Best Practices

### Documentation

Document your schemas:

```json
{
  "title": "User Created Event",
  "description": "Fired when a new user account is created",
  "type": "object",
  "properties": {
    "user_id": {
      "type": "string",
      "format": "uuid", 
      "description": "Unique identifier for the user account",
      "example": "550e8400-e29b-41d4-a716-446655440000"
    }
  }
}
```

### Validation

- **Strict validation**: Use `additionalProperties: false`
- **Required fields**: Be explicit about required vs optional
- **Constraints**: Use appropriate min/max, patterns, formats

### Governance

- **Schema reviews**: Review schema changes like code
- **Breaking change approval**: Require approval for breaking changes
- **Deprecation policy**: Define timeline for removing old schemas

## Tools & Utilities

### Schema Generation

Generate schemas from examples:

```python
def generate_schema_from_example(example_payload):
    """Generate basic schema from example payload"""
    schema = {"type": "object", "properties": {}}
    
    for key, value in example_payload.items():
        if isinstance(value, str):
            schema["properties"][key] = {"type": "string"}
        elif isinstance(value, int):
            schema["properties"][key] = {"type": "integer"}
        elif isinstance(value, float):
            schema["properties"][key] = {"type": "number"}
        elif isinstance(value, bool):
            schema["properties"][key] = {"type": "boolean"}
    
    return schema
```

### Schema Diff

Compare schema versions:

```python
def compare_schemas(old_schema, new_schema):
    """Compare two schemas and identify changes"""
    changes = []
    
    old_props = old_schema.get('properties', {})
    new_props = new_schema.get('properties', {})
    
    # Added properties
    for prop in new_props:
        if prop not in old_props:
            changes.append(f"Added property: {prop}")
    
    # Removed properties  
    for prop in old_props:
        if prop not in new_props:
            changes.append(f"Removed property: {prop}")
    
    return changes
```

## Next Steps

- [API Reference](../api/actions.md) - Complete Actions API documentation
- [Examples](../examples/event-sourcing.md) - Event sourcing with schemas
- [Deployment](../deployment/production.md) - Production schema management
