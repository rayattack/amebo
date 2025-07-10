# Docker Deployment

Deploy Amebo using Docker for consistent, portable, and scalable deployments across environments.

## Quick Start

### Single Instance

Run Amebo as a single Docker container:

```bash
# Create configuration
cat > amebo.json << EOF
{
  "AMEBO_SECRET": "your-secret-key-32-chars-long",
  "AMEBO_DSN": "sqlite:///amebo.db",
  "AMEBO_USERNAME": "admin",
  "AMEBO_PASSWORD": "secure-password",
  "AMEBO_PORT": 3310
}
EOF

# Run container
docker run -d \
  --name amebo \
  -p 3310:3310 \
  -v $(pwd)/amebo.json:/app/amebo.json \
  rayattack/amebo:latest
```

### With PostgreSQL

Run with a PostgreSQL database:

```bash
# Start PostgreSQL
docker run -d \
  --name amebo-postgres \
  -e POSTGRES_DB=amebo \
  -e POSTGRES_USER=amebo \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  postgres:15-alpine

# Start Amebo
docker run -d \
  --name amebo \
  --link amebo-postgres:postgres \
  -p 3310:3310 \
  -e AMEBO_SECRET="your-secret-key" \
  -e AMEBO_DSN="postgresql://amebo:password@postgres:5432/amebo" \
  -e AMEBO_USERNAME="admin" \
  -e AMEBO_PASSWORD="secure-password" \
  rayattack/amebo:latest
```

## Docker Compose

### Basic Setup

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: amebo
      POSTGRES_USER: amebo
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U amebo -d amebo"]
      interval: 10s
      timeout: 5s
      retries: 5

  amebo:
    image: rayattack/amebo:latest
    ports:
      - "3310:3310"
    environment:
      AMEBO_SECRET: your-secret-key-32-chars-long
      AMEBO_DSN: postgresql://amebo:password@postgres:5432/amebo
      AMEBO_USERNAME: admin
      AMEBO_PASSWORD: secure-password
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres_data:
```

Start the services:

```bash
docker-compose up -d
```

### Production Setup

Enhanced production configuration:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: amebo
      POSTGRES_USER: amebo
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgresql.conf:/etc/postgresql/postgresql.conf
    command: postgres -c config_file=/etc/postgresql/postgresql.conf
    secrets:
      - postgres_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U amebo -d amebo"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  amebo:
    image: rayattack/amebo:latest
    ports:
      - "3310:3310"
    environment:
      AMEBO_SECRET_FILE: /run/secrets/amebo_secret
      AMEBO_DSN: postgresql://amebo:password@postgres:5432/amebo
      AMEBO_USERNAME: admin
      AMEBO_PASSWORD_FILE: /run/secrets/amebo_password
      AMEBO_ENVELOPE: 512
      AMEBO_IDLES: 3
    secrets:
      - amebo_secret
      - amebo_password
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3310/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M

secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt
  amebo_secret:
    file: ./secrets/amebo_secret.txt
  amebo_password:
    file: ./secrets/amebo_password.txt

volumes:
  postgres_data:
    driver: local
```

## Custom Docker Image

### Building from Source

Create a custom Dockerfile:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd --create-home --shell /bin/bash amebo && \
    chown -R amebo:amebo /app

USER amebo

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${AMEBO_PORT:-3310}/health || exit 1

# Default command
CMD ["python", "-m", "amebo.main"]
```

Build and run:

```bash
# Build image
docker build -t my-amebo:latest .

# Run container
docker run -d \
  --name my-amebo \
  -p 3310:3310 \
  -e AMEBO_SECRET="your-secret" \
  -e AMEBO_DSN="sqlite:///amebo.db" \
  my-amebo:latest
```

### Multi-stage Build

Optimize image size:

```dockerfile
# Build stage
FROM python:3.11-slim as builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --user --no-cache-dir -e .

# Runtime stage
FROM python:3.11-slim

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application
COPY --from=builder /app /app

WORKDIR /app

# Create non-root user
RUN useradd --create-home --shell /bin/bash amebo && \
    chown -R amebo:amebo /app

USER amebo

# Update PATH
ENV PATH=/root/.local/bin:$PATH

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${AMEBO_PORT:-3310}/health || exit 1

CMD ["python", "-m", "amebo.main"]
```

## Environment Configuration

### Environment Files

Create `.env` file:

```bash
# Database
POSTGRES_DB=amebo
POSTGRES_USER=amebo
POSTGRES_PASSWORD=secure-password

# Application
AMEBO_SECRET=your-secret-key-32-chars-long
AMEBO_USERNAME=admin
AMEBO_PASSWORD=admin-password
AMEBO_DSN=postgresql://amebo:secure-password@postgres:5432/amebo

# Performance
AMEBO_ENVELOPE=256
AMEBO_IDLES=5
AMEBO_REST_WHEN=0
```

Use with Docker Compose:

```yaml
version: '3.8'

services:
  amebo:
    image: rayattack/amebo:latest
    env_file:
      - .env
    ports:
      - "3310:3310"
```

### Secrets Management

Use Docker secrets:

```bash
# Create secrets
echo "your-secret-key-32-chars-long" | docker secret create amebo_secret -
echo "secure-admin-password" | docker secret create amebo_password -

# Use in compose
version: '3.8'

services:
  amebo:
    image: rayattack/amebo:latest
    environment:
      AMEBO_SECRET_FILE: /run/secrets/amebo_secret
      AMEBO_PASSWORD_FILE: /run/secrets/amebo_password
    secrets:
      - amebo_secret
      - amebo_password

secrets:
  amebo_secret:
    external: true
  amebo_password:
    external: true
```

## Networking

### Custom Networks

Create isolated networks:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    networks:
      - backend

  amebo:
    image: rayattack/amebo:latest
    networks:
      - backend
      - frontend
    ports:
      - "3310:3310"

networks:
  backend:
    driver: bridge
    internal: true
  frontend:
    driver: bridge
```

### Reverse Proxy

Use Nginx as reverse proxy:

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - amebo

  amebo:
    image: rayattack/amebo:latest
    expose:
      - "3310"
    environment:
      AMEBO_SECRET: your-secret-key
      AMEBO_DSN: postgresql://amebo:password@postgres:5432/amebo
```

Nginx configuration:

```nginx
upstream amebo {
    server amebo:3310;
}

server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://amebo;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Monitoring

### Health Checks

Configure health checks:

```yaml
services:
  amebo:
    image: rayattack/amebo:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3310/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### Logging

Configure logging:

```yaml
services:
  amebo:
    image: rayattack/amebo:latest
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Metrics

Expose metrics:

```yaml
services:
  amebo:
    image: rayattack/amebo:latest
    environment:
      METRICS_ENABLED: "true"
      METRICS_PORT: "9090"
    ports:
      - "3310:3310"
      - "9090:9090"
```

## Backup & Recovery

### Database Backup

Automated backup:

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/opt/amebo/backups"
mkdir -p $BACKUP_DIR

# Create backup
docker exec amebo-postgres pg_dump -U amebo amebo > $BACKUP_DIR/amebo-$(date +%Y%m%d-%H%M%S).sql

# Cleanup old backups (keep 7 days)
find $BACKUP_DIR -name "*.sql" -mtime +7 -delete

echo "Backup completed: $BACKUP_DIR/amebo-$(date +%Y%m%d-%H%M%S).sql"
```

Schedule with cron:

```bash
# Add to crontab
0 2 * * * /opt/amebo/backup.sh
```

### Volume Backup

Backup Docker volumes:

```bash
# Backup volume
docker run --rm \
  -v amebo_postgres_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/postgres-backup-$(date +%Y%m%d).tar.gz -C /data .

# Restore volume
docker run --rm \
  -v amebo_postgres_data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/postgres-backup-20241210.tar.gz -C /data
```

## Troubleshooting

### Common Issues

1. **Container won't start**
   ```bash
   # Check logs
   docker logs amebo
   
   # Check configuration
   docker exec amebo cat /app/amebo.json
   ```

2. **Database connection failed**
   ```bash
   # Test database connectivity
   docker exec amebo-postgres psql -U amebo -d amebo -c "SELECT 1;"
   
   # Check network
   docker exec amebo ping postgres
   ```

3. **Permission issues**
   ```bash
   # Check file permissions
   docker exec amebo ls -la /app/
   
   # Fix ownership
   docker exec --user root amebo chown -R amebo:amebo /app/
   ```

### Performance Tuning

Optimize container resources:

```yaml
services:
  amebo:
    image: rayattack/amebo:latest
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
    environment:
      AMEBO_ENVELOPE: 512
      AMEBO_IDLES: 3
```

## Next Steps

- [Docker Cluster](docker-cluster.md) - High availability cluster setup
- [Production Deployment](production.md) - Production best practices
- [Monitoring](monitoring.md) - Comprehensive monitoring setup
