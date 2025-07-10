# Scaling Guide

Strategies and best practices for scaling Amebo to handle increased load and ensure high availability.

## Scaling Strategies

### Horizontal Scaling
Add more Amebo instances:
```bash
# Scale with Docker Compose
docker-compose up -d --scale amebo=5

# Kubernetes scaling
kubectl scale deployment amebo --replicas=5
```

### Vertical Scaling
Increase resources per instance:
```yaml
services:
  amebo:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 4G
```

### Database Scaling
- Read replicas for query distribution
- Connection pooling optimization
- Database sharding strategies

## Load Balancing

### Nginx Configuration
```nginx
upstream amebo_backend {
    least_conn;
    server amebo-1:3310 max_fails=3 fail_timeout=30s;
    server amebo-2:3310 max_fails=3 fail_timeout=30s;
    server amebo-3:3310 max_fails=3 fail_timeout=30s;
}
```

### Health Checks
Ensure load balancer only routes to healthy instances:
```nginx
location /health {
    proxy_pass http://amebo_backend/health;
    proxy_connect_timeout 5s;
    proxy_read_timeout 5s;
}
```

## Performance Optimization

### Configuration Tuning
```json
{
  "AMEBO_ENVELOPE": 1024,
  "AMEBO_IDLES": 2,
  "AMEBO_REST_WHEN": 20
}
```

### Database Optimization
```sql
-- Increase connection limits
ALTER SYSTEM SET max_connections = 500;

-- Optimize memory settings
ALTER SYSTEM SET shared_buffers = '512MB';
ALTER SYSTEM SET effective_cache_size = '2GB';
```

## Monitoring at Scale

### Key Metrics
- Requests per second across all instances
- Response time distribution
- Error rates by instance
- Resource utilization trends

### Auto-scaling
```yaml
# Kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: amebo-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: amebo
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## Best Practices

### Capacity Planning
1. Baseline performance testing
2. Load testing with realistic scenarios
3. Monitor growth trends
4. Plan for peak loads

### Deployment Strategies
- Blue-green deployments
- Rolling updates
- Canary releases
- Circuit breaker patterns

### Data Management
- Event retention policies
- Archive old events
- Optimize database indexes
- Regular maintenance tasks

## Next Steps
- [Production Deployment](production.md)
- [Monitoring Setup](monitoring.md)
- [Performance Tuning](../support/performance.md)
