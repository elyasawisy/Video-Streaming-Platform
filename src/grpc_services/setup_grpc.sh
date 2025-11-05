# Setup script for gRPC services

echo "Setting up gRPC services..."

# Create directory structure
mkdir -p src/grpc_services

# Install Python gRPC tools
pip install grpcio grpcio-tools

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
echo ""
echo "To start the gRPC server:"
echo "  python src/grpc_services/server.py"
echo ""
echo "To test the client:"
echo "  python src/grpc_services/client.py"