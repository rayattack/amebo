# Migration Guide

Guidelines for migrating to Amebo from other event systems and upgrading between Amebo versions.

## Migrating from Other Systems

### From Kafka

**Assessment**:
- Identify topics → map to Amebo actions
- Analyze message schemas → convert to JSON Schema
- Review consumer groups → map to subscriptions

**Migration Steps**:
```bash
# 1. Set up Amebo alongside Kafka
# 2. Create dual publishing
# 3. Migrate consumers gradually
# 4. Decommission Kafka
```

**Example Mapping**:
```python
# Kafka topic: user-events
# Amebo action: user.created, user.updated, user.deleted

# Kafka consumer group: email-service
# Amebo subscription: email-service subscribes to user.* actions
```

### From RabbitMQ

**Assessment**:
- Map exchanges/queues to actions
- Convert message formats
- Identify routing patterns

**Bridge Implementation**:
```python
class RabbitMQToAmeboBridge:
    def __init__(self, amebo_client):
        self.amebo = amebo_client

    def handle_rabbitmq_message(self, channel, method, properties, body):
        # Convert RabbitMQ message to Amebo event
        message = json.loads(body)

        action = f"{method.exchange}.{method.routing_key}"
        payload = message

        # Publish to Amebo
        self.amebo.publish_event(action, payload)

        # Acknowledge RabbitMQ message
        channel.basic_ack(delivery_tag=method.delivery_tag)
```

### From AWS SQS/SNS

**Migration Strategy**:
```python
# SNS Topic → Amebo Action
# SQS Queue → Amebo Subscription

def migrate_sns_to_amebo():
    # 1. Create corresponding actions in Amebo
    # 2. Set up dual publishing (SNS + Amebo)
    # 3. Migrate subscribers to Amebo webhooks
    # 4. Remove SNS publishing
```

## Amebo Version Upgrades

### Pre-Upgrade Checklist
- [ ] Backup database
- [ ] Review changelog
- [ ] Test in staging environment
- [ ] Plan rollback strategy
- [ ] Schedule maintenance window

### Upgrade Process

#### Minor Version Upgrades (e.g., 1.1.0 → 1.2.0)
```bash
# 1. Stop Amebo instances
docker-compose stop amebo

# 2. Update image version
# Edit docker-compose.yml: image: rayattack/amebo:1.2.0

# 3. Start services
docker-compose up -d

# 4. Verify health
curl http://localhost/health
```

#### Major Version Upgrades (e.g., 1.x → 2.0)
```bash
# 1. Review breaking changes
# 2. Update configuration if needed
# 3. Run database migrations
# 4. Update client applications
# 5. Deploy new version
```

### Database Migrations

**Automatic Migrations**:
```bash
# Amebo handles schema migrations automatically
# on startup for minor versions
```

**Manual Migrations** (for major versions):
```sql
-- Example migration script
-- v1_to_v2_migration.sql

-- Add new columns
ALTER TABLE events ADD COLUMN event_version INTEGER DEFAULT 1;

-- Update existing data
UPDATE events SET event_version = 1 WHERE event_version IS NULL;

-- Create new indexes
CREATE INDEX idx_events_version ON events(event_version);
```

## Schema Evolution

### Backward Compatible Changes
```json
// Adding optional fields (safe)
{
  "type": "object",
  "properties": {
    "id": {"type": "string"},
    "email": {"type": "string"},
    "phone": {"type": "string"}  // New optional field
  },
  "required": ["id", "email"]
}
```

### Breaking Changes
```bash
# Create new action version
curl -X POST http://localhost/v1/actions \
  -d '{
    "action": "user.created.v2",
    "application": "user-service",
    "schemata": {
      // New schema with breaking changes
    }
  }'

# Dual publishing during transition
publish_event("user.created", payload)     // Old version
publish_event("user.created.v2", payload)  // New version
```

## Data Migration

### Event History Migration
```python
def migrate_event_history(source_system, target_amebo):
    """Migrate historical events to Amebo"""

    # Get events from source system
    events = source_system.get_all_events()

    for event in events:
        # Transform event format
        amebo_event = transform_event(event)

        # Publish to Amebo
        target_amebo.publish_event(
            amebo_event['action'],
            amebo_event['payload']
        )
```

### Subscription Migration
```python
def migrate_subscriptions():
    """Migrate existing subscriptions"""

    # Map old consumers to new subscriptions
    subscription_mapping = {
        'kafka_consumer_group_1': {
            'application': 'email-service',
            'actions': ['user.created', 'user.updated']
        },
        'rabbitmq_queue_1': {
            'application': 'analytics-service',
            'actions': ['order.placed', 'order.completed']
        }
    }

    for old_consumer, config in subscription_mapping.items():
        for action in config['actions']:
            create_amebo_subscription(
                application=config['application'],
                action=action,
                handler=f"https://{config['application']}/webhooks/{action}"
            )
```

## Testing Migration

### Migration Testing Strategy
```python
def test_migration():
    # 1. Set up test environment
    # 2. Migrate test data
    # 3. Verify data integrity
    # 4. Test application functionality
    # 5. Performance testing

    # Example verification
    original_events = get_original_events()
    migrated_events = get_migrated_events()

    assert len(original_events) == len(migrated_events)

    for orig, migr in zip(original_events, migrated_events):
        assert orig['payload'] == migr['payload']
```

### Rollback Procedures
```bash
# Database rollback
pg_restore --clean --if-exists -d amebo backup_before_migration.sql

# Application rollback
docker-compose down
# Edit docker-compose.yml to previous version
docker-compose up -d
```

## Best Practices

1. **Plan thoroughly**: Understand current system before migrating
2. **Test extensively**: Test migration in staging environment
3. **Migrate gradually**: Phase migration to reduce risk
4. **Monitor closely**: Watch for issues during migration
5. **Have rollback plan**: Always have a way to rollback

## Common Migration Issues

### Data Loss Prevention
- Always backup before migration
- Verify data integrity after migration
- Test rollback procedures

### Performance Impact
- Monitor system performance during migration
- Consider migration during low-traffic periods
- Scale resources if needed

### Application Compatibility
- Update client applications for new schemas
- Handle both old and new event formats during transition
- Coordinate with application teams

## Next Steps
- [Performance Guide](performance.md)
- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
