# Quick Start Guide

Get Amebo up and running in just a few minutes! This guide will walk you through the fastest way to start using Amebo for event-driven communication.

## Prerequisites

Before you begin, ensure you have:

- **Docker & Docker Compose** (recommended) OR
- **Python 3.8+** for local installation
- **PostgreSQL** (optional, SQLite works for development)

## Option 1: Docker Cluster (Recommended)

The fastest way to get a production-ready Amebo cluster running:

### Step 1: Clone and Start

```bash
# Clone the repository
git clone https://github.com/rayattack/amebo.git
cd amebo

# Start the cluster (3 instances + PostgreSQL + Load Balancer)
./start-cluster.sh
```

### Step 2: Verify Installation

```bash
# Check cluster health
./health-check.sh

# Test the API
curl http://localhost/v1/applications
```

!!! success "Cluster Ready!"
    Your Amebo cluster is now running with:
    
    - **Load Balancer**: http://localhost
    - **3 App Instances**: ports 3311, 3312, 3313
    - **PostgreSQL**: port 5432
    - **Health Monitoring**: Built-in

## Option 2: Single Instance (Development)

For development or testing with a single instance:

=== "Docker"

    ```bash
    # Create configuration
    cat > amebo.json << EOF
    {
      "AMEBO_SECRET": "dev-secret-key-change-in-production",
      "AMEBO_DSN": "sqlite:///amebo.db",
      "AMEBO_PORT": 3310
    }
    EOF
    
    # Run with Docker
    docker run -p 3310:3310 -v $(pwd)/amebo.json:/app/amebo.json amebo:latest
    ```

=== "Python Package"

    ```bash
    # Install Amebo
    pip install amebo
    
    # Create configuration
    cat > amebo.json << EOF
    {
      "AMEBO_SECRET": "dev-secret-key-change-in-production",
      "AMEBO_DSN": "sqlite:///amebo.db",
      "AMEBO_PORT": 3310
    }
    EOF
    
    # Start the server
    amebo
    ```

=== "From Source"

    ```bash
    # Clone repository
    git clone https://github.com/rayattack/amebo.git
    cd amebo
    
    # Install dependencies
    pip install -e .
    
    # Copy sample configuration
    cp sample-amebo.json amebo.json
    
    # Start the server
    python -m amebo.main
    ```

## Your First Event Flow

Let's create a complete event flow in 4 simple steps:

### Step 1: Register an Application

```bash
curl -X POST http://localhost/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "application": "user-service",
    "address": "https://api.example.com",
    "secret": "webhook-secret-key"
  }'
```

### Step 2: Define an Action (Event Type)

```bash
curl -X POST http://localhost/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string", "format": "email"},
        "name": {"type": "string"}
      },
      "required": ["id", "email", "name"]
    }
  }'
```

### Step 3: Create a Subscription

```bash
curl -X POST http://localhost/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "application": "notification-service",
    "subscription": "user-created-notifications",
    "action": "user.created",
    "handler": "https://notifications.example.com/webhooks/user-created",
    "max_retries": 3
  }'
```

### Step 4: Publish an Event

```bash
curl -X POST http://localhost/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "payload": {
      "id": "user-123",
      "email": "john@example.com",
      "name": "John Doe"
    }
  }'
```

!!! tip "What Happens Next?"
    Amebo will:
    
    1. **Validate** the payload against the schema
    2. **Store** the event in the database
    3. **Deliver** the event to all subscribers
    4. **Retry** failed deliveries automatically
    5. **Track** delivery status and metrics

## Verification

Check that everything is working:

=== "List Applications"

    ```bash
    curl http://localhost/v1/applications
    ```

=== "List Actions"

    ```bash
    curl http://localhost/v1/actions
    ```

=== "List Events"

    ```bash
    curl http://localhost/v1/events
    ```

=== "List Subscriptions"

    ```bash
    curl http://localhost/v1/subscriptions
    ```

## Web Interface

Amebo includes a built-in web interface for management:

1. **Open your browser** to http://localhost
2. **Login** with default credentials:
   - Username: `administrator`
   - Password: `N0.open.Sesame!`
3. **Explore** applications, events, and subscriptions

!!! warning "Security Note"
    Change the default credentials in production! Update the `AMEBO_USERNAME` and `AMEBO_PASSWORD` in your configuration.

## Next Steps

Now that you have Amebo running:

1. **[Learn Core Concepts](../user-guide/concepts.md)** - Understand applications, events, actions, and subscriptions
2. **[Explore the API](../api/overview.md)** - Detailed API documentation with examples
3. **[Deploy to Production](../deployment/production.md)** - Production deployment best practices
4. **[Set Up Monitoring](../deployment/monitoring.md)** - Monitor your Amebo cluster

## Common Issues

!!! question "Port Already in Use?"
    
    ```bash
    # Check what's using the port
    netstat -tulpn | grep :3310
    
    # Change the port in amebo.json
    "AMEBO_PORT": 3311
    ```

!!! question "Database Connection Failed?"
    
    For PostgreSQL issues:
    ```bash
    # Check PostgreSQL is running
    docker logs amebo-postgres
    
    # Test connection
    docker exec -it amebo-postgres psql -U amebo -d amebo
    ```

!!! question "Permission Denied?"
    
    ```bash
    # Make scripts executable
    chmod +x start-cluster.sh stop-cluster.sh health-check.sh
    ```

## Getting Help

- **📖 Documentation**: Browse the full documentation
- **🐛 Issues**: [Report bugs on GitHub](https://github.com/rayattack/amebo/issues)
- **💬 Discussions**: [Ask questions](https://github.com/rayattack/amebo/discussions)
- **📧 Support**: Check the [support section](../support/faq.md)

---

**Congratulations!** 🎉 You now have Amebo running and have created your first event flow. Ready to dive deeper? Check out the [User Guide](../user-guide/concepts.md) to learn more about Amebo's powerful features.
