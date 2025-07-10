# Monitoring & Observability

Comprehensive monitoring setup for Amebo deployments with metrics, logging, and alerting.

## Overview

Effective monitoring is crucial for production Amebo deployments. This guide covers metrics collection, visualization, and alerting strategies.

## Monitoring Stack

### Prometheus + Grafana
The recommended monitoring stack:

```yaml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

### Key Metrics

#### Application Metrics
- Request rate (requests/second)
- Response time (p50, p95, p99)
- Error rate (%)
- Event processing rate
- Webhook delivery success rate

#### System Metrics
- CPU utilization
- Memory usage
- Disk I/O
- Network traffic
- Database connections

#### Business Metrics
- Events published per application
- Subscription health
- Schema validation failures
- Delivery latency

## Configuration

### Prometheus Configuration
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'amebo'
    static_configs:
      - targets: ['amebo:3310']
    metrics_path: '/metrics'
    scrape_interval: 30s

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:5432']
```

### Grafana Dashboards
Import pre-built dashboards for:
- Application overview
- Database performance
- System resources
- Business metrics

## Alerting

### Alert Rules
```yaml
groups:
  - name: amebo
    rules:
      - alert: HighErrorRate
        expr: rate(amebo_errors_total[5m]) > 0.1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"

      - alert: ServiceDown
        expr: up{job="amebo"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Amebo service is down"
```

### Notification Channels
- Slack integration
- Email alerts
- PagerDuty integration
- Webhook notifications

## Logging

### Structured Logging
```python
import structlog

logger = structlog.get_logger()

def publish_event(action, payload):
    logger.info(
        "event_published",
        action=action,
        payload_size=len(str(payload)),
        timestamp=datetime.utcnow().isoformat()
    )
```

### Log Aggregation
Use ELK stack or similar:
- Elasticsearch for storage
- Logstash for processing
- Kibana for visualization

### Log Levels
- DEBUG: Detailed debugging information
- INFO: General operational messages
- WARNING: Warning conditions
- ERROR: Error conditions
- CRITICAL: Critical conditions

## Health Checks

### Application Health
```bash
# Basic health check
curl -f http://localhost:3310/health

# Detailed health check
curl http://localhost:3310/health/detailed
```

### Database Health
```bash
# PostgreSQL health
docker exec postgres pg_isready -U amebo -d amebo

# Connection pool status
curl http://localhost:3310/health/database
```

### Dependency Health
Monitor external dependencies:
- Database connectivity
- Network connectivity
- Disk space
- Memory availability

## Performance Monitoring

### Response Time Tracking
```python
import time
from functools import wraps

def monitor_performance(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start_time
        
        metrics.histogram('function_duration', duration, tags=[
            f'function:{func.__name__}'
        ])
        
        return result
    return wrapper
```

### Database Performance
Monitor:
- Query execution time
- Connection pool usage
- Lock contention
- Index usage

## Troubleshooting

### Common Issues
1. **High memory usage**
   - Check for memory leaks
   - Optimize batch sizes
   - Monitor garbage collection

2. **Slow response times**
   - Database query optimization
   - Connection pool tuning
   - Resource allocation

3. **Failed webhook deliveries**
   - Network connectivity
   - Endpoint availability
   - Timeout configuration

### Debug Tools
```bash
# View application logs
docker logs amebo-instance-1

# Monitor resource usage
docker stats

# Database query analysis
EXPLAIN ANALYZE SELECT * FROM events WHERE action = 'user.created';
```

## Best Practices

### Monitoring Strategy
1. **Start simple**: Basic metrics first
2. **Add gradually**: Expand monitoring over time
3. **Focus on SLIs**: Service Level Indicators
4. **Set SLOs**: Service Level Objectives
5. **Automate alerts**: Reduce manual monitoring

### Dashboard Design
- Clear, actionable visualizations
- Logical grouping of metrics
- Appropriate time ranges
- Color coding for status

### Alert Management
- Avoid alert fatigue
- Clear escalation procedures
- Runbook documentation
- Regular alert review

## Next Steps
- [Performance Tuning](../support/performance.md)
- [Troubleshooting Guide](../support/troubleshooting.md)
- [Production Deployment](production.md)
