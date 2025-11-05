"""Simple RabbitMQ client wrapper for publishing and consuming."""

import json
import pika

# TODO: pass RABBITMQ_URL and queue/exchange names from service configs
class RabbitMQClient:
    def __init__(self, url: str):
        self.url = url
        self.connection = None
        self.channel = None

    def connect(self):
        params = pika.URLParameters(self.url)
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        return self.channel

    def declare_queue(self, queue: str, durable: bool = True):
        self.channel.queue_declare(queue=queue, durable=durable)

    def publish(self, queue: str, message: dict):
        body = json.dumps(message)
        self.channel.basic_publish(
            exchange='',
            routing_key=queue,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type='application/json'
            ),
        )

    def close(self):
        if self.connection and not self.connection.is_closed:
            self.connection.close()

