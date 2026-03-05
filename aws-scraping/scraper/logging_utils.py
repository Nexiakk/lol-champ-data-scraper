"""
Logging utilities for the champion scraping system.
Provides structured logging with proper configuration and formatting.
"""

import logging
import logging.handlers
import sys
from typing import Optional
from .config import get_config


class ScrapingLogger:
    """Centralized logger for the scraping system"""

    def __init__(self, name: str = "champion_scraper"):
        self.logger = logging.getLogger(name)
        self._configured = False

    def configure(self, config=None):
        """Configure logging based on config"""
        if self._configured:
            return

        if config is None:
            config = get_config()

        # Clear existing handlers
        self.logger.handlers.clear()

        # Set level
        level = getattr(logging, config.logging.level.upper(), logging.INFO)
        self.logger.setLevel(level)

        # Create formatter
        formatter = logging.Formatter(config.logging.format)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File handler (if specified)
        if config.logging.file_path:
            file_handler = logging.handlers.RotatingFileHandler(
                config.logging.file_path,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self._configured = True

    def get_logger(self) -> logging.Logger:
        """Get the configured logger"""
        if not self._configured:
            self.configure()
        return self.logger


# Global logger instance
_logger = ScrapingLogger()

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance"""
    if name:
        return _logger.get_logger().getChild(name)
    return _logger.get_logger()

def log_scraping_start(champion: str, operation: str):
    """Log the start of a scraping operation"""
    logger = get_logger()
    logger.info(f"🔄 Starting {operation} for {champion}")

def log_scraping_success(champion: str, operation: str, details: Optional[str] = None):
    """Log successful completion of scraping operation"""
    logger = get_logger()
    message = f"✅ {operation} completed for {champion}"
    if details:
        message += f" ({details})"
    logger.info(message)

def log_scraping_error(champion: str, operation: str, error: Exception):
    """Log error during scraping operation"""
    logger = get_logger()
    logger.error(f"❌ {operation} failed for {champion}: {str(error)}")

def log_rate_limiting(delay: float):
    """Log rate limiting"""
    logger = get_logger()
    logger.debug(f"⏱️ Rate limiting: waiting {delay:.1f}s")

def log_patch_info(patch: str, viability_days: Optional[int] = None):
    """Log patch information"""
    logger = get_logger()
    message = f"📦 Using patch {patch}"
    if viability_days is not None:
        message += f" (viable for {viability_days} days)"
    logger.info(message)



# Convenience functions for backward compatibility
def info(message: str):
    """Log info message"""
    get_logger().info(message)

def error(message: str):
    """Log error message"""
    get_logger().error(message)

def warning(message: str):
    """Log warning message"""
    get_logger().warning(message)

def debug(message: str):
    """Log debug message"""
    get_logger().debug(message)
