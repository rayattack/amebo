#!/bin/bash

# Amebo Documentation Build Script
# This script builds and serves the documentation locally

set -e

echo "🔨 Building Amebo Documentation..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

# Check if pip is installed
if ! command -v pip &> /dev/null; then
    print_error "pip is not installed. Please install pip first."
    exit 1
fi

# Parse command line arguments
SERVE=false
BUILD_ONLY=false
CLEAN=false
PORT=8000

while [[ $# -gt 0 ]]; do
    case $1 in
        --serve|-s)
            SERVE=true
            shift
            ;;
        --build-only|-b)
            BUILD_ONLY=true
            shift
            ;;
        --clean|-c)
            CLEAN=true
            shift
            ;;
        --port|-p)
            PORT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --serve, -s       Build and serve documentation locally"
            echo "  --build-only, -b  Build documentation without serving"
            echo "  --clean, -c       Clean build directory before building"
            echo "  --port, -p PORT   Port for local server (default: 8000)"
            echo "  --help, -h        Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Clean build directory if requested
if [ "$CLEAN" = true ]; then
    print_status "Cleaning build directory..."
    rm -rf site/
    print_success "Build directory cleaned"
fi

# Check if virtual environment exists
if [ ! -d "venv-docs" ]; then
    print_status "Creating virtual environment for documentation..."
    python3 -m venv venv-docs
    print_success "Virtual environment created"
fi

# Activate virtual environment
print_status "Activating virtual environment..."
source venv-docs/bin/activate

# Install/upgrade documentation dependencies
print_status "Installing documentation dependencies..."
pip install --upgrade pip
pip install -r r.docs.txt

# Validate mkdocs configuration
print_status "Validating MkDocs configuration..."
if ! mkdocs build --help > /dev/null 2>&1; then
    print_error "MkDocs is not properly installed"
    exit 1
fi
print_success "MkDocs configuration is valid"

# Build documentation
print_status "Building documentation..."
if mkdocs build --verbose; then
    print_success "Documentation built successfully"
else
    print_error "Documentation build failed"
    exit 1
fi

# Check if build-only mode
if [ "$BUILD_ONLY" = true ]; then
    print_success "Documentation build complete. Files are in the 'site' directory."
    exit 0
fi

# Serve documentation if requested
if [ "$SERVE" = true ]; then
    print_status "Starting local documentation server on port $PORT..."
    print_success "Documentation available at: http://localhost:$PORT"
    print_warning "Press Ctrl+C to stop the server"
    echo ""
    
    # Start the server
    mkdocs serve --dev-addr="0.0.0.0:$PORT"
else
    print_success "Documentation built successfully!"
    echo ""
    echo "📖 Next steps:"
    echo "  • View locally: ./build-docs.sh --serve"
    echo "  • Deploy to GitHub Pages: git push origin main"
    echo "  • Build only: ./build-docs.sh --build-only"
    echo "  • Clean build: ./build-docs.sh --clean"
fi
