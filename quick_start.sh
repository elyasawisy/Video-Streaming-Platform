# Quick setup and test script for the video streaming platform

set -e  # Exit on error

echo "======================================================================"
echo "Video Streaming Platform - Quick Start"
echo "======================================================================"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check prerequisites
print_info "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi
print_success "Docker found"

if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi
print_success "Docker Compose found"

if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed. Please install Python 3.11+."
    exit 1
fi
print_success "Python 3 found"

# Create directory structure
print_info "Creating directory structure..."
mkdir -p uploads/raw uploads/chunks uploads/transcoded
mkdir -p results benchmarks tests
print_success "Directories created"

# Install Python dependencies
print_info "Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip3 install -r requirements.txt --quiet
    print_success "Python dependencies installed"
else
    print_warning "requirements.txt not found, skipping Python dependencies"
fi

# Generate gRPC code
print_info "Generating gRPC code..."
if [ -f "src/grpc_services/video.proto" ]; then
    python3 -m grpc_tools.protoc \
        -I./src/grpc_services \
        --python_out=./src/grpc_services \
        --grpc_python_out=./src/grpc_services \
        ./src/grpc_services/video.proto
    print_success "gRPC code generated"
else
    print_warning "video.proto not found, skipping gRPC generation"
fi

# Start services
print_info "Starting services with Docker Compose..."
docker-compose up -d

print_success "Services started!"

# Wait for services to be ready
print_info "Waiting for services to be healthy..."
sleep 10

# Check service health
print_info "Checking service health..."

check_service() {
    local service_name=$1
    local health_url=$2
    
    if curl -s -f "$health_url" > /dev/null; then
        print_success "$service_name is healthy"
        return 0
    else
        print_error "$service_name is not responding"
        return 1
    fi
}

check_service "HTTP/2 Upload Service" "http://localhost:8001/health"
check_service "Chunked Upload Service" "http://localhost:8002/health"

# Show running services
print_info "Running services:"
docker-compose ps

echo ""
echo "======================================================================"
echo "✅ Setup Complete!"
echo "======================================================================"
echo ""
echo "📡 Available Services:"
echo "   HTTP/2 Upload:     http://localhost:8001"
echo "   Chunked Upload:    http://localhost:8002"
echo "   PostgreSQL:        localhost:5432"
echo "   RabbitMQ:          localhost:5672"
echo "   RabbitMQ UI:       http://localhost:15672 (guest/guest)"
echo "   Redis:             localhost:6379"
echo ""
echo "🧪 Run Tests:"
echo "   python test_upload_http2.py          # Test HTTP/2 upload"
echo "   python test_upload_chunked.py        # Test chunked upload"
echo "   python compare_uploads.py            # Compare both methods"
echo ""
echo "📊 View Logs:"
echo "   docker-compose logs -f upload_service_http2"
echo "   docker-compose logs -f upload_service_chunked"
echo ""
echo "🛑 Stop Services:"
echo "   docker-compose down"
echo ""
echo "======================================================================"