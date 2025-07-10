# Installation Guide

This guide covers all the different ways to install and run Amebo, from development setups to production deployments.

## System Requirements

### Minimum Requirements

- **CPU**: 1 core
- **RAM**: 512MB
- **Storage**: 1GB
- **OS**: Linux, macOS, or Windows
- **Python**: 3.8+ (if installing from source)

### Recommended for Production

- **CPU**: 2+ cores
- **RAM**: 2GB+
- **Storage**: 10GB+ SSD
- **Database**: PostgreSQL 12+
- **Load Balancer**: Nginx or similar

## Installation Methods

=== "Docker (Recommended)"

    ### Single Instance

    ```bash
    # Pull the image
    docker pull rayattack/amebo:latest
    
    # Create configuration
    mkdir -p /opt/amebo
    cat > /opt/amebo/amebo.json << EOF
    {
      "AMEBO_SECRET": "your-secret-key-here",
      "AMEBO_DSN": "postgresql://user:pass@localhost/amebo",
      "AMEBO_PORT": 3310
    }
    EOF
    
    # Run container
    docker run -d \
      --name amebo \
      -p 3310:3310 \
      -v /opt/amebo/amebo.json:/app/amebo.json \
      rayattack/amebo:latest
    ```

    ### High Availability Cluster

    ```bash
    # Clone repository for cluster setup
    git clone https://github.com/rayattack/amebo.git
    cd amebo
    
    # Start 3-instance cluster with load balancer
    ./start-cluster.sh
    ```

=== "Python Package"

    ### From PyPI

    ```bash
    # Install from PyPI
    pip install amebo
    
    # Verify installation
    amebo --help
    ```

    ### With Virtual Environment

    ```bash
    # Create virtual environment
    python -m venv amebo-env
    source amebo-env/bin/activate  # On Windows: amebo-env\Scripts\activate
    
    # Install Amebo
    pip install amebo
    
    # Create configuration
    cat > amebo.json << EOF
    {
      "AMEBO_SECRET": "your-secret-key-here",
      "AMEBO_DSN": "sqlite:///amebo.db"
    }
    EOF
    
    # Start server
    amebo
    ```

=== "From Source"

    ### Development Setup

    ```bash
    # Clone repository
    git clone https://github.com/rayattack/amebo.git
    cd amebo
    
    # Create virtual environment
    python -m venv venv
    source venv/bin/activate
    
    # Install in development mode
    pip install -e .
    
    # Install development dependencies
    pip install -r requirements-dev.txt
    
    # Copy sample configuration
    cp sample-amebo.json amebo.json
    
    # Run tests
    pytest
    
    # Start development server
    python -m amebo.main
    ```

    ### Production Build

    ```bash
    # Clone and build
    git clone https://github.com/rayattack/amebo.git
    cd amebo
    
    # Install production dependencies
    pip install .
    
    # Create production configuration
    cp .env.production .env
    # Edit .env with your settings
    
    # Start with production settings
    amebo --config production.json
    ```

## Database Setup

Amebo supports multiple database backends:

=== "PostgreSQL (Recommended)"

    ### Installation

    ```bash
    # Ubuntu/Debian
    sudo apt update
    sudo apt install postgresql postgresql-contrib
    
    # CentOS/RHEL
    sudo yum install postgresql-server postgresql-contrib
    
    # macOS
    brew install postgresql
    
    # Start service
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    ```

    ### Database Creation

    ```sql
    -- Connect as postgres user
    sudo -u postgres psql
    
    -- Create database and user
    CREATE DATABASE amebo;
    CREATE USER amebo WITH PASSWORD 'your-password';
    GRANT ALL PRIVILEGES ON DATABASE amebo TO amebo;
    
    -- Exit
    \q
    ```

    ### Configuration

    ```json
    {
      "AMEBO_DSN": "postgresql://amebo:your-password@localhost:5432/amebo"
    }
    ```

=== "SQLite (Development)"

    SQLite requires no additional setup and is perfect for development:

    ```json
    {
      "AMEBO_DSN": "sqlite:///amebo.db"
    }
    ```

    The database file will be created automatically.

=== "Docker PostgreSQL"

    ```bash
    # Run PostgreSQL in Docker
    docker run -d \
      --name amebo-postgres \
      -e POSTGRES_DB=amebo \
      -e POSTGRES_USER=amebo \
      -e POSTGRES_PASSWORD=your-password \
      -p 5432:5432 \
      postgres:15-alpine
    
    # Configuration
    {
      "AMEBO_DSN": "postgresql://amebo:your-password@localhost:5432/amebo"
    }
    ```

## Configuration

### Configuration File

Create `amebo.json` with your settings:

```json
{
  "AMEBO_USERNAME": "admin",
  "AMEBO_PASSWORD": "secure-password",
  "AMEBO_SECRET": "your-secret-key-32-chars-long",
  "AMEBO_DSN": "postgresql://user:pass@localhost/amebo",
  "AMEBO_PORT": 3310,
  "AMEBO_ENVELOPE": 256,
  "AMEBO_IDLES": 5,
  "AMEBO_REST_WHEN": 0
}
```

### Environment Variables

Alternatively, use environment variables:

```bash
export AMEBO_USERNAME="admin"
export AMEBO_PASSWORD="secure-password"
export AMEBO_SECRET="your-secret-key-32-chars-long"
export AMEBO_DSN="postgresql://user:pass@localhost/amebo"
export AMEBO_PORT=3310
```

### Command Line Arguments

```bash
amebo \
  --amebo_username admin \
  --amebo_password secure-password \
  --amebo_secret your-secret-key \
  --amebo_dsn "postgresql://user:pass@localhost/amebo" \
  --amebo_port 3310
```

## Service Installation

=== "Systemd (Linux)"

    Create a systemd service file:

    ```bash
    sudo tee /etc/systemd/system/amebo.service << EOF
    [Unit]
    Description=Amebo HTTP Event Notifications Server
    After=network.target postgresql.service
    Wants=postgresql.service
    
    [Service]
    Type=simple
    User=amebo
    Group=amebo
    WorkingDirectory=/opt/amebo
    Environment=PATH=/opt/amebo/venv/bin
    ExecStart=/opt/amebo/venv/bin/amebo
    ExecReload=/bin/kill -HUP \$MAINPID
    Restart=always
    RestartSec=5
    
    [Install]
    WantedBy=multi-user.target
    EOF
    
    # Enable and start service
    sudo systemctl daemon-reload
    sudo systemctl enable amebo
    sudo systemctl start amebo
    ```

=== "Docker Compose"

    Create `docker-compose.yml`:

    ```yaml
    version: '3.8'
    
    services:
      amebo:
        image: rayattack/amebo:latest
        ports:
          - "3310:3310"
        environment:
          AMEBO_SECRET: your-secret-key
          AMEBO_DSN: postgresql://amebo:password@postgres:5432/amebo
        depends_on:
          - postgres
        restart: unless-stopped
    
      postgres:
        image: postgres:15-alpine
        environment:
          POSTGRES_DB: amebo
          POSTGRES_USER: amebo
          POSTGRES_PASSWORD: password
        volumes:
          - postgres_data:/var/lib/postgresql/data
        restart: unless-stopped
    
    volumes:
      postgres_data:
    ```

    ```bash
    # Start services
    docker-compose up -d
    ```

=== "Kubernetes"

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
            - name: AMEBO_DSN
              valueFrom:
                secretKeyRef:
                  name: amebo-secret
                  key: dsn
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: amebo-service
    spec:
      selector:
        app: amebo
      ports:
      - port: 80
        targetPort: 3310
      type: LoadBalancer
    ```

## Verification

After installation, verify Amebo is working:

```bash
# Check service status
curl http://localhost:3310/v1/applications

# Check health
curl http://localhost:3310/health

# View logs
# Docker: docker logs amebo
# Systemd: sudo journalctl -u amebo -f
# Source: check console output
```

## Troubleshooting

### Common Issues

!!! warning "Port Already in Use"
    
    ```bash
    # Find what's using the port
    sudo netstat -tulpn | grep :3310
    
    # Change port in configuration
    "AMEBO_PORT": 3311
    ```

!!! warning "Database Connection Failed"
    
    ```bash
    # Check PostgreSQL is running
    sudo systemctl status postgresql
    
    # Test connection
    psql -h localhost -U amebo -d amebo
    
    # Check firewall
    sudo ufw status
    ```

!!! warning "Permission Denied"
    
    ```bash
    # Create amebo user
    sudo useradd -r -s /bin/false amebo
    
    # Set permissions
    sudo chown -R amebo:amebo /opt/amebo
    sudo chmod +x /opt/amebo/venv/bin/amebo
    ```

### Log Locations

- **Docker**: `docker logs <container-name>`
- **Systemd**: `/var/log/syslog` or `journalctl -u amebo`
- **Source**: Console output or redirect to file

### Performance Tuning

```json
{
  "AMEBO_ENVELOPE": 512,     // Increase batch size
  "AMEBO_IDLES": 3,          // Reduce idle time
  "AMEBO_REST_WHEN": 10      // Adjust rest threshold
}
```

## Next Steps

- **[Configuration Guide](configuration.md)** - Detailed configuration options
- **[First Steps](first-steps.md)** - Create your first application and events
- **[Production Deployment](../deployment/production.md)** - Production best practices
- **[Monitoring Setup](../deployment/monitoring.md)** - Set up monitoring and alerting
