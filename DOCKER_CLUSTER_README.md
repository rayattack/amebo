# Amebo Docker Cluster Setup

This setup provides a resilient Amebo cluster with 3 application instances, a shared PostgreSQL database, and an Nginx load balancer for high availability.

!!! note "Documentation Moved"
    The complete Docker cluster documentation is now available at: [Docker Cluster Guide](docs/deployment/docker-cluster.md)

## Architecture

```
┌─────────────────┐    ┌─────────────────┐
│   Load Balancer │    │   Monitoring    │
│     (Nginx)     │    │   (Optional)    │
│    Port: 80     │    │ Grafana: 3000   │
└─────────┬───────┘    │ Prometheus:9090 │
          │            └─────────────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│ Amebo-1 │ │ Amebo-2 │ │ Amebo-3 │
│Port:3311│ │Port:3312│ │Port:3313│
└────┬────┘ └────┬────┘ └────┬────┘
     │           │           │
     └───────────┼───────────┘
                 │
         ┌───────▼───────┐
         │  PostgreSQL   │
         │   Port: 5432  │
         └───────────────┘
```

## Quick Start

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+
- 4GB+ RAM available
- Ports 80, 3311-3313, 5432 available

### 1. Start the Cluster
```bash
# Make scripts executable
chmod +x start-cluster.sh stop-cluster.sh

# Start the cluster
./start-cluster.sh
```

### 2. Verify the Setup
```bash
# Check all services are running
docker-compose ps

# Test the load balancer
curl http://localhost/v1/applications

# Test individual instances
curl http://localhost:3311/v1/applications
curl http://localhost:3312/v1/applications
curl http://localhost:3313/v1/applications
```

### 3. Stop the Cluster
```bash
# Stop without removing data
./stop-cluster.sh

# Stop and remove all data (WARNING: destructive)
./stop-cluster.sh --remove-volumes
```

## Configuration

### Environment Variables
Copy `.env.example` to `.env` and modify as needed:

```bash
cp .env.example .env
# Edit .env with your preferred settings
```

### Production Configuration
For production use:
1. Copy `.env.production` to `.env`
2. Change all default passwords and secrets
3. Configure SSL certificates for Nginx
4. Adjust resource limits in docker-compose.yml

## Monitoring (Optional)

Start the monitoring stack:
```bash
docker-compose -f docker-compose.monitoring.yml up -d
```

Access monitoring tools:
- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **cAdvisor**: http://localhost:8080

## High Availability Features

### Load Balancing
- **Algorithm**: Least connections
- **Health Checks**: Automatic failover if instance fails
- **Retry Logic**: 3 retries with 30s timeout

### Database Resilience
- **Shared Database**: All instances use the same PostgreSQL
- **Connection Pooling**: Built-in asyncpg connection pooling
- **Health Checks**: Database connectivity monitoring

### Container Resilience
- **Restart Policy**: `unless-stopped` for all services
- **Health Checks**: HTTP endpoints for application health
- **Graceful Shutdown**: Proper signal handling

## Scaling

### Horizontal Scaling
Add more Amebo instances:
```bash
# Scale to 5 instances
docker-compose up -d --scale amebo-1=2 --scale amebo-2=2 --scale amebo-3=1

# Or add new services in docker-compose.yml
```

### Vertical Scaling
Adjust resource limits in docker-compose.yml:
```yaml
services:
  amebo-1:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**
   ```bash
   # Check what's using the ports
   netstat -tulpn | grep :80
   netstat -tulpn | grep :5432
   ```

2. **Database Connection Issues**
   ```bash
   # Check PostgreSQL logs
   docker logs amebo-postgres
   
   # Test database connectivity
   docker exec -it amebo-postgres psql -U amebo -d amebo
   ```

3. **Application Startup Issues**
   ```bash
   # Check application logs
   docker logs amebo-instance-1
   docker logs amebo-instance-2
   docker logs amebo-instance-3
   ```

4. **Load Balancer Issues**
   ```bash
   # Check Nginx logs
   docker logs amebo-loadbalancer
   
   # Test backend connectivity
   docker exec -it amebo-loadbalancer wget -qO- http://amebo-1:3310/v1/applications
   ```

### Health Check Commands
```bash
# Check service health
docker-compose ps

# Check individual container health
docker inspect amebo-instance-1 | grep -A 10 Health

# Manual health check
curl -f http://localhost/health
```

### Log Management
```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f amebo-1

# View logs with timestamps
docker-compose logs -f -t

# Limit log output
docker-compose logs --tail=100 -f
```

## Security Considerations

### Production Checklist
- [ ] Change all default passwords
- [ ] Use strong secrets (32+ characters)
- [ ] Configure SSL/TLS certificates
- [ ] Set up firewall rules
- [ ] Enable log rotation
- [ ] Configure backup strategy
- [ ] Set up monitoring alerts
- [ ] Review container security settings

### Network Security
- All services run in isolated Docker network
- Only necessary ports exposed to host
- Internal communication uses service names
- Load balancer provides single entry point

## Backup and Recovery

### Database Backup
```bash
# Create backup
docker exec amebo-postgres pg_dump -U amebo amebo > backup.sql

# Restore backup
docker exec -i amebo-postgres psql -U amebo amebo < backup.sql
```

### Full System Backup
```bash
# Backup volumes
docker run --rm -v amebo_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_backup.tar.gz -C /data .

# Restore volumes
docker run --rm -v amebo_postgres_data:/data -v $(pwd):/backup alpine tar xzf /backup/postgres_backup.tar.gz -C /data
```

## Performance Tuning

### PostgreSQL Optimization
Edit `init-db.sql` to add performance settings:
```sql
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
```

### Application Optimization
Adjust environment variables:
```bash
AMEBO_ENVELOPE=512    # Increase batch size
AMEBO_IDLES=3         # Reduce idle time
AMEBO_REST_WHEN=10    # Adjust rest threshold
```

## Support

For issues and questions:
1. Check the logs using commands above
2. Review the troubleshooting section
3. Check the main Amebo documentation
4. Open an issue on the project repository
