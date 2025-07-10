# Troubleshooting Guide

Common issues and solutions for Amebo deployments.

## Common Issues

### Service Won't Start

**Symptoms**: Amebo container exits immediately

**Solutions**:
```bash
# Check logs
docker logs amebo

# Verify configuration
docker exec amebo cat /app/amebo.json

# Check port conflicts
netstat -tulpn | grep :3310
```

### Database Connection Failed

**Symptoms**: "Connection refused" or "Database not found" errors

**Solutions**:
```bash
# Test database connectivity
docker exec amebo-postgres psql -U amebo -d amebo -c "SELECT 1;"

# Check network connectivity
docker exec amebo ping postgres

# Verify credentials
echo $AMEBO_DSN
```

### Webhook Delivery Failures

**Symptoms**: Events published but not delivered to subscribers

**Solutions**:
```bash
# Check delivery status
curl http://localhost/v1/gists

# Test webhook endpoint
curl -X POST https://your-app.com/webhook \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# Verify subscription configuration
curl http://localhost/v1/subscriptions
```

### High Memory Usage

**Symptoms**: Container using excessive memory

**Solutions**:
```bash
# Monitor resource usage
docker stats amebo

# Adjust configuration
AMEBO_ENVELOPE=128  # Reduce batch size
AMEBO_IDLES=10      # Increase idle time

# Check for memory leaks
docker exec amebo ps aux
```

### Schema Validation Errors

**Symptoms**: Events rejected with validation errors

**Solutions**:
```bash
# Verify schema definition
curl http://localhost/v1/actions/user.created

# Test payload locally
python -c "
import jsonschema
schema = {...}
payload = {...}
jsonschema.validate(payload, schema)
"

# Check action exists
curl http://localhost/v1/actions
```

## Debugging Tools

### Log Analysis
```bash
# View application logs
docker logs -f amebo

# Search for errors
docker logs amebo 2>&1 | grep ERROR

# Export logs
docker logs amebo > amebo.log 2>&1
```

### Health Checks
```bash
# Basic health check
curl -f http://localhost/health

# Detailed health check
curl http://localhost/health/detailed

# Database health
curl http://localhost/health/database
```

### Performance Analysis
```bash
# Monitor response times
curl -w "@curl-format.txt" -o /dev/null -s http://localhost/v1/applications

# Database query analysis
docker exec amebo-postgres psql -U amebo -d amebo -c "
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY total_time DESC LIMIT 10;"
```

## Getting Help

1. **Check logs** first
2. **Search documentation** for similar issues
3. **Check GitHub issues** for known problems
4. **Create new issue** with detailed information

### Issue Template
When reporting issues, include:
- Amebo version
- Deployment method (Docker, source, etc.)
- Operating system
- Error messages and logs
- Steps to reproduce
- Expected vs actual behavior

## Next Steps
- [Performance Guide](performance.md)
- [FAQ](faq.md)
- [Migration Guide](migration.md)
