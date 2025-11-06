"""Enhanced RabbitMQ client with improved error handling and retries."""

import json
import time
import logging
from typing import Callable, Optional, Dict, Any
import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError
from . import rabbitmq_config as config

logger = logging.getLogger(__name__)

class RabbitMQClient:
    def __init__(
        self, 
        url: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        heartbeat: int = 600,
        connection_timeout: int = 5
    ):
        """Initialize RabbitMQ client with retry settings."""
        self.url = url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.heartbeat = heartbeat
        self.connection_timeout = connection_timeout
        self.connection = None
        self.channel = None

    def _create_connection(self) -> pika.BlockingConnection:
        """Create a new connection with retry logic."""
        retries = 0
        while retries < self.max_retries:
            try:
                params = pika.URLParameters(self.url)
                params.heartbeat = self.heartbeat
                params.connection_timeout = self.connection_timeout
                return pika.BlockingConnection(params)
            except AMQPConnectionError as e:
                retries += 1
                if retries == self.max_retries:
                    raise
                logger.warning(f"Connection attempt {retries} failed: {e}")
                time.sleep(self.retry_delay * retries)

    def connect(self) -> None:
        """Establish connection and channel, setup exchanges and queues."""
        if self.connection is None or self.connection.is_closed:
            self.connection = self._create_connection()
            self.channel = self.connection.channel()
            self._setup_exchanges()
            self._setup_queues()

    def _setup_exchanges(self) -> None:
        """Declare exchanges based on configuration."""
        for name, conf in config.EXCHANGE_CONFIGS.items():
            self.channel.exchange_declare(
                exchange=name,
                exchange_type=conf['type'],
                durable=conf['durable']
            )

    def _setup_queues(self) -> None:
        """Declare queues and bindings based on configuration."""
        for name, conf in config.QUEUE_CONFIGS.items():
            self.channel.queue_declare(
                queue=name,
                durable=conf['durable'],
                arguments=conf['arguments']
            )

        for binding in config.QUEUE_BINDINGS:
            self.channel.queue_bind(
                queue=binding['queue'],
                exchange=binding['exchange'],
                routing_key=binding['routing_key']
            )

    def ensure_connection(self) -> None:
        """Ensure connection is active, reconnect if needed."""
        if self.connection is None or self.connection.is_closed:
            self.connect()

    def publish(
        self,
        queue: str,
        message: Dict[str, Any],
        priority: int = 0,
        expiration: Optional[str] = None
    ) -> None:
        """Publish message to queue with retry logic."""
        retries = 0
        while retries < self.max_retries:
            try:
                self.ensure_connection()
                self.channel.basic_publish(
                    exchange=config.TRANSCODE_EXCHANGE,
                    routing_key=queue,
                    body=json.dumps(message),
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # persistent
                        content_type='application/json',
                        priority=priority,
                        expiration=expiration
                    )
                )
                return
            except (AMQPConnectionError, AMQPChannelError) as e:
                retries += 1
                if retries == self.max_retries:
                    raise
                logger.warning(f"Publish attempt {retries} failed: {e}")
                self.connection = None  # Force reconnect
                time.sleep(self.retry_delay * retries)

    def consume(
        self,
        queue: str,
        callback: Callable,
        prefetch_count: int = 1,
        auto_ack: bool = False
    ) -> None:
        """Start consuming messages from queue."""
        def wrapped_callback(ch, method, properties, body):
            try:
                message = json.loads(body)
                callback(message)
                if not auto_ack:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                if not auto_ack:
                    # Reject and requeue if within retry limit
                    headers = properties.headers or {}
                    retry_count = headers.get('retry_count', 0)
                    if retry_count < self.max_retries:
                        headers['retry_count'] = retry_count + 1
                        self.channel.basic_publish(
                            exchange='',
                            routing_key=config.TRANSCODE_RETRY,
                            body=body,
                            properties=pika.BasicProperties(
                                delivery_mode=2,
                                headers=headers
                            )
                        )
                    else:
                        # Send to DLQ after max retries
                        self.channel.basic_publish(
                            exchange=config.DLX_EXCHANGE,
                            routing_key=config.TRANSCODE_DLQ,
                            body=body,
                            properties=properties
                        )
                    ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

        self.ensure_connection()
        self.channel.basic_qos(prefetch_count=prefetch_count)
        self.channel.basic_consume(
            queue=queue,
            on_message_callback=wrapped_callback,
            auto_ack=auto_ack
        )
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.channel.stop_consuming()

    def get_queue_info(self, queue: str) -> Dict[str, Any]:
        """Get information about queue status."""
        self.ensure_connection()
        try:
            return self.channel.queue_declare(queue=queue, passive=True)
        except pika.exceptions.ChannelClosedByBroker:
            return None

    def purge_queue(self, queue: str) -> int:
        """Purge all messages from a queue."""
        self.ensure_connection()
        return self.channel.queue_purge(queue=queue).message_count

    def close(self) -> None:
        """Close connection safely."""
        if self.connection and not self.connection.is_closed:
            if self.channel and not self.channel.is_closed:
                self.channel.close()
            self.connection.close()
        self.connection = None
        self.channel = None

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

