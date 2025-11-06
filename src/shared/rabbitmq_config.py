"""RabbitMQ configuration and queue definitions."""

# Queue names
TRANSCODE_QUEUE = 'transcode_queue'
TRANSCODE_DLQ = 'transcode_dlq'
TRANSCODE_RETRY = 'transcode_retry'

# Exchange names
TRANSCODE_EXCHANGE = 'transcode_exchange'
DLX_EXCHANGE = 'dlx_exchange'

# Queue configurations
QUEUE_CONFIGS = {
    TRANSCODE_QUEUE: {
        'durable': True,
        'arguments': {
            'x-dead-letter-exchange': DLX_EXCHANGE,
            'x-dead-letter-routing-key': TRANSCODE_DLQ,
            'x-message-ttl': 1800000,  # 30 minutes
            'x-max-priority': 10
        }
    },
    TRANSCODE_DLQ: {
        'durable': True,
        'arguments': {
            'x-message-ttl': 604800000,  # 7 days
            'x-max-length': 10000
        }
    },
    TRANSCODE_RETRY: {
        'durable': True,
        'arguments': {
            'x-dead-letter-exchange': TRANSCODE_EXCHANGE,
            'x-dead-letter-routing-key': TRANSCODE_QUEUE,
            'x-message-ttl': 60000  # 1 minute retry delay
        }
    }
}

# Exchange configurations
EXCHANGE_CONFIGS = {
    TRANSCODE_EXCHANGE: {
        'type': 'direct',
        'durable': True
    },
    DLX_EXCHANGE: {
        'type': 'direct',
        'durable': True
    }
}

# Binding configurations
QUEUE_BINDINGS = [
    {
        'queue': TRANSCODE_QUEUE,
        'exchange': TRANSCODE_EXCHANGE,
        'routing_key': TRANSCODE_QUEUE
    },
    {
        'queue': TRANSCODE_DLQ,
        'exchange': DLX_EXCHANGE,
        'routing_key': TRANSCODE_DLQ
    },
    {
        'queue': TRANSCODE_RETRY,
        'exchange': DLX_EXCHANGE,
        'routing_key': TRANSCODE_RETRY
    }
]