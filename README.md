# Amebo

[![PyPI version](https://badge.fury.io/py/amebo.svg)](https://badge.fury.io/py/amebo)
[![Docker Pulls](https://img.shields.io/docker/pulls/rayattack/amebo)](https://hub.docker.com/r/rayattack/amebo)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen)](https://rayattack.github.io/amebo/)

**HTTP Event Notifications Server** - A lightweight, schema-driven event broadcasting system for microservices and distributed applications.

Amebo simplifies event-driven architecture by providing a centralized hub for publishing, validating, and distributing events across your applications with built-in schema registry and webhook delivery.

## ✨ Key Features

- **🚀 High Performance**: Sub-10ms response times with 1000+ events/second throughput
- **📋 Schema Registry**: Built-in JSON Schema validation for all events
- **🔄 Reliable Delivery**: Automatic retries with exponential backoff
- **🐳 Production Ready**: Docker support with clustering and monitoring
- **🛡️ Secure**: JWT authentication and webhook signature verification
- **📊 Observable**: Comprehensive metrics and health checks

## 🏗️ Core Concepts

Amebo has just **4 simple concepts** to master:

1. **Applications** - Services that publish and consume events
2. **Actions** - Event types with JSON Schema validation
3. **Events** - Actual occurrences of actions with payloads
4. **Subscriptions** - Webhook endpoints that receive events

## 🚀 Quick Start

### Docker (Recommended)

```bash
# Start Amebo with PostgreSQL
docker run -d \
  --name amebo \
  -p 3310:3310 \
  -e AMEBO_DSN="postgresql://user:pass@host:5432/amebo" \
  rayattack/amebo:latest
```

### Python Package

```bash
pip install amebo
amebo --workers 2 --address 0.0.0.0:3310
```

### Example Usage

```bash
# 1. Register an application
curl -X POST http://localhost:3310/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "application": "user-service",
    "address": "https://users.myapp.com",
    "secret": "your-secret-key"
  }'

# 2. Define an action with schema
curl -X POST http://localhost:3310/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "application": "user-service",
    "schemata": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "email": {"type": "string", "format": "email"}
      },
      "required": ["id", "email"]
    }
  }'

# 3. Publish an event
curl -X POST http://localhost:3310/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "action": "user.created",
    "payload": {
      "id": "user-123",
      "email": "john@example.com"
    }
  }'
```


## 📚 Documentation

**[📖 Complete Documentation](https://rayattack.github.io/amebo/)** - Comprehensive guides and API reference

### Quick Links

- **[🚀 Quick Start Guide](https://rayattack.github.io/amebo/getting-started/quick-start/)** - Get up and running in 5 minutes
- **[⚙️ Installation](https://rayattack.github.io/amebo/getting-started/installation/)** - Docker, Python, and production setup
- **[🏗️ Core Concepts](https://rayattack.github.io/amebo/user-guide/concepts/)** - Understanding Amebo's architecture
- **[🔌 API Reference](https://rayattack.github.io/amebo/api/overview/)** - Complete REST API documentation
- **[🐳 Production Deployment](https://rayattack.github.io/amebo/deployment/production/)** - Scaling and monitoring guides
- **[💡 Examples](https://rayattack.github.io/amebo/examples/basic-usage/)** - Real-world usage patterns

## 🏢 Use Cases

- **Microservices Communication** - Decouple services with event-driven architecture
- **Event Sourcing** - Build audit trails and event stores
- **Webhook Management** - Centralized webhook delivery with retries
- **Data Pipeline Triggers** - Trigger downstream processing on data changes
- **User Activity Tracking** - Track and react to user actions across services

## 🔧 Production Features

- **High Availability** - Multi-instance clustering with load balancing
- **Monitoring** - Prometheus metrics and health checks
- **Security** - JWT authentication and webhook signatures
- **Performance** - Connection pooling and batch processing
- **Reliability** - Automatic retries and dead letter queues


## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](https://rayattack.github.io/amebo/development/contributing/) for details.

- **[🐛 Report Issues](https://github.com/rayattack/amebo/issues)** - Bug reports and feature requests
- **[💬 Discussions](https://github.com/rayattack/amebo/discussions)** - Questions and community support
- **[🔧 Development](https://rayattack.github.io/amebo/development/architecture/)** - Architecture and development setup

## 📊 Performance

- **Response Time**: < 10ms (p95)
- **Throughput**: 1000+ events/second per instance
- **Availability**: 99.9% uptime with proper deployment
- **Scalability**: Horizontal scaling with load balancing

## 🛠️ Technology Stack

- **Runtime**: Python 3.8+ with FastAPI
- **Database**: PostgreSQL (production), SQLite (development)
- **Deployment**: Docker with clustering support
- **Monitoring**: Prometheus metrics and health checks

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🌍 Etymology

The word "amebo" is West African slang (Nigerian origin) for someone who never keeps what you tell them to themselves - a chronic gossip who spreads news everywhere. Perfect for an event broadcasting system! 😄

---

**[📖 Get Started with the Documentation](https://rayattack.github.io/amebo/)** | **[🐳 Docker Hub](https://hub.docker.com/r/rayattack/amebo)** | **[📦 PyPI](https://pypi.org/project/amebo/)**
