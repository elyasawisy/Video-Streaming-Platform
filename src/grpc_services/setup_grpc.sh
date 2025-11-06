# Setup script for gRPC services with resilience patterns

echo "Setting up gRPC services..."



# Install Python gRPC tools and dependencies
pip install grpcio grpcio-tools
pip install -r src/grpc_services/requirements.txt

# Generate Python code from proto file
echo "Generating Python gRPC code..."
python -m grpc_tools.protoc \
    -I./src/grpc_services \
    --python_out=./src/grpc_services \
    --grpc_python_out=./src/grpc_services \
    ./src/grpc_services/video.proto

echo "Generated files:"
echo "   - video_pb2.py (message classes)"
echo "   - video_pb2_grpc.py (service classes)"

# Fix import issues in generated files
echo "Fixing imports..."
sed -i 's/import video_pb2/from . import video_pb2/' src/grpc_services/video_pb2_grpc.py

echo "gRPC setup complete!"
echo "Services available:"
echo "   - Video Service (main service)"
echo "   - Health Check Service (grpc.health.v1.Health)"
echo "   - Metrics (Prometheus /metrics)"
echo ""
echo "To start the gRPC server with metrics and health checks:"
echo "  python src/grpc_services/server.py"
echo ""
echo "The server will start with:"
echo "   - gRPC service on port 50051"
echo "   - Prometheus metrics on :8000/metrics"
echo "   - Health checks via grpc.health.v1.Health"
echo ""
echo "To test the resilient client:"
echo "  python src/grpc_services/client.py"
echo ""
echo "The client includes:"
echo "   - Circuit breaker pattern"
echo "   - Retry with exponential backoff"
echo "   - Request timeouts"
echo "   - Error handling"
echo "   - Metrics collection"