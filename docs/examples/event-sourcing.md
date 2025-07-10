# Event Sourcing with Amebo

Implement event sourcing patterns using Amebo as your event store and notification system.

## Overview

Event sourcing stores all changes as a sequence of events, making Amebo perfect for this pattern.

## Basic Event Sourcing

### User Aggregate Example

```python
class UserAggregate:
    def __init__(self, user_id):
        self.user_id = user_id
        self.version = 0
        self.email = None
        self.name = None
        self.status = 'pending'
        
    def create(self, email, name):
        event = {
            'action': 'user.created',
            'payload': {
                'user_id': self.user_id,
                'email': email,
                'name': name,
                'version': self.version + 1
            }
        }
        self.apply_event(event)
        return event
        
    def verify_email(self):
        if self.status != 'pending':
            raise ValueError("User already verified")
            
        event = {
            'action': 'user.email_verified',
            'payload': {
                'user_id': self.user_id,
                'verified_at': datetime.utcnow().isoformat(),
                'version': self.version + 1
            }
        }
        self.apply_event(event)
        return event
        
    def apply_event(self, event):
        action = event['action']
        payload = event['payload']
        
        if action == 'user.created':
            self.email = payload['email']
            self.name = payload['name']
            self.status = 'pending'
        elif action == 'user.email_verified':
            self.status = 'active'
            
        self.version = payload['version']
```

### Event Store Implementation

```python
class AmeboEventStore:
    def __init__(self, amebo_client):
        self.amebo = amebo_client
        
    def save_events(self, aggregate_id, events, expected_version):
        # Optimistic concurrency control
        current_version = self.get_current_version(aggregate_id)
        if current_version != expected_version:
            raise ConcurrencyError("Version mismatch")
            
        # Save events to Amebo
        for event in events:
            event['payload']['aggregate_id'] = aggregate_id
            self.amebo.publish_event(event['action'], event['payload'])
            
    def get_events(self, aggregate_id, from_version=0):
        # Query events from Amebo
        events = self.amebo.get_events(
            filter={'aggregate_id': aggregate_id},
            from_version=from_version
        )
        return events
        
    def load_aggregate(self, aggregate_class, aggregate_id):
        events = self.get_events(aggregate_id)
        aggregate = aggregate_class(aggregate_id)
        
        for event in events:
            aggregate.apply_event(event)
            
        return aggregate
```

## Command Handlers

```python
class UserCommandHandler:
    def __init__(self, event_store):
        self.event_store = event_store
        
    def handle_create_user(self, command):
        user_id = command['user_id']
        
        # Check if user already exists
        try:
            existing_user = self.event_store.load_aggregate(UserAggregate, user_id)
            if existing_user.version > 0:
                raise ValueError("User already exists")
        except AggregateNotFound:
            pass  # User doesn't exist, continue
            
        # Create new user
        user = UserAggregate(user_id)
        event = user.create(command['email'], command['name'])
        
        # Save event
        self.event_store.save_events(user_id, [event], 0)
        
        return user
        
    def handle_verify_email(self, command):
        user_id = command['user_id']
        
        # Load current state
        user = self.event_store.load_aggregate(UserAggregate, user_id)
        expected_version = user.version
        
        # Execute command
        event = user.verify_email()
        
        # Save event
        self.event_store.save_events(user_id, [event], expected_version)
        
        return user
```

## Projections

### Read Model Projections

```python
class UserProjection:
    def __init__(self, database):
        self.db = database
        
    def handle_user_created(self, event):
        payload = event['payload']
        
        self.db.users.insert({
            'user_id': payload['user_id'],
            'email': payload['email'],
            'name': payload['name'],
            'status': 'pending',
            'created_at': event['timestamp'],
            'version': payload['version']
        })
        
    def handle_user_email_verified(self, event):
        payload = event['payload']
        
        self.db.users.update(
            {'user_id': payload['user_id']},
            {
                '$set': {
                    'status': 'active',
                    'verified_at': payload['verified_at'],
                    'version': payload['version']
                }
            }
        )

# Subscribe to events for projection updates
curl -X POST http://localhost/v1/subscriptions \
  -d '{
    "application": "user-projection",
    "subscription": "user-read-model",
    "action": "user.created",
    "handler": "https://projections.myapp.com/webhooks/user-events"
  }'
```

## Snapshots

```python
class SnapshotStore:
    def __init__(self, database):
        self.db = database
        
    def save_snapshot(self, aggregate_id, aggregate, version):
        snapshot = {
            'aggregate_id': aggregate_id,
            'version': version,
            'data': aggregate.to_dict(),
            'created_at': datetime.utcnow()
        }
        
        self.db.snapshots.replace_one(
            {'aggregate_id': aggregate_id},
            snapshot,
            upsert=True
        )
        
    def load_snapshot(self, aggregate_id):
        snapshot = self.db.snapshots.find_one({'aggregate_id': aggregate_id})
        return snapshot
        
class OptimizedEventStore(AmeboEventStore):
    def __init__(self, amebo_client, snapshot_store):
        super().__init__(amebo_client)
        self.snapshots = snapshot_store
        
    def load_aggregate(self, aggregate_class, aggregate_id):
        # Try to load from snapshot first
        snapshot = self.snapshots.load_snapshot(aggregate_id)
        
        if snapshot:
            aggregate = aggregate_class.from_dict(
                aggregate_id, 
                snapshot['data']
            )
            from_version = snapshot['version']
        else:
            aggregate = aggregate_class(aggregate_id)
            from_version = 0
            
        # Load events since snapshot
        events = self.get_events(aggregate_id, from_version)
        
        for event in events:
            aggregate.apply_event(event)
            
        # Save new snapshot if many events processed
        if len(events) > 10:
            self.snapshots.save_snapshot(
                aggregate_id, 
                aggregate, 
                aggregate.version
            )
            
        return aggregate
```

## CQRS Integration

```python
# Command side
@app.route('/users', methods=['POST'])
def create_user():
    command = {
        'user_id': str(uuid.uuid4()),
        'email': request.json['email'],
        'name': request.json['name']
    }
    
    user = command_handler.handle_create_user(command)
    
    return jsonify({
        'user_id': user.user_id,
        'version': user.version
    }), 201

# Query side
@app.route('/users/<user_id>')
def get_user(user_id):
    # Read from projection/read model
    user = read_model.get_user(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    return jsonify(user)
```

## Event Replay

```python
def rebuild_projection(projection_name, from_date=None):
    """Rebuild a projection from events"""
    
    # Clear existing projection
    projection_db.clear(projection_name)
    
    # Get all relevant events
    events = amebo_client.get_events(
        actions=['user.created', 'user.email_verified', 'user.updated'],
        from_date=from_date
    )
    
    # Replay events
    projection = get_projection(projection_name)
    
    for event in events:
        projection.handle_event(event)
        
    print(f"Rebuilt {projection_name} with {len(events)} events")
```

## Testing Event Sourcing

```python
def test_user_creation_and_verification():
    # Given
    user_id = str(uuid.uuid4())
    event_store = InMemoryEventStore()
    command_handler = UserCommandHandler(event_store)
    
    # When - Create user
    create_command = {
        'user_id': user_id,
        'email': 'test@example.com',
        'name': 'Test User'
    }
    user = command_handler.handle_create_user(create_command)
    
    # Then
    assert user.email == 'test@example.com'
    assert user.status == 'pending'
    assert user.version == 1
    
    # When - Verify email
    verify_command = {'user_id': user_id}
    user = command_handler.handle_verify_email(verify_command)
    
    # Then
    assert user.status == 'active'
    assert user.version == 2
    
    # Verify events were stored
    events = event_store.get_events(user_id)
    assert len(events) == 2
    assert events[0]['action'] == 'user.created'
    assert events[1]['action'] == 'user.email_verified'
```

## Best Practices

1. **Immutable events**: Never modify published events
2. **Versioning**: Include version in events for concurrency control
3. **Idempotency**: Handle duplicate events gracefully
4. **Snapshots**: Use for performance with large event streams
5. **Projections**: Keep read models eventually consistent

## Next Steps
- [Integration Patterns](integration-patterns.md)
- [Microservices Example](microservices.md)
- [Schema Registry](../user-guide/schema-registry.md)
