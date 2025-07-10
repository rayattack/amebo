#!/bin/bash

# Amebo Cluster Startup Script
# This script starts the Amebo cluster with 3 instances, PostgreSQL, and load balancer

set -e

echo "🚀 Starting Amebo Cluster..."

# Check if Docker and Docker Compose are installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create network if it doesn't exist
echo "📡 Creating Docker network..."
docker network create amebo-network 2>/dev/null || echo "Network already exists"

# Build the Amebo image
echo "🔨 Building Amebo Docker image..."
docker-compose build

# Start the cluster
echo "🏃 Starting Amebo cluster services..."
docker-compose up -d

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check service health
echo "🔍 Checking service health..."
services=("amebo-postgres" "amebo-instance-1" "amebo-instance-2" "amebo-instance-3" "amebo-loadbalancer")

for service in "${services[@]}"; do
    echo -n "Checking $service... "
    if docker ps --filter "name=$service" --filter "status=running" | grep -q "$service"; then
        echo "✅ Running"
    else
        echo "❌ Not running"
        echo "Check logs with: docker logs $service"
    fi
done

echo ""
echo "🎉 Amebo cluster startup complete!"
echo ""
echo "📊 Service URLs:"
echo "  • Load Balancer: http://localhost"
echo "  • Amebo Instance 1: http://localhost:3311"
echo "  • Amebo Instance 2: http://localhost:3312"
echo "  • Amebo Instance 3: http://localhost:3313"
echo "  • PostgreSQL: localhost:5432"
echo ""
echo "🔧 Management Commands:"
echo "  • View logs: docker-compose logs -f"
echo "  • Stop cluster: ./stop-cluster.sh"
echo "  • Restart cluster: docker-compose restart"
echo "  • Scale instances: docker-compose up -d --scale amebo-1=2"
echo ""
echo "📈 Optional Monitoring (run separately):"
echo "  • Start monitoring: docker-compose -f docker-compose.monitoring.yml up -d"
echo "  • Grafana: http://localhost:3000 (admin/admin)"
echo "  • Prometheus: http://localhost:9090"
