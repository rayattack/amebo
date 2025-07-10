# Frequently Asked Questions

Common questions and answers about Amebo usage, deployment, and troubleshooting.

## General Questions

### What is Amebo?

Amebo is an HTTP Event Notifications Server that acts as a schema registry and event broadcast runtime. It enables applications to communicate through events without being tightly coupled to specific messaging systems like Kafka, RabbitMQ, or SQS.

### How is Amebo different from Kafka or RabbitMQ?

| Feature | Amebo | Kafka | RabbitMQ |
|---------|-------|-------|----------|
| **Protocol** | HTTP/REST | Binary/TCP | AMQP/Binary |
| **Schema Registry** | Built-in | Separate service | Plugin required |
| **Delivery** | HTTP webhooks | Pull-based | Push/Pull |
| **Setup Complexity** | Simple | Complex | Moderate |
| **Language Support** | Any HTTP client | Client libraries | Client libraries |

### When should I use Amebo?

Amebo is ideal for:

- **Microservices** that need loose coupling
- **Event-driven architectures** with HTTP-based services
- **Webhook delivery** systems
- **Schema validation** requirements
- **Simple deployment** needs
- **Multi-language** environments

### What are the performance characteristics?

- **Latency**: Sub-10ms response times
- **Throughput**: 1000+ events/second per instance
- **Scalability**: Horizontal scaling with load balancer
- **Reliability**: ACID transactions with automatic retries

## Installation & Setup

### What are the system requirements?

**Minimum:**
- 1 CPU core, 512MB RAM
- Python 3.8+ or Docker
- 1GB storage

**Recommended:**
- 2+ CPU cores, 2GB+ RAM
- PostgreSQL database
- 10GB+ SSD storage

### Can I use SQLite in production?

SQLite is suitable for:
- **Development** environments
- **Small deployments** (< 100 events/day)
- **Single instance** setups

For production, use PostgreSQL for:
- **High availability** clustering
- **Better performance** at scale
- **ACID compliance** across instances

### How do I migrate from SQLite to PostgreSQL?

```bash
# 1. Export data from SQLite
sqlite3 amebo.db .dump > amebo_backup.sql

# 2. Convert to PostgreSQL format
# (Manual conversion or use migration tools)

# 3. Import to PostgreSQL
psql -U amebo -d amebo -f amebo_backup_pg.sql

# 4. Update configuration
# Change AMEBO_DSN to PostgreSQL connection string
```

## Configuration

### How do I configure clustering?

Use the Docker cluster setup:

```bash
# Clone repository
git clone https://github.com/rayattack/amebo.git
cd amebo

# Start 3-instance cluster
./start-cluster.sh
```

Or manually configure multiple instances with shared database.

### What environment variables are available?

| Variable | Description | Default |
|----------|-------------|---------|
| `AMEBO_SECRET` | JWT signing secret | Required |
| `AMEBO_DSN` | Database connection string | Required |
| `AMEBO_PORT` | Server port | 3310 |
| `AMEBO_USERNAME` | Admin username | admin |
| `AMEBO_PASSWORD` | Admin password | Required |
| `AMEBO_ENVELOPE` | Batch size | 256 |
| `AMEBO_IDLES` | Idle sleep time (seconds) | 5 |
| `AMEBO_REST_WHEN` | Rest threshold | 0 |

### How do I secure Amebo in production?

1. **Change default credentials**
2. **Use strong secrets** (32+ characters)
3. **Enable HTTPS** with SSL certificates
4. **Configure firewall** rules
5. **Use environment variables** for secrets
6. **Enable authentication** for all endpoints
7. **Regular security updates**

## API Usage

### How do I authenticate API requests?

```bash
# 1. Get JWT token
curl -X POST http://localhost/v1/tokens \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'

# 2. Use token in requests
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost/v1/applications
```

### What's the difference between actions and events?

- **Actions** are event type definitions with schemas
- **Events** are actual instances of actions with data

Think of actions as "classes" and events as "instances" in programming terms.

### How do I handle webhook failures?

Amebo automatically retries failed webhooks with exponential backoff:

1. **Immediate retry**
2. **2 seconds delay**
3. **4 seconds delay**
4. **8 seconds delay**
5. **16 seconds delay**

After max retries, events go to dead letter queue.

### Can I replay events?

Yes, use the replay endpoint:

```bash
# Replay specific event
curl -X POST http://localhost/v1/regists/event-123

# Get events for manual replay
curl "http://localhost/v1/events?from=2024-12-01&action=user.created"
```

## Schema Management

### How do I version schemas?

Use semantic versioning in action names:

```bash
# Version 1
"action": "user.created.v1"

# Version 2 (breaking changes)
"action": "user.created.v2"

# Or use namespacing
"action": "v2.user.created"
```

### What JSON Schema features are supported?

Amebo supports JSON Schema Draft 7:

- **Types**: string, number, integer, boolean, array, object, null
- **Formats**: email, date-time, uri, uuid, etc.
- **Validation**: required, minimum, maximum, pattern, etc.
- **Composition**: allOf, anyOf, oneOf, not
- **References**: $ref (within same schema)

### How do I handle schema evolution?

1. **Additive changes**: Add optional fields
2. **Breaking changes**: Create new action version
3. **Deprecation**: Mark old actions as deprecated
4. **Migration**: Provide migration tools/scripts

## Troubleshooting

### Events are not being delivered

Check these common issues:

1. **Webhook endpoint** is accessible
2. **Subscription** is correctly configured
3. **Application** is registered
4. **Network connectivity** between Amebo and target
5. **Webhook handler** returns 200-299 status

### High memory usage

Optimize configuration:

```bash
# Reduce batch size
AMEBO_ENVELOPE=128

# Increase idle time
AMEBO_IDLES=10

# Adjust rest threshold
AMEBO_REST_WHEN=5
```

### Database connection errors

For PostgreSQL:

```bash
# Check service status
sudo systemctl status postgresql

# Test connection
psql -h localhost -U amebo -d amebo

# Check connection limits
SELECT * FROM pg_stat_activity;
```

### Slow response times

Performance tuning:

1. **Database indexing**: Ensure proper indexes
2. **Connection pooling**: Configure pool size
3. **Batch processing**: Optimize envelope size
4. **Resource allocation**: Increase CPU/RAM
5. **Load balancing**: Add more instances

## Monitoring & Operations

### What metrics should I monitor?

Key metrics:

- **Response time**: < 10ms average
- **Error rate**: < 1%
- **Event throughput**: Events/second
- **Webhook delivery rate**: Success percentage
- **Database connections**: Pool utilization
- **Memory usage**: < 80%
- **CPU usage**: < 80%

### How do I set up monitoring?

Use the included monitoring stack:

```bash
# Start monitoring
docker-compose -f docker-compose.monitoring.yml up -d

# Access Grafana
open http://localhost:3000
```

### How do I backup data?

```bash
# PostgreSQL backup
docker exec amebo-postgres pg_dump -U amebo amebo > backup.sql

# Automated backup script
cat > backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/amebo/backups"
mkdir -p $BACKUP_DIR
docker exec amebo-postgres pg_dump -U amebo amebo > $BACKUP_DIR/amebo-$(date +%Y%m%d).sql
find $BACKUP_DIR -name "*.sql" -mtime +7 -delete
EOF

chmod +x backup.sh
echo "0 2 * * * /path/to/backup.sh" | crontab -
```

## Integration

### How do I integrate with existing systems?

Common integration patterns:

1. **API Gateway**: Route events through gateway
2. **Message Queues**: Bridge to existing queues
3. **Databases**: Trigger events on data changes
4. **Monitoring**: Send events to monitoring systems
5. **Analytics**: Stream events to analytics platforms

### Can I use Amebo with Kubernetes?

Yes, see the Kubernetes deployment example:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: amebo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: amebo
  template:
    metadata:
      labels:
        app: amebo
    spec:
      containers:
      - name: amebo
        image: rayattack/amebo:latest
        ports:
        - containerPort: 3310
        env:
        - name: AMEBO_SECRET
          valueFrom:
            secretKeyRef:
              name: amebo-secret
              key: secret
```

### How do I migrate from other event systems?

Migration strategies:

1. **Parallel running**: Run both systems simultaneously
2. **Gradual migration**: Move services one by one
3. **Event bridging**: Forward events between systems
4. **Schema mapping**: Convert existing schemas
5. **Testing**: Validate event delivery

## Getting Help

### Where can I get support?

- **Documentation**: This comprehensive guide
- **GitHub Issues**: [Report bugs](https://github.com/rayattack/amebo/issues)
- **Discussions**: [Ask questions](https://github.com/rayattack/amebo/discussions)
- **Community**: Join the community forums

### How do I report a bug?

1. **Check existing issues** first
2. **Provide minimal reproduction** case
3. **Include logs** and error messages
4. **Specify version** and environment
5. **Use issue template** if available

### How do I contribute?

See the [Contributing Guide](../development/contributing.md) for:

- Code contributions
- Documentation improvements
- Bug reports
- Feature requests
- Community support
