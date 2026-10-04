"""BUDDY Typed Configuration Subsystem.

Provides typed, environment-driven configuration schema, validation rules,
and safe serialization with automatic secret masking.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError
from app.core.logging import REDACTED_MASK

AppEnvType = Literal["development", "production", "testing", "staging"]
LogLevelType = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class BuddyConfig(BaseSettings):
    """Strongly typed application configuration model for BUDDY."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core Runtime Settings
    app_env: AppEnvType = Field(
        default="development",
        validation_alias="APP_ENV",
    )
    log_level: LogLevelType = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    buddy_name: str = Field(
        default="BUDDY",
        validation_alias="BUDDY_NAME",
    )
    data_dir: Path = Field(
        default=Path("data"),
        validation_alias="DATA_DIR",
    )

    # AI Configuration (Loop 3)
    ai_provider: str = Field(
        default="mock",
        validation_alias="AI_PROVIDER",
    )
    ai_model: str = Field(
        default="gpt-4o-mini",
        validation_alias="AI_MODEL",
    )
    ai_api_key: Optional[str] = Field(
        default=None,
        validation_alias="AI_API_KEY",
    )
    ai_base_url: Optional[str] = Field(
        default="https://api.openai.com/v1",
        validation_alias="AI_BASE_URL",
    )
    ai_temperature: float = Field(
        default=0.7,
        validation_alias="AI_TEMPERATURE",
    )
    ai_max_tokens: int = Field(
        default=1024,
        validation_alias="AI_MAX_TOKENS",
    )
    ai_timeout: float = Field(
        default=30.0,
        validation_alias="AI_TIMEOUT",
    )
    ai_max_retries: int = Field(
        default=2,
        validation_alias="AI_MAX_RETRIES",
    )
    conversation_max_messages: int = Field(
        default=20,
        validation_alias="CONVERSATION_MAX_MESSAGES",
    )
    stt_provider: str = Field(
        default="mock",
        validation_alias="STT_PROVIDER",
    )
    tts_provider: str = Field(
        default="mock",
        validation_alias="TTS_PROVIDER",
    )
    database_path: Path = Field(
        default=Path("data/buddy.db"),
        validation_alias="DATABASE_PATH",
    )
    audit_log_path: Path = Field(
        default=Path("data/audit.log"),
        validation_alias="AUDIT_LOG_PATH",
    )
    master_key_storage: str = Field(
        default="keyring",
        validation_alias="MASTER_KEY_STORAGE",
    )
    wake_word: str = Field(
        default="hey buddy",
        validation_alias="WAKE_WORD",
    )
    # Tool Execution Settings (Loop 4)
    tools_enabled: bool = Field(
        default=True,
        validation_alias="TOOLS_ENABLED",
    )
    tools_timeout: float = Field(
        default=10.0,
        validation_alias="TOOLS_TIMEOUT",
    )
    tools_max_per_turn: int = Field(
        default=5,
        validation_alias="TOOLS_MAX_PER_TURN",
    )
    tools_require_confirmation: bool = Field(
        default=True,
        validation_alias="TOOLS_REQUIRE_CONFIRMATION",
    )
    # Voice Pipeline Settings (Loop 2)
    voice_enabled: bool = Field(
        default=True,
        validation_alias="VOICE_ENABLED",
    )
    audio_input_device: str = Field(
        default="default",
        validation_alias="AUDIO_INPUT_DEVICE",
    )
    audio_output_device: str = Field(
        default="default",
        validation_alias="AUDIO_OUTPUT_DEVICE",
    )
    audio_sample_rate: int = Field(
        default=16000,
        validation_alias="AUDIO_SAMPLE_RATE",
    )
    audio_channels: int = Field(
        default=1,
        validation_alias="AUDIO_CHANNELS",
    )
    voice_timeout: float = Field(
        default=10.0,
        validation_alias="VOICE_TIMEOUT",
    )
    vad_silence_timeout: float = Field(
        default=1.5,
        validation_alias="VAD_SILENCE_TIMEOUT",
    )
    log_transcripts: bool = Field(
        default=False,
        validation_alias="LOG_TRANSCRIPTS",
    )

    # Memory & Contextual Personalization Settings (Loop 8)
    memory_enabled: bool = Field(
        default=True,
        validation_alias="MEMORY_ENABLED",
    )
    memory_database_path: Path = Field(
        default=Path("data/memory.db"),
        validation_alias="MEMORY_DATABASE_PATH",
    )
    memory_encryption_enabled: bool = Field(
        default=False,
        validation_alias="MEMORY_ENCRYPTION_ENABLED",
    )
    memory_encryption_key: Optional[str] = Field(
        default=None,
        validation_alias="MEMORY_ENCRYPTION_KEY",
    )
    memory_max_size_mb: int = Field(
        default=50,
        validation_alias="MEMORY_MAX_SIZE_MB",
    )
    memory_max_records: int = Field(
        default=1000,
        validation_alias="MEMORY_MAX_RECORDS",
    )
    memory_max_context_records: int = Field(
        default=10,
        validation_alias="MEMORY_MAX_CONTEXT_RECORDS",
    )
    memory_max_context_tokens: int = Field(
        default=2000,
        validation_alias="MEMORY_MAX_CONTEXT_TOKENS",
    )
    memory_session_ttl_seconds: float = Field(
        default=3600.0,
        validation_alias="MEMORY_SESSION_TTL_SECONDS",
    )
    memory_episodic_ttl_days: int = Field(
        default=30,
        validation_alias="MEMORY_EPISODIC_TTL_DAYS",
    )
    memory_inferred_ttl_days: int = Field(
        default=7,
        validation_alias="MEMORY_INFERRED_TTL_DAYS",
    )
    memory_require_confirmation: bool = Field(
        default=True,
        validation_alias="MEMORY_REQUIRE_CONFIRMATION",
    )
    memory_secret_detection_enabled: bool = Field(
        default=True,
        validation_alias="MEMORY_SECRET_DETECTION_ENABLED",
    )

    # Browser Automation Settings (Loop 9)
    browser_enabled: bool = Field(
        default=True,
        validation_alias="BROWSER_ENABLED",
    )
    browser_engine: str = Field(
        default="chromium",
        validation_alias="BROWSER_ENGINE",
    )
    browser_headless: bool = Field(
        default=True,
        validation_alias="BROWSER_HEADLESS",
    )
    browser_session_timeout_seconds: float = Field(
        default=300.0,
        validation_alias="BROWSER_SESSION_TIMEOUT_SECONDS",
    )
    browser_action_timeout_seconds: float = Field(
        default=15.0,
        validation_alias="BROWSER_ACTION_TIMEOUT_SECONDS",
    )
    browser_navigation_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="BROWSER_NAVIGATION_TIMEOUT_SECONDS",
    )
    browser_max_tabs: int = Field(
        default=5,
        validation_alias="BROWSER_MAX_TABS",
    )
    browser_max_actions: int = Field(
        default=50,
        validation_alias="BROWSER_MAX_ACTIONS",
    )
    browser_max_download_size_mb: int = Field(
        default=25,
        validation_alias="BROWSER_MAX_DOWNLOAD_SIZE_MB",
    )
    browser_max_upload_size_mb: int = Field(
        default=10,
        validation_alias="BROWSER_MAX_UPLOAD_SIZE_MB",
    )
    browser_max_page_text_chars: int = Field(
        default=20000,
        validation_alias="BROWSER_MAX_PAGE_TEXT_CHARS",
    )
    browser_max_dom_nodes: int = Field(
        default=500,
        validation_alias="BROWSER_MAX_DOM_NODES",
    )
    max_dom_nodes: int = Field(
        default=500,
        validation_alias="MAX_DOM_NODES",
    )
    max_accessibility_nodes: int = Field(
        default=300,
        validation_alias="MAX_ACCESSIBILITY_NODES",
    )
    max_navigation_redirects: int = Field(
        default=5,
        validation_alias="MAX_NAVIGATION_REDIRECTS",
    )
    max_browser_session_duration: float = Field(
        default=300.0,
        validation_alias="MAX_BROWSER_SESSION_DURATION",
    )
    max_browser_action_timeout: float = Field(
        default=15.0,
        validation_alias="MAX_BROWSER_ACTION_TIMEOUT",
    )
    max_browser_tabs: int = Field(
        default=5,
        validation_alias="MAX_BROWSER_TABS",
    )
    max_browser_actions_per_task: int = Field(
        default=50,
        validation_alias="MAX_BROWSER_ACTIONS_PER_TASK",
    )
    max_browser_download_size_mb: int = Field(
        default=25,
        validation_alias="MAX_BROWSER_DOWNLOAD_SIZE_MB",
    )
    max_browser_upload_size_mb: int = Field(
        default=10,
        validation_alias="MAX_BROWSER_UPLOAD_SIZE_MB",
    )
    max_page_text_chars: int = Field(
        default=20000,
        validation_alias="MAX_PAGE_TEXT_CHARS",
    )
    browser_min_target_confidence: float = Field(
        default=0.85,
        validation_alias="BROWSER_MIN_TARGET_CONFIDENCE",
    )
    browser_allow_localhost: bool = Field(
        default=False,
        validation_alias="BROWSER_ALLOW_LOCALHOST",
    )
    browser_allow_private_networks: bool = Field(
        default=False,
        validation_alias="BROWSER_ALLOW_PRIVATE_NETWORKS",
    )
    browser_allowed_domains: List[str] = Field(
        default_factory=list,
        validation_alias="BROWSER_ALLOWED_DOMAINS",
    )
    browser_blocked_domains: List[str] = Field(
        default_factory=list,
        validation_alias="BROWSER_BLOCKED_DOMAINS",
    )
    browser_screenshot_enabled: bool = Field(
        default=True,
        validation_alias="BROWSER_SCREENSHOT_ENABLED",
    )
    browser_download_dir: Path = Field(
        default=Path("data/downloads"),
        validation_alias="BROWSER_DOWNLOAD_DIR",
    )

    @classmethod
    def load_from_env(cls, env_file: Optional[str] = None) -> BuddyConfig:
        """Load configuration respecting BUDDY_ prefixed fallbacks and explicit env file."""
        # Handle dual naming (BUDDY_ENV -> APP_ENV, BUDDY_LOG_LEVEL -> LOG_LEVEL, etc.)
        env_overrides: Dict[str, Any] = {}

        alias_map = {
            "BUDDY_ENV": "APP_ENV",
            "BUDDY_LOG_LEVEL": "LOG_LEVEL",
            "BUDDY_DATA_DIR": "DATA_DIR",
            "BUDDY_AI_PROVIDER": "AI_PROVIDER",
            "BUDDY_AI_MODEL": "AI_MODEL",
            "BUDDY_AI_API_KEY": "AI_API_KEY",
            "OPENAI_API_KEY": "AI_API_KEY",
            "BUDDY_AI_BASE_URL": "AI_BASE_URL",
            "BUDDY_AI_TEMPERATURE": "AI_TEMPERATURE",
            "BUDDY_AI_MAX_TOKENS": "AI_MAX_TOKENS",
            "BUDDY_AI_TIMEOUT": "AI_TIMEOUT",
            "BUDDY_AI_MAX_RETRIES": "AI_MAX_RETRIES",
            "BUDDY_CONVERSATION_MAX_MESSAGES": "CONVERSATION_MAX_MESSAGES",
            "BUDDY_STT_PROVIDER": "STT_PROVIDER",
            "BUDDY_TTS_PROVIDER": "TTS_PROVIDER",
            "BUDDY_DATABASE_PATH": "DATABASE_PATH",
            "BUDDY_AUDIT_LOG_PATH": "AUDIT_LOG_PATH",
            "BUDDY_MASTER_KEY_STORAGE": "MASTER_KEY_STORAGE",
            "BUDDY_WAKE_WORD": "WAKE_WORD",
            "BUDDY_TOOLS_ENABLED": "TOOLS_ENABLED",
            "BUDDY_TOOLS_TIMEOUT": "TOOLS_TIMEOUT",
            "BUDDY_TOOLS_MAX_PER_TURN": "TOOLS_MAX_PER_TURN",
            "BUDDY_TOOLS_REQUIRE_CONFIRMATION": "TOOLS_REQUIRE_CONFIRMATION",
            "BUDDY_VOICE_ENABLED": "VOICE_ENABLED",
            "BUDDY_AUDIO_INPUT_DEVICE": "AUDIO_INPUT_DEVICE",
            "BUDDY_AUDIO_OUTPUT_DEVICE": "AUDIO_OUTPUT_DEVICE",
            "BUDDY_AUDIO_SAMPLE_RATE": "AUDIO_SAMPLE_RATE",
            "BUDDY_AUDIO_CHANNELS": "AUDIO_CHANNELS",
            "BUDDY_VOICE_TIMEOUT": "VOICE_TIMEOUT",
            "BUDDY_VAD_SILENCE_TIMEOUT": "VAD_SILENCE_TIMEOUT",
            "BUDDY_LOG_TRANSCRIPTS": "LOG_TRANSCRIPTS",
            "BUDDY_MEMORY_ENABLED": "MEMORY_ENABLED",
            "BUDDY_MEMORY_DATABASE_PATH": "MEMORY_DATABASE_PATH",
            "BUDDY_MEMORY_ENCRYPTION_ENABLED": "MEMORY_ENCRYPTION_ENABLED",
            "BUDDY_MEMORY_ENCRYPTION_KEY": "MEMORY_ENCRYPTION_KEY",
            "BUDDY_MEMORY_MAX_SIZE_MB": "MEMORY_MAX_SIZE_MB",
            "BUDDY_MEMORY_MAX_RECORDS": "MEMORY_MAX_RECORDS",
            "BUDDY_MEMORY_MAX_CONTEXT_RECORDS": "MEMORY_MAX_CONTEXT_RECORDS",
            "BUDDY_MEMORY_MAX_CONTEXT_TOKENS": "MEMORY_MAX_CONTEXT_TOKENS",
            "BUDDY_MEMORY_SESSION_TTL_SECONDS": "MEMORY_SESSION_TTL_SECONDS",
            "BUDDY_MEMORY_EPISODIC_TTL_DAYS": "MEMORY_EPISODIC_TTL_DAYS",
            "BUDDY_MEMORY_INFERRED_TTL_DAYS": "MEMORY_INFERRED_TTL_DAYS",
            "BUDDY_MEMORY_REQUIRE_CONFIRMATION": "MEMORY_REQUIRE_CONFIRMATION",
            "BUDDY_MEMORY_SECRET_DETECTION_ENABLED": "MEMORY_SECRET_DETECTION_ENABLED",
            "BUDDY_BROWSER_ENABLED": "BROWSER_ENABLED",
            "BUDDY_BROWSER_ENGINE": "BROWSER_ENGINE",
            "BUDDY_BROWSER_HEADLESS": "BROWSER_HEADLESS",
            "BUDDY_BROWSER_SESSION_TIMEOUT_SECONDS": "BROWSER_SESSION_TIMEOUT_SECONDS",
            "BUDDY_BROWSER_ACTION_TIMEOUT_SECONDS": "BROWSER_ACTION_TIMEOUT_SECONDS",
            "BUDDY_BROWSER_NAVIGATION_TIMEOUT_SECONDS": "BROWSER_NAVIGATION_TIMEOUT_SECONDS",
            "BUDDY_BROWSER_MAX_TABS": "BROWSER_MAX_TABS",
            "BUDDY_BROWSER_MAX_ACTIONS": "BROWSER_MAX_ACTIONS",
            "BUDDY_BROWSER_MAX_DOWNLOAD_SIZE_MB": "BROWSER_MAX_DOWNLOAD_SIZE_MB",
            "BUDDY_BROWSER_MAX_UPLOAD_SIZE_MB": "BROWSER_MAX_UPLOAD_SIZE_MB",
            "BUDDY_BROWSER_MAX_PAGE_TEXT_CHARS": "BROWSER_MAX_PAGE_TEXT_CHARS",
            "BUDDY_BROWSER_MAX_DOM_NODES": "BROWSER_MAX_DOM_NODES",
            "BUDDY_BROWSER_MIN_TARGET_CONFIDENCE": "BROWSER_MIN_TARGET_CONFIDENCE",
            "BUDDY_BROWSER_ALLOW_LOCALHOST": "BROWSER_ALLOW_LOCALHOST",
            "BUDDY_BROWSER_ALLOW_PRIVATE_NETWORKS": "BROWSER_ALLOW_PRIVATE_NETWORKS",
            "BUDDY_BROWSER_ALLOWED_DOMAINS": "BROWSER_ALLOWED_DOMAINS",
            "BUDDY_BROWSER_BLOCKED_DOMAINS": "BROWSER_BLOCKED_DOMAINS",
            "BUDDY_BROWSER_SCREENSHOT_ENABLED": "BROWSER_SCREENSHOT_ENABLED",
            "BUDDY_BROWSER_DOWNLOAD_DIR": "BROWSER_DOWNLOAD_DIR",
            "BUDDY_MAX_DOM_NODES": "MAX_DOM_NODES",
            "BUDDY_MAX_ACCESSIBILITY_NODES": "MAX_ACCESSIBILITY_NODES",
            "BUDDY_MAX_NAVIGATION_REDIRECTS": "MAX_NAVIGATION_REDIRECTS",
            "BUDDY_MAX_BROWSER_SESSION_DURATION": "MAX_BROWSER_SESSION_DURATION",
            "BUDDY_MAX_BROWSER_ACTION_TIMEOUT": "MAX_BROWSER_ACTION_TIMEOUT",
            "BUDDY_MAX_BROWSER_TABS": "MAX_BROWSER_TABS",
            "BUDDY_MAX_BROWSER_ACTIONS_PER_TASK": "MAX_BROWSER_ACTIONS_PER_TASK",
            "BUDDY_MAX_BROWSER_DOWNLOAD_SIZE_MB": "MAX_BROWSER_DOWNLOAD_SIZE_MB",
            "BUDDY_MAX_BROWSER_UPLOAD_SIZE_MB": "MAX_BROWSER_UPLOAD_SIZE_MB",
            "BUDDY_MAX_PAGE_TEXT_CHARS": "MAX_PAGE_TEXT_CHARS",
        }

        for buddy_var, core_var in alias_map.items():
            if buddy_var in os.environ and core_var not in os.environ:
                env_overrides[core_var] = os.environ[buddy_var]

        try:
            if env_file:
                return cls(_env_file=env_file, **env_overrides)
            return cls(**env_overrides)
        except Exception as e:
            raise ConfigurationError(f"Failed to load or validate configuration: {e}") from e

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, v: Any) -> str:
        if isinstance(v, str):
            upper = v.upper().strip()
            if upper in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                return upper
        raise ValueError(f"Invalid log level: {v}. Must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, v: Any) -> str:
        if isinstance(v, str):
            lower = v.lower().strip()
            if lower in ("development", "production", "testing", "staging"):
                return lower
        raise ValueError(f"Invalid app environment: {v}. Must be development, production, testing, or staging.")

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize configuration with all credentials, keys, and tokens redacted."""
        raw = self.model_dump()
        safe: Dict[str, Any] = {}

        sensitive_keywords: Set[str] = {
            "key",
            "secret",
            "password",
            "token",
            "salt",
            "pin",
            "credential",
            "auth",
        }

        for k, v in raw.items():
            is_sensitive = any(kw in k.lower() for kw in sensitive_keywords)
            if is_sensitive and v is not None:
                safe[k] = REDACTED_MASK
            elif isinstance(v, Path):
                safe[k] = str(v)
            else:
                safe[k] = v

        return safe


BuddyConfig.model_rebuild()
