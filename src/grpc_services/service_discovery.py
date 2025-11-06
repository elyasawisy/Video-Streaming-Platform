"""Enhanced Service Discovery module for gRPC Services."""

import os
import json
import time
import logging
from typing import List, Dict, Optional
import redis
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class ServiceNode:
    """Information about a service node."""
    id: str
    host: str
    port: int
    status: str  # active, draining, down
    last_heartbeat: datetime
    metadata: Dict

class ServiceRegistry:
    """Service discovery and health tracking using Redis."""
    
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
        self.service_prefix = "service:"
        self.node_prefix = "node:"
        self.heartbeat_interval = 5  # seconds
        self.node_ttl = 30  # seconds
        
    def register_node(
        self,
        service_name: str,
        node_id: str,
        host: str,
        port: int,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Register a service node."""
        try:
            node_key = f"{self.node_prefix}{service_name}:{node_id}"
            service_key = f"{self.service_prefix}{service_name}"
            
            node_data = {
                "id": node_id,
                "host": host,
                "port": port,
                "status": "active",
                "last_heartbeat": datetime.utcnow().isoformat(),
                "metadata": json.dumps(metadata or {})
            }
            
            # Store node data with TTL
            self.redis.hmset(node_key, node_data)
            self.redis.expire(node_key, self.node_ttl)
            
            # Add to service set
            self.redis.sadd(service_key, node_id)
            
            logger.info(f"Registered node {node_id} for service {service_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error registering node: {e}")
            return False
    
    def deregister_node(self, service_name: str, node_id: str) -> bool:
        """Deregister a service node."""
        try:
            node_key = f"{self.node_prefix}{service_name}:{node_id}"
            service_key = f"{self.service_prefix}{service_name}"
            
            # Remove node data
            self.redis.delete(node_key)
            
            # Remove from service set
            self.redis.srem(service_key, node_id)
            
            logger.info(f"Deregistered node {node_id} from service {service_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error deregistering node: {e}")
            return False
    
    def send_heartbeat(self, service_name: str, node_id: str) -> bool:
        """Send heartbeat for a node."""
        try:
            node_key = f"{self.node_prefix}{service_name}:{node_id}"
            
            # Update last heartbeat
            self.redis.hset(node_key, "last_heartbeat", datetime.utcnow().isoformat())
            self.redis.expire(node_key, self.node_ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")
            return False
    
    def get_service_nodes(self, service_name: str) -> List[ServiceNode]:
        """Get all active nodes for a service."""
        try:
            service_key = f"{self.service_prefix}{service_name}"
            nodes = []
            
            # Get all node IDs for service
            node_ids = self.redis.smembers(service_key)
            
            for node_id in node_ids:
                node_id = node_id.decode() if isinstance(node_id, bytes) else node_id
                node_key = f"{self.node_prefix}{service_name}:{node_id}"
                
                # Get node data
                data = self.redis.hgetall(node_key)
                if not data:
                    continue
                
                # Convert bytes to str
                data = {k.decode(): v.decode() for k, v in data.items()}
                
                nodes.append(ServiceNode(
                    id=data["id"],
                    host=data["host"],
                    port=int(data["port"]),
                    status=data["status"],
                    last_heartbeat=datetime.fromisoformat(data["last_heartbeat"]),
                    metadata=json.loads(data["metadata"])
                ))
            
            return nodes
            
        except Exception as e:
            logger.error(f"Error getting service nodes: {e}")
            return []
    
    def update_node_status(self, service_name: str, node_id: str, status: str) -> bool:
        """Update a node's status."""
        try:
            node_key = f"{self.node_prefix}{service_name}:{node_id}"
            self.redis.hset(node_key, "status", status)
            return True
            
        except Exception as e:
            logger.error(f"Error updating node status: {e}")
            return False
    
    def cleanup_expired_nodes(self, service_name: str) -> int:
        """Remove expired nodes."""
        try:
            service_key = f"{self.service_prefix}{service_name}"
            node_ids = self.redis.smembers(service_key)
            removed = 0
            
            for node_id in node_ids:
                node_id = node_id.decode() if isinstance(node_id, bytes) else node_id
                node_key = f"{self.node_prefix}{service_name}:{node_id}"
                
                # Check if node still exists
                if not self.redis.exists(node_key):
                    self.redis.srem(service_key, node_id)
                    removed += 1
            
            return removed
            
        except Exception as e:
            logger.error(f"Error cleaning up nodes: {e}")
            return 0
    
    def monitor_services(self):
        """Background task to monitor services and cleanup."""
        while True:
            try:
                # Get all services
                services = self.redis.keys(f"{self.service_prefix}*")
                
                for service in services:
                    service_name = service.decode().split(":", 1)[1]
                    removed = self.cleanup_expired_nodes(service_name)
                    if removed > 0:
                        logger.info(f"Removed {removed} expired nodes from {service_name}")
                
            except Exception as e:
                logger.error(f"Error monitoring services: {e}")
            
            time.sleep(self.heartbeat_interval)