"""
Configuration management for the champion scraping system.
Centralizes all configuration settings and provides environment-specific configs.
"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class ScrapingConfig:
    """Configuration for scraping operations"""
    request_timeout: int = 15
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    cache_timeout: int = 3600  # 1 hour

    # Scraping thresholds
    min_pickrate_threshold: float = 9.0  # Minimum pickrate for roles
    patch_viability_days: int = 7  # Days patch must be released to be viable


@dataclass
class LoggingConfig:
    """Configuration for logging"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None


@dataclass
class AppConfig:
    """Main application configuration"""
    scraping: ScrapingConfig = field(default_factory=ScrapingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    environment: str = field(default_factory=lambda: os.environ.get('ENVIRONMENT', 'development'))
    debug: bool = field(default_factory=lambda: os.environ.get('DEBUG', 'false').lower() == 'true')

    @classmethod
    def from_environment(cls) -> 'AppConfig':
        """Create configuration from environment variables"""
        return cls(
            scraping=ScrapingConfig(),
            logging=LoggingConfig(),
            environment=os.environ.get('ENVIRONMENT', 'development'),
            debug=os.environ.get('DEBUG', 'false').lower() == 'true'
        )

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'AppConfig':
        """Create configuration from dictionary"""
        scraping_dict = config_dict.get('scraping', {})
        logging_dict = config_dict.get('logging', {})

        return cls(
            scraping=ScrapingConfig(**scraping_dict),
            logging=LoggingConfig(**logging_dict),
            environment=config_dict.get('environment', 'development'),
            debug=config_dict.get('debug', False)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            'scraping': {
                'request_timeout': self.scraping.request_timeout,
                'rate_limit_delay': self.scraping.rate_limit_delay,
                'max_retries': self.scraping.max_retries,
                'user_agent': self.scraping.user_agent,
                'cache_timeout': self.scraping.cache_timeout,
                'min_pickrate_threshold': self.scraping.min_pickrate_threshold,
                'patch_viability_days': self.scraping.patch_viability_days
            },
            'logging': {
                'level': self.logging.level,
                'format': self.logging.format,
                'file_path': self.logging.file_path
            },
            'environment': self.environment,
            'debug': self.debug
        }


# Global configuration instance
_config = AppConfig.from_environment()

def get_config() -> AppConfig:
    """Get the global application configuration"""
    return _config

def set_config(config: AppConfig):
    """Set the global application configuration"""
    global _config
    _config = config

def load_config_from_file(file_path: str) -> AppConfig:
    """Load configuration from JSON file"""
    import json

    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            config_dict = json.load(f)
            config = AppConfig.from_dict(config_dict)
            set_config(config)
            return config

    # Return default config if file doesn't exist
    return get_config()

def save_config_to_file(config: AppConfig, file_path: str):
    """Save configuration to JSON file"""
    import json

    with open(file_path, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)
