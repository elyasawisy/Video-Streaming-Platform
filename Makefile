.PHONY: help setup start stop restart logs test clean

help:
	@echo "Video Streaming Platform - Commands"
	@echo ""
	@echo "Setup & Start:"
	@echo "  make setup        - Initial setup (generate proto, install deps)"
	@echo "  make start        - Start all services"
	@echo "  make stop         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo ""
	@echo "Development:"
	@echo "  make logs         - View all logs"
	@echo "  make logs-http2   - View HTTP/2 service logs"
	@echo "  make logs-chunked - View chunked service logs"
	@echo "  make shell-db     - Open PostgreSQL shell"
	@echo ""
	@echo "Testing:"
	@echo "  make test         - Run all tests"
	@echo "  make test-http2   - Test HTTP/2 upload"
	@echo "  make test-chunked - Test chunked upload"
	@echo "  make compare      - Compare both upload methods"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean        - Remove test files and uploads"
	@echo "  make reset        - Stop services and remove volumes"

setup:
	@echo "Setting up project..."
	mkdir -p uploads/raw uploads/chunks uploads/transcoded results benchmarks
	pip install -r requirements.txt
	python -m grpc_tools.protoc \
		-I./src/grpc_services \
		--python_out=./src/grpc_services \
		--grpc_python_out=./src/grpc_services \
		./src/grpc_services/video.proto
	@echo "✅ Setup complete!"

start:
	@echo "Starting services..."
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	sleep 10
	docker-compose ps
	@echo "✅ Services started!"

stop:
	@echo "Stopping services..."
	docker-compose down
	@echo "✅ Services stopped!"

restart:
	@echo "Restarting services..."
	docker-compose restart
	@echo "✅ Services restarted!"

logs:
	docker-compose logs -f

logs-http2:
	docker-compose logs -f upload_service_http2

logs-chunked:
	docker-compose logs -f upload_service_chunked

logs-rabbitmq:
	docker-compose logs -f rabbitmq

shell-db:
	docker-compose exec postgres psql -U videouser -d video_streaming

test:
	@echo "Running all tests..."
	python test_upload_http2.py
	python test_upload_chunked.py
	python compare_uploads.py

test-http2:
	@echo "Testing HTTP/2 upload..."
	python test_upload_http2.py

test-chunked:
	@echo "Testing chunked upload..."
	python test_upload_chunked.py

compare:
	@echo "Comparing upload methods..."
	python compare_uploads.py

clean:
	@echo "Cleaning up test files..."
	rm -f test_*.mp4
	rm -rf uploads/raw/* uploads/chunks/*
	@echo "✅ Cleaned up!"

reset:
	@echo "⚠️  This will delete all data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v; \
		rm -rf uploads/raw/* uploads/chunks/* uploads/transcoded/*; \
		echo "✅ Reset complete!"; \
	fi