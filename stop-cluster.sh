#!/bin/bash

# Amebo Cluster Shutdown Script
# This script stops the Amebo cluster and optionally removes volumes

set -e

echo "🛑 Stopping Amebo Cluster..."

# Parse command line arguments
REMOVE_VOLUMES=false
REMOVE_MONITORING=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --remove-volumes)
            REMOVE_VOLUMES=true
            shift
            ;;
        --remove-monitoring)
            REMOVE_MONITORING=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --remove-volumes    Remove persistent volumes (WARNING: This will delete all data)"
            echo "  --remove-monitoring Remove monitoring stack"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Stop monitoring if requested
if [ "$REMOVE_MONITORING" = true ]; then
    echo "🔍 Stopping monitoring stack..."
    docker-compose -f docker-compose.monitoring.yml down
fi

# Stop main cluster
echo "🏃 Stopping Amebo cluster services..."
if [ "$REMOVE_VOLUMES" = true ]; then
    echo "⚠️  WARNING: Removing volumes will delete all data!"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose down -v
        echo "🗑️  Volumes removed"
    else
        echo "❌ Operation cancelled"
        exit 1
    fi
else
    docker-compose down
fi

echo ""
echo "✅ Amebo cluster stopped successfully!"
echo ""
echo "🔧 Next steps:"
echo "  • Start cluster: ./start-cluster.sh"
echo "  • View remaining containers: docker ps -a"
echo "  • Clean up everything: docker system prune"
