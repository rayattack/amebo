#!/bin/bash

# Amebo Cluster Health Check Script
# This script checks the health of all cluster components

set -e

echo "🏥 Amebo Cluster Health Check"
echo "=============================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if a service is running
check_service() {
    local service_name=$1
    local port=$2
    local endpoint=${3:-"/"}
    
    echo -n "Checking $service_name... "
    
    if docker ps --filter "name=$service_name" --filter "status=running" | grep -q "$service_name"; then
        if [ -n "$port" ]; then
            if curl -s -f "http://localhost:$port$endpoint" > /dev/null 2>&1; then
                echo -e "${GREEN}✅ Healthy${NC}"
                return 0
            else
                echo -e "${YELLOW}⚠️  Running but not responding${NC}"
                return 1
            fi
        else
            echo -e "${GREEN}✅ Running${NC}"
            return 0
        fi
    else
        echo -e "${RED}❌ Not running${NC}"
        return 1
    fi
}

# Function to check database connectivity
check_database() {
    echo -n "Checking PostgreSQL connectivity... "
    
    if docker exec amebo-postgres pg_isready -U amebo -d amebo > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Connected${NC}"
        return 0
    else
        echo -e "${RED}❌ Connection failed${NC}"
        return 1
    fi
}

# Function to check load balancer
check_load_balancer() {
    echo -n "Checking Load Balancer... "
    
    if curl -s -f "http://localhost/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Healthy${NC}"
        return 0
    else
        echo -e "${RED}❌ Not responding${NC}"
        return 1
    fi
}

# Main health checks
echo ""
echo "🔍 Infrastructure Services:"
check_service "amebo-postgres" "" ""
check_database

echo ""
echo "🚀 Application Instances:"
check_service "amebo-instance-1" "3311" "/v1/applications"
check_service "amebo-instance-2" "3312" "/v1/applications"
check_service "amebo-instance-3" "3313" "/v1/applications"

echo ""
echo "⚖️  Load Balancer:"
check_service "amebo-loadbalancer" "" ""
check_load_balancer

echo ""
echo "📊 Resource Usage:"
echo "Docker containers:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" | grep amebo

echo ""
echo "💾 Volume Usage:"
docker system df

echo ""
echo "🔗 Network Connectivity Test:"
echo -n "Testing load balancer to instances... "
if curl -s "http://localhost/v1/applications" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Success${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo ""
echo "📋 Summary:"
echo "Run 'docker-compose logs -f' to view detailed logs"
echo "Run 'docker-compose ps' to see service status"
echo "Run './stop-cluster.sh' to stop the cluster"
