# Performance Optimization

Guidelines for optimizing Amebo performance in production environments.

## Performance Targets

- **Response Time**: < 10ms (p95)
- **Throughput**: 1000+ events/second per instance
- **Error Rate**: < 0.1%
- **Availability**: 99.9%

## Configuration Tuning

### Application Settings
```json
{
  "AMEBO_ENVELOPE": 512,     // Increase batch size for higher throughput
  "AMEBO_IDLES": 3,          // Reduce idle time for better responsiveness
  "AMEBO_REST_WHEN": 10      // Adjust rest threshold based on load
}
```

### Database Optimization
```sql
-- PostgreSQL performance settings
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
SELECT pg_reload_conf();
```

## Monitoring Performance

### Key Metrics
```python
# Application metrics to monitor
- Request rate (requests/second)
- Response time (p50, p95, p99)
- Error rate (%)
- Event processing rate
- Webhook delivery success rate
- Database connection pool usage
- Memory usage
- CPU utilization
```

### Performance Testing
```bash
# Load testing with Apache Bench
ab -n 10000 -c 100 -H "Authorization: Bearer TOKEN" \
   -p event.json -T application/json \
   http://localhost/v1/events

# Load testing with wrk
wrk -t12 -c400 -d30s --script=post-event.lua http://localhost/v1/events
```

## Scaling Strategies

### Horizontal Scaling
```yaml
# Docker Compose scaling
docker-compose up -d --scale amebo=5

# Kubernetes scaling
kubectl scale deployment amebo --replicas=5
```

### Vertical Scaling
```yaml
# Increase container resources
services:
  amebo:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 4G
```

## Database Performance

### Connection Pooling
```python
# Optimize connection pool settings
DATABASE_POOL_SIZE = 20
DATABASE_MAX_OVERFLOW = 30
DATABASE_POOL_TIMEOUT = 30
```

### Query Optimization
```sql
-- Add indexes for common queries
CREATE INDEX idx_events_action ON events(action);
CREATE INDEX idx_events_timestamp ON events(timestamped);
CREATE INDEX idx_subscriptions_action ON subscriptions(action);
```

## Caching Strategies

### Application-Level Caching
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_action_schema(action_name):
    """Cache action schemas for validation"""
    return database.get_action_schema(action_name)
```

### Database Query Caching
```sql
-- Enable query result caching
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
```

## Best Practices

1. **Monitor continuously**: Set up comprehensive monitoring
2. **Test regularly**: Regular performance testing
3. **Optimize queries**: Use EXPLAIN ANALYZE for slow queries
4. **Scale proactively**: Scale before hitting limits
5. **Cache wisely**: Cache frequently accessed data

## Troubleshooting Performance Issues

### High Response Times
- Check database query performance
- Monitor connection pool usage
- Verify adequate resources
- Check for lock contention

### Low Throughput
- Increase batch size (AMEBO_ENVELOPE)
- Add more instances
- Optimize database queries
- Check network latency

### Memory Issues
- Monitor for memory leaks
- Adjust garbage collection settings
- Optimize data structures
- Check for large payloads

## Next Steps
- [Scaling Guide](../deployment/scaling.md)
- [Monitoring Setup](../deployment/monitoring.md)
- [Troubleshooting](troubleshooting.md)
