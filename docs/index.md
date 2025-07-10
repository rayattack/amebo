# Amebo

<div align="center">
  <img src="assets/logo.png" alt="Amebo Logo" width="200"/>
  <h2>HTTP Event Notifications Server</h2>
  <p><strong>Asynchronous Communication Engine for Modern Applications</strong></p>
</div>

---

## What is Amebo?

Amebo is a **schema registry** and **event broadcast runtime** that enables you to disconnect your applications from traditional messaging systems like PubSub, RabbitMQ, Kafka, and SQS. It provides a simple HTTP API for registering event schemas, submitting message payloads, and broadcasting events to queues, pub/sub servers, or other web applications.

## Key Features

=== "🚀 High Performance"

    - **Sub-10ms latencies** at scale
    - **Battle-tested** with 100+ million requests
    - **Efficient batching** with configurable envelope sizes
    - **Connection pooling** for optimal database performance

=== "🔧 Simple Integration"

    - **HTTP-first** API design
    - **Schema validation** with JSON Schema
    - **Multiple backends** (PostgreSQL, SQLite, Redis)
    - **RESTful endpoints** for all operations

=== "🛡️ Enterprise Ready"

    - **High availability** with clustering support
    - **Authentication & authorization** built-in
    - **Monitoring & observability** ready
    - **Docker containerization** support

=== "🌐 Flexible Architecture"

    - **Microservices** communication
    - **Event sourcing** patterns
    - **Webhook delivery** with retries
    - **Multiple engine support** (PubSub, Kafka, RabbitMQ, SQS)

## Quick Start

Get Amebo running in under 5 minutes:

=== "Docker (Recommended)"

    ```bash
    # Clone the repository
    git clone https://github.com/rayattack/amebo.git
    cd amebo
    
    # Start the cluster
    ./start-cluster.sh
    
    # Test the API
    curl http://localhost/v1/applications
    ```

=== "Python Package"

    ```bash
    # Install Amebo
    pip install amebo
    
    # Create configuration
    echo '{
      "AMEBO_SECRET": "your-secret-key",
      "AMEBO_DSN": "postgresql://user:pass@localhost/db"
    }' > amebo.json
    
    # Start the server
    amebo
    ```

=== "From Source"

    ```bash
    # Clone and setup
    git clone https://github.com/rayattack/amebo.git
    cd amebo
    
    # Install dependencies
    pip install -r requirements.txt
    
    # Configure and run
    cp sample-amebo.json amebo.json
    python -m amebo.main
    ```

## Architecture Overview

```mermaid
graph TB
    A[Client Applications] --> B[Load Balancer]
    B --> C[Amebo Instance 1]
    B --> D[Amebo Instance 2]
    B --> E[Amebo Instance 3]
    
    C --> F[PostgreSQL Database]
    D --> F
    E --> F
    
    C --> G[Event Engines]
    D --> G
    E --> G
    
    G --> H[PubSub]
    G --> I[Kafka]
    G --> J[RabbitMQ]
    G --> K[Webhooks]
    
    style A fill:#e1f5fe
    style B fill:#f3e5f5
    style C fill:#e8f5e8
    style D fill:#e8f5e8
    style E fill:#e8f5e8
    style F fill:#fff3e0
    style G fill:#fce4ec
```

## Core Concepts

Amebo has only **4 core concepts** to master:

| Concept | Description | Example |
|---------|-------------|---------|
| **Applications** | Microservices or modules that create and receive events | `user-service`, `payment-service` |
| **Events** | Data payloads representing something that happened | `user-created`, `payment-processed` |
| **Actions** | Event types with associated JSON schemas | `user.created` with user schema |
| **Subscriptions** | HTTP endpoints that receive event notifications | `https://api.example.com/webhooks/user-created` |

## Use Cases

!!! example "Perfect for"

    - **Microservices communication**
    - **Event-driven architectures**
    - **Webhook delivery systems**
    - **Real-time notifications**
    - **Data pipeline orchestration**
    - **System integration**

## Why Choose Amebo?

=== "🎯 Simplicity"

    - **4 core concepts** only
    - **HTTP-first** design
    - **JSON Schema** validation
    - **RESTful** API

=== "⚡ Performance"

    - **Sub-10ms** response times
    - **Horizontal scaling** support
    - **Efficient batching**
    - **Connection pooling**

=== "🔒 Reliability"

    - **ACID transactions**
    - **Automatic retries**
    - **Dead letter queues**
    - **Health monitoring**

=== "🚀 Scalability"

    - **Multi-instance** clustering
    - **Load balancing** ready
    - **Database sharding** support
    - **Cloud native**

## Community & Support

- **📖 Documentation**: Comprehensive guides and API reference
- **🐛 Issues**: [GitHub Issues](https://github.com/rayattack/amebo/issues)
- **💬 Discussions**: [GitHub Discussions](https://github.com/rayattack/amebo/discussions)
- **📦 Package**: [PyPI Package](https://pypi.org/project/amebo/)

## License

Amebo is released under the [MIT License](https://github.com/rayattack/amebo/blob/main/LICENSE).

---

<div align="center">
  <p>Ready to get started? Check out our <a href="getting-started/quick-start/">Quick Start Guide</a>!</p>
</div>
