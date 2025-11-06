# PowerShell script for setting up gRPC services with resilience patterns

Write-Host "Setting up gRPC services..."

# Ensure script is run from project root
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$scriptPath\..\.."

# Create directory structure if not exists
New-Item -ItemType Directory -Force -Path "src\grpc_services" | Out-Null

# Install Python gRPC tools and dependencies
Write-Host "Installing dependencies..."
python -m pip install --upgrade pip
python -m pip install -r src/grpc_services/requirements.txt

# Generate Python code from proto file
Write-Host "Generating Python gRPC code..."
python -m grpc_tools.protoc `
    -I./src/grpc_services `
    --python_out=./src/grpc_services `
    --grpc_python_out=./src/grpc_services `
    ./src/grpc_services/video.proto

Write-Host "Generated files:"
Write-Host "   - video_pb2.py (message classes)"
Write-Host "   - video_pb2_grpc.py (service classes)"

# Fix imports
Write-Host "Fixing imports..."
(Get-Content src/grpc_services/video_pb2_grpc.py) `
    -replace 'import video_pb2', 'from . import video_pb2' |
    Set-Content src/grpc_services/video_pb2_grpc.py

Write-Host "`ngRPC setup complete!"
Write-Host "Services available:"
Write-Host "   - Video Service (main service)"
Write-Host "   - Health Check Service (grpc.health.v1.Health)"
Write-Host "   - Metrics (Prometheus /metrics)"
Write-Host ""
Write-Host "To start the gRPC server with metrics and health checks:"
Write-Host "  python src/grpc_services/server.py"
Write-Host ""
Write-Host "The server will start with:"
Write-Host "   - gRPC service on port 50051"
Write-Host "   - Prometheus metrics on :8000/metrics"
Write-Host "   - Health checks via grpc.health.v1.Health"
Write-Host ""
Write-Host "To test the resilient client:"
Write-Host "  python src/grpc_services/client.py"
Write-Host ""
Write-Host "The client includes:"
Write-Host "   - Circuit breaker pattern"
Write-Host "   - Retry with exponential backoff"
Write-Host "   - Request timeouts"
Write-Host "   - Error handling"
Write-Host "   - Metrics collection"