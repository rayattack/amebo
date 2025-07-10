# Testing Guide

Comprehensive testing strategies for Amebo development and deployment.

## Test Types

### Unit Tests
```bash
# Run unit tests
pytest tests/unit/

# With coverage
pytest --cov=amebo tests/unit/
```

### Integration Tests
```bash
# Run integration tests
pytest tests/integration/

# Test with real database
pytest tests/integration/ --db-url postgresql://test:test@localhost/test_amebo
```

### End-to-End Tests
```bash
# Run E2E tests
pytest tests/e2e/

# Test full cluster
docker-compose -f docker-compose.test.yml up -d
pytest tests/e2e/
```

## Writing Tests

### Example Unit Test
```python
def test_event_validation():
    schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    payload = {"id": "123"}

    result = validate_event_payload(payload, schema)
    assert result.is_valid
```

### Example Integration Test
```python
def test_event_publishing_flow():
    # Create application
    app = create_test_application()

    # Define action
    action = create_test_action(app.name)

    # Publish event
    event = publish_test_event(action.name, {"id": "123"})

    # Verify event was stored
    stored_event = get_event_by_id(event.id)
    assert stored_event.action == action.name
```

## Test Configuration

### Test Database
```python
# conftest.py
@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine
```

### Mock Services
```python
@pytest.fixture
def mock_webhook_server():
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, "http://test.example.com/webhook",
                json={"status": "ok"}, status=200)
        yield rsps
```

## Best Practices

1. **Test Isolation**: Each test should be independent
2. **Clear Naming**: Test names should describe what they test
3. **Arrange-Act-Assert**: Structure tests clearly
4. **Mock External Dependencies**: Use mocks for external services
5. **Test Edge Cases**: Include error conditions and edge cases

## Continuous Integration

Tests run automatically on:
- Pull requests
- Main branch commits
- Release tags

## Next Steps
- [Contributing Guide](contributing.md)
- [Architecture Overview](architecture.md)
