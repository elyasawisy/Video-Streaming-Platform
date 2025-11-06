"""Circuit breaker and retry logic for gRPC services."""

import time
import logging
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from threading import Lock
import grpc
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = 'closed'      # Normal operation
    OPEN = 'open'         # Failing, reject requests
    HALF_OPEN = 'half_open'  # Testing recovery

@dataclass
class CircuitConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5  # Number of failures before opening
    success_threshold: int = 2  # Successes needed to close
    timeout: int = 60         # Seconds circuit stays open
    window_size: int = 60     # Rolling window for failure counting
    excluded_errors: List[grpc.StatusCode] = None  # Errors that don't count as failures

@dataclass
class CircuitBreakerMetrics:
    """Circuit breaker metrics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    current_state: CircuitState = CircuitState.CLOSED
    last_failure_time: Optional[datetime] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    failure_timestamps: List[datetime] = None
    avg_response_time: float = 0.0

class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(self, name: str, config: CircuitConfig):
        self.name = name
        self.config = config
        self.state = CircuitState.CLOSED
        self.last_failure = None
        self.metrics = CircuitBreakerMetrics(failure_timestamps=[])
        self.lock = Lock()
        self.excluded_errors = config.excluded_errors or []
        
    def _should_count_failure(self, error: grpc.RpcError) -> bool:
        """Determine if error should count towards failure threshold."""
        if isinstance(error, grpc.RpcError):
            return error.code() not in self.excluded_errors
        return True
    
    def _record_failure(self, error: grpc.RpcError) -> None:
        """Record a failure and potentially open the circuit."""
        with self.lock:
            now = datetime.utcnow()
            self.metrics.failed_requests += 1
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            self.metrics.failure_timestamps.append(now)
            self.metrics.last_failure_time = now
            
            # Remove old failures outside window
            window_start = now - timedelta(seconds=self.config.window_size)
            self.metrics.failure_timestamps = [
                ts for ts in self.metrics.failure_timestamps
                if ts > window_start
            ]
            
            # Check if we should open the circuit
            if (len(self.metrics.failure_timestamps) >= self.config.failure_threshold
                and self.state == CircuitState.CLOSED):
                self.state = CircuitState.OPEN
                self.last_failure = now
                logger.warning(f"Circuit {self.name} opened due to failures")
                self.metrics.current_state = CircuitState.OPEN
    
    def _record_success(self) -> None:
        """Record a success and potentially close the circuit."""
        with self.lock:
            self.metrics.successful_requests += 1
            self.metrics.consecutive_failures = 0
            self.metrics.consecutive_successes += 1
            
            if (self.state == CircuitState.HALF_OPEN and
                self.metrics.consecutive_successes >= self.config.success_threshold):
                self.state = CircuitState.CLOSED
                logger.info(f"Circuit {self.name} closed after success")
                self.metrics.current_state = CircuitState.CLOSED
                self.metrics.failure_timestamps = []
    
    def _check_state_transition(self) -> None:
        """Check if circuit should transition states."""
        with self.lock:
            now = datetime.utcnow()
            
            if (self.state == CircuitState.OPEN and
                self.last_failure and
                (now - self.last_failure).seconds >= self.config.timeout):
                self.state = CircuitState.HALF_OPEN
                logger.info(f"Circuit {self.name} entering half-open state")
                self.metrics.current_state = CircuitState.HALF_OPEN
    
    def get_metrics(self) -> CircuitBreakerMetrics:
        """Get current circuit breaker metrics."""
        with self.lock:
            return self.metrics
    
    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator for protecting gRPC calls."""
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            self._check_state_transition()
            
            if self.state == CircuitState.OPEN:
                self.metrics.rejected_requests += 1
                raise grpc.RpcError(
                    'Circuit breaker is OPEN. Too many recent failures.'
                )
            
            try:
                start_time = time.time()
                self.metrics.total_requests += 1
                
                result = func(*args, **kwargs)
                
                # Update response time metrics
                duration = time.time() - start_time
                self.metrics.avg_response_time = (
                    (self.metrics.avg_response_time * (self.metrics.total_requests - 1) + duration)
                    / self.metrics.total_requests
                )
                
                self._record_success()
                return result
                
            except grpc.RpcError as e:
                if self._should_count_failure(e):
                    self._record_failure(e)
                raise
            
        return wrapper

class RetryConfig:
    """Configuration for retry behavior."""
    def __init__(
        self,
        max_attempts: int = 3,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        backoff_multiplier: float = 2.0,
        retryable_status_codes: List[grpc.StatusCode] = None
    ):
        self.max_attempts = max_attempts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier
        self.retryable_status_codes = retryable_status_codes or [
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.RESOURCE_EXHAUSTED
        ]

def retry_on_error(config: RetryConfig):
    """Decorator for retrying failed gRPC calls."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            backoff = config.initial_backoff
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except grpc.RpcError as e:
                    last_exception = e
                    
                    # Check if error is retryable
                    if e.code() not in config.retryable_status_codes:
                        raise
                    
                    if attempt < config.max_attempts - 1:
                        logger.warning(
                            f"Attempt {attempt + 1}/{config.max_attempts} failed: {e.code()}. "
                            f"Retrying in {backoff:.1f}s"
                        )
                        time.sleep(backoff)
                        backoff = min(
                            backoff * config.backoff_multiplier,
                            config.max_backoff
                        )
            
            raise last_exception
        
        return wrapper
    return decorator

class GrpcClientWrapper:
    """Wrapper for gRPC clients with circuit breaker and retry logic."""
    
    def __init__(
        self,
        service_name: str,
        circuit_config: Optional[CircuitConfig] = None,
        retry_config: Optional[RetryConfig] = None
    ):
        self.service_name = service_name
        self.circuit = CircuitBreaker(
            service_name,
            circuit_config or CircuitConfig()
        )
        self.retry_config = retry_config or RetryConfig()
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Make a gRPC call with circuit breaker and retry logic."""
        @self.circuit
        @retry_on_error(self.retry_config)
        def wrapped_call():
            return func(*args, **kwargs)
        
        return wrapped_call()