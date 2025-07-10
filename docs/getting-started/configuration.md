# Configuration Guide

Comprehensive guide to configuring Amebo for different environments and use cases.

## Configuration Methods

Amebo supports multiple configuration methods, listed in order of precedence:

1. **Command line arguments** (highest priority)
2. **Environment variables**
3. **Configuration file** (amebo.json)
4. **Default values** (lowest priority)

## Configuration File

The primary configuration method uses a JSON file named `amebo.json`:

```json
{
  "AMEBO_USERNAME": "administrator",
  "AMEBO_PASSWORD": "secure-password-here",
  "AMEBO_SECRET": "your-32-character-secret-key",
  "AMEBO_DSN": "postgresql://user:pass@localhost/amebo",
  "AMEBO_PORT": 3310,
  "AMEBO_ENVELOPE": 256,
  "AMEBO_IDLES": 5,
  "AMEBO_REST_WHEN": 0
}
```

### Custom Configuration File

Use a different configuration file:

```bash
# Specify custom config file
amebo --config production.json

# Or set environment variable
export AMEBO_CONFIG_FILE=production.json
amebo
```

## Environment Variables

All configuration options can be set via environment variables:

```bash
export AMEBO_USERNAME="admin"
export AMEBO_PASSWORD="secure-password"
export AMEBO_SECRET="your-secret-key"
export AMEBO_DSN="postgresql://user:pass@localhost/amebo"
export AMEBO_PORT=3310

# Start Amebo
amebo
```

## Command Line Arguments

Override any setting with command line arguments:

```bash
amebo \
  --amebo_username admin \
  --amebo_password secure-password \
  --amebo_secret your-secret-key \
  --amebo_dsn "postgresql://user:pass@localhost/amebo" \
  --amebo_port 3310
```

## Configuration Options

### Core Settings

| Option | Type | Required | Description | Default |
|--------|------|----------|-------------|---------|
| `AMEBO_SECRET` | string | ✅ | JWT signing secret (32+ chars) | - |
| `AMEBO_DSN` | string | ✅ | Database connection string | - |
| `AMEBO_PORT` | integer | ❌ | HTTP server port | 3310 |

### Authentication

| Option | Type | Required | Description | Default |
|--------|------|----------|-------------|---------|
| `AMEBO_USERNAME` | string | ❌ | Admin username | admin |
| `AMEBO_PASSWORD` | string | ❌ | Admin password | - |

### Performance

| Option | Type | Required | Description | Default |
|--------|------|----------|-------------|---------|
| `AMEBO_ENVELOPE` | integer | ❌ | Batch processing size | 256 |
| `AMEBO_IDLES` | integer | ❌ | Idle sleep time (seconds) | 5 |
| `AMEBO_REST_WHEN` | integer | ❌ | Rest threshold | 0 |

## Database Configuration

### PostgreSQL (Recommended)

```json
{
  "AMEBO_DSN": "postgresql://username:password@hostname:port/database"
}
```

**Connection String Format:**
```
postgresql://[user[:password]@][host][:port][/dbname][?param1=value1&...]
```

**Examples:**
```bash
# Local PostgreSQL
"postgresql://amebo:password@localhost:5432/amebo"

# Remote PostgreSQL with SSL
"postgresql://user:pass@db.example.com:5432/amebo?sslmode=require"

# Connection pooling
"postgresql://user:pass@localhost:5432/amebo?pool_size=20&max_overflow=30"
```

### SQLite (Development)

```json
{
  "AMEBO_DSN": "sqlite:///path/to/database.db"
}
```

**Examples:**
```bash
# Relative path
"sqlite:///amebo.db"

# Absolute path
"sqlite:////opt/amebo/data/amebo.db"

# In-memory (testing only)
"sqlite:///:memory:"
```

## Environment-Specific Configurations

### Development

```json
{
  "AMEBO_USERNAME": "admin",
  "AMEBO_PASSWORD": "admin",
  "AMEBO_SECRET": "dev-secret-key-not-for-production",
  "AMEBO_DSN": "sqlite:///amebo.db",
  "AMEBO_PORT": 3310,
  "AMEBO_ENVELOPE": 128,
  "AMEBO_IDLES": 10,
  "AMEBO_REST_WHEN": 0
}
```

### Testing

```json
{
  "AMEBO_USERNAME": "test",
  "AMEBO_PASSWORD": "test",
  "AMEBO_SECRET": "test-secret-key",
  "AMEBO_DSN": "sqlite:///:memory:",
  "AMEBO_PORT": 3311,
  "AMEBO_ENVELOPE": 64,
  "AMEBO_IDLES": 1,
  "AMEBO_REST_WHEN": 0
}
```

### Production

```json
{
  "AMEBO_USERNAME": "admin",
  "AMEBO_PASSWORD": "STRONG_PRODUCTION_PASSWORD",
  "AMEBO_SECRET": "STRONG_32_CHARACTER_SECRET_KEY_HERE",
  "AMEBO_DSN": "postgresql://amebo:STRONG_DB_PASSWORD@db.internal:5432/amebo",
  "AMEBO_PORT": 3310,
  "AMEBO_ENVELOPE": 512,
  "AMEBO_IDLES": 3,
  "AMEBO_REST_WHEN": 10
}
```

## Security Configuration

### Secret Management

Generate strong secrets:

```bash
# Generate 32-character secret
openssl rand -hex 32

# Or use Python
python -c "import secrets; print(secrets.token_hex(32))"

# Or use Node.js
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

### Password Security

Use strong passwords:

```bash
# Generate strong password
openssl rand -base64 32

# Or use pwgen
pwgen -s 32 1
```

### Environment Variables for Secrets

Never commit secrets to version control:

```bash
# .env file (add to .gitignore)
AMEBO_SECRET=your-secret-here
AMEBO_PASSWORD=your-password-here
AMEBO_DSN=postgresql://user:pass@host/db

# Load from .env file
export $(cat .env | xargs)
amebo
```

## Performance Tuning

### Batch Processing

Optimize event processing:

```json
{
  "AMEBO_ENVELOPE": 512,    // Larger batches for high throughput
  "AMEBO_IDLES": 3,         // Shorter idle time for responsiveness
  "AMEBO_REST_WHEN": 10     // Rest when queue is small
}
```

### Database Optimization

PostgreSQL settings:

```sql
-- Connection pooling
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
SELECT pg_reload_conf();
```

### Memory Management

Monitor and adjust:

```bash
# Check memory usage
docker stats amebo-instance-1

# Adjust if needed
AMEBO_ENVELOPE=256  # Reduce batch size
AMEBO_IDLES=5       # Increase idle time
```

## Logging Configuration

### Log Levels

Set via environment:

```bash
export LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Log Format

Configure structured logging:

```bash
export LOG_FORMAT=json  # json, text
export LOG_TIMESTAMP=true
```

## Monitoring Configuration

### Health Checks

Configure health check endpoints:

```json
{
  "HEALTH_CHECK_ENABLED": true,
  "HEALTH_CHECK_PATH": "/health",
  "HEALTH_CHECK_TIMEOUT": 30
}
```

### Metrics

Enable metrics collection:

```json
{
  "METRICS_ENABLED": true,
  "METRICS_PATH": "/metrics",
  "METRICS_PORT": 9090
}
```

## Docker Configuration

### Environment File

Create `.env` for Docker Compose:

```bash
# Database
POSTGRES_DB=amebo
POSTGRES_USER=amebo
POSTGRES_PASSWORD=secure-password

# Application
AMEBO_SECRET=your-secret-key
AMEBO_USERNAME=admin
AMEBO_PASSWORD=admin-password
AMEBO_DSN=postgresql://amebo:secure-password@postgres:5432/amebo

# Performance
AMEBO_ENVELOPE=256
AMEBO_IDLES=5
AMEBO_REST_WHEN=0
```

### Docker Compose Override

Create `docker-compose.override.yml`:

```yaml
version: '3.8'

services:
  amebo-1:
    environment:
      AMEBO_ENVELOPE: 512
      AMEBO_IDLES: 3
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M
```

## Kubernetes Configuration

### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: amebo-config
data:
  AMEBO_PORT: "3310"
  AMEBO_ENVELOPE: "256"
  AMEBO_IDLES: "5"
  AMEBO_REST_WHEN: "0"
```

### Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: amebo-secret
type: Opaque
data:
  secret: <base64-encoded-secret>
  password: <base64-encoded-password>
  dsn: <base64-encoded-dsn>
```

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: amebo
spec:
  template:
    spec:
      containers:
      - name: amebo
        image: rayattack/amebo:latest
        envFrom:
        - configMapRef:
            name: amebo-config
        env:
        - name: AMEBO_SECRET
          valueFrom:
            secretKeyRef:
              name: amebo-secret
              key: secret
        - name: AMEBO_PASSWORD
          valueFrom:
            secretKeyRef:
              name: amebo-secret
              key: password
        - name: AMEBO_DSN
          valueFrom:
            secretKeyRef:
              name: amebo-secret
              key: dsn
```

## Validation

### Configuration Validation

Validate your configuration:

```bash
# Test configuration
amebo --config-check

# Validate database connection
amebo --test-db

# Check all settings
amebo --show-config
```

### Environment Validation

{% raw %}
```bash
#!/bin/bash
# validate-config.sh

echo "Validating Amebo configuration..."

# Check required variables
required_vars=("AMEBO_SECRET" "AMEBO_DSN")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: $var is not set"
        exit 1
    fi
done

# Check secret length
if [ ${#AMEBO_SECRET} -lt 32 ]; then
    echo "WARNING: AMEBO_SECRET should be at least 32 characters"
fi

# Check database connection
if ! echo "SELECT 1;" | psql "$AMEBO_DSN" > /dev/null 2>&1; then
    echo "ERROR: Cannot connect to database"
    exit 1
fi

echo "Configuration validation passed!"
```
{% endraw %}

## Troubleshooting

### Common Issues

1. **Invalid DSN format**
   ```bash
   # Check DSN format
   echo $AMEBO_DSN
   # Should be: postgresql://user:pass@host:port/db
   ```

2. **Port conflicts**
   ```bash
   # Check port usage
   netstat -tulpn | grep :3310
   # Change port if needed
   export AMEBO_PORT=3311
   ```

3. **Permission errors**
   ```bash
   # Check file permissions
   ls -la amebo.json
   chmod 600 amebo.json  # Secure config file
   ```

### Debug Mode

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
amebo
```

## Next Steps

- **[First Steps](first-steps.md)** - Create your first application and events
- **[Docker Deployment](../deployment/docker.md)** - Deploy with Docker
- **[Production Setup](../deployment/production.md)** - Production best practices
