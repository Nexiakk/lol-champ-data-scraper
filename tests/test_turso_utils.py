"""
Tests for Turso utilities - error categorization and retry logic.
"""

import pytest
import time
import sys
from unittest.mock import patch, MagicMock

# Mock libsql_experimental before importing turso_utils
sys.modules['libsql_experimental'] = MagicMock()

from scraper.turso_utils import (
    categorize_error,
    is_retryable_error,
    retry_on_stream_error,
    TursoConfig,
)


class TestErrorCategorization:
    """Test error categorization function"""

    def test_connection_errors(self):
        """Test that connection-related errors are categorized correctly"""
        connection_errors = [
            Exception("stream not found: 67c42080:019d3cd0"),
            Exception("Connection refused"),
            Exception("ECONNRESET"),
            Exception("ECONNREFUSED"),
            Exception("Broken pipe"),
            Exception("Network error"),
            Exception("Socket timeout"),
        ]
        
        for error in connection_errors:
            assert categorize_error(error) == 'connection', f"Failed for: {error}"

    def test_transient_errors(self):
        """Test that transient errors are categorized correctly"""
        transient_errors = [
            Exception("Request timeout"),
            Exception("429 Too Many Requests"),
            Exception("503 Service Unavailable"),
            Exception("502 Bad Gateway"),
            Exception("Database busy"),
            Exception("Table locked"),
        ]
        
        for error in transient_errors:
            assert categorize_error(error) == 'transient', f"Failed for: {error}"

    def test_fatal_errors(self):
        """Test that fatal errors are categorized correctly"""
        fatal_errors = [
            Exception("Syntax error in SQL"),
            Exception("Table does not exist"),
            Exception("Permission denied"),
            Exception("Invalid data type"),
        ]
        
        for error in fatal_errors:
            assert categorize_error(error) == 'fatal', f"Failed for: {error}"

    def test_is_retryable_error(self):
        """Test is_retryable_error function"""
        assert is_retryable_error(Exception("stream not found")) is True
        assert is_retryable_error(Exception("timeout")) is True
        assert is_retryable_error(Exception("503")) is True
        assert is_retryable_error(Exception("SQL syntax error")) is False


class TestRetryDecorator:
    """Test retry decorator with exponential backoff"""

    def test_successful_first_attempt(self):
        """Test that successful function returns immediately"""
        call_count = 0
        
        @retry_on_stream_error(max_retries=3, base_delay=0.1)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_on_connection_error(self):
        """Test retry on connection errors"""
        call_count = 0
        
        @retry_on_stream_error(max_retries=3, base_delay=0.01)
        def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("stream not found")
            return "success"
        
        result = failing_then_success()
        assert result == "success"
        assert call_count == 3

    def test_no_retry_on_fatal_error(self):
        """Test that fatal errors are not retried"""
        call_count = 0
        
        @retry_on_stream_error(max_retries=3, base_delay=0.01)
        def fatal_error():
            nonlocal call_count
            call_count += 1
            raise Exception("SQL syntax error")
        
        with pytest.raises(Exception, match="SQL syntax error"):
            fatal_error()
        
        assert call_count == 1  # Should not retry

    def test_max_retries_exceeded(self):
        """Test that function fails after max retries"""
        call_count = 0
        
        @retry_on_stream_error(max_retries=3, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise Exception("stream not found")
        
        with pytest.raises(Exception, match="stream not found"):
            always_fails()
        
        assert call_count == 3  # Should retry 3 times

    def test_exponential_backoff(self):
        """Test that delays increase exponentially"""
        delays = []
        
        @retry_on_stream_error(max_retries=4, base_delay=1.0, jitter_factor=0)
        def track_delays():
            if len(delays) < 3:
                raise Exception("stream not found")
            return "success"
        
        # Patch time.sleep to track delays
        original_sleep = time.sleep
        def mock_sleep(seconds):
            delays.append(seconds)
            # Don't actually sleep in tests
        
        with patch('scraper.turso_utils.time.sleep', mock_sleep):
            track_delays()
        
        # Check exponential growth: 1, 2, 4 (approximately, without jitter)
        assert len(delays) == 3
        assert delays[0] == pytest.approx(1.0, rel=0.1)
        assert delays[1] == pytest.approx(2.0, rel=0.1)
        assert delays[2] == pytest.approx(4.0, rel=0.1)


class TestTursoConfig:
    """Test TursoConfig class"""

    def test_default_values(self):
        """Test default configuration values"""
        config = TursoConfig()
        
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 10.0
        assert config.jitter_factor == 0.5

    def test_custom_values(self):
        """Test custom configuration values"""
        config = TursoConfig(
            db_url="libsql://test.turso.io",
            auth_token="test-token",
            max_retries=5,
            base_delay=2.0,
            max_delay=20.0,
            jitter_factor=0.3
        )
        
        assert config.db_url == "libsql://test.turso.io"
        assert config.auth_token == "test-token"
        assert config.max_retries == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 20.0
        assert config.jitter_factor == 0.3

    @patch.dict('os.environ', {
        'TURSO_DB_URL': 'libsql://env.turso.io',
        'TURSO_AUTH_TOKEN': 'env-token',
        'TURSO_MAX_RETRIES': '5',
        'TURSO_BASE_DELAY': '2.0',
        'TURSO_MAX_DELAY': '15.0',
        'TURSO_JITTER_FACTOR': '0.4'
    })
    def test_from_environment(self):
        """Test configuration from environment variables"""
        config = TursoConfig.from_environment()
        
        assert config.db_url == "libsql://env.turso.io"
        assert config.auth_token == "env-token"
        assert config.max_retries == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 15.0
        assert config.jitter_factor == 0.4


class TestRetryWithTransientErrors:
    """Test retry behavior with transient errors"""

    def test_retry_on_timeout(self):
        """Test retry on timeout errors"""
        call_count = 0
        
        @retry_on_stream_error(max_retries=3, base_delay=0.01)
        def timeout_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Request timeout")
            return "success"
        
        result = timeout_then_success()
        assert result == "success"
        assert call_count == 2

    def test_retry_on_rate_limit(self):
        """Test retry on rate limit errors"""
        call_count = 0
        
        @retry_on_stream_error(max_retries=3, base_delay=0.01)
        def rate_limited_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("429 Too Many Requests")
            return "success"
        
        result = rate_limited_then_success()
        assert result == "success"
        assert call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])