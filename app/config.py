"""
Конфигурация приложения
"""
import json
from typing import List
from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Bot settings
    bot_token: str = Field(..., alias="BOT_TOKEN")
    bot_username: str = Field("", alias="BOT_USERNAME")
    
    # Admin settings
    admin_user_ids: str = Field("[]", alias="ADMIN_USER_IDS")
    
    # Database settings
    postgres_host: str = Field("localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("botdb", alias="POSTGRES_DB")
    postgres_user: str = Field("botuser", alias="POSTGRES_USER")
    postgres_password: str = Field("", alias="POSTGRES_PASSWORD")
    
    # Redis settings
    redis_host: str = Field("localhost", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")
    redis_db: int = Field(0, alias="REDIS_DB")
    redis_password: str = Field("", alias="REDIS_PASSWORD")
    
    # Environment
    env: str = Field("development", alias="ENV")
    
    # Logging
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Local Bot API settings
    use_local_api: bool = Field(False, alias="USE_LOCAL_API")
    telegram_api_id: str = Field("", alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field("", alias="TELEGRAM_API_HASH")
    local_api_host: str = Field("telegram-bot-api", alias="LOCAL_API_HOST")
    local_api_port: int = Field(8081, alias="LOCAL_API_PORT")

    # AI providers (Telegram Business mode)
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field("claude-sonnet-4-5-20250929", alias="CLAUDE_MODEL")
    deepseek_api_key: str = Field("", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field("https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    enable_prompt_cache: bool = Field(True, alias="ENABLE_PROMPT_CACHE")

    # Контекст-бюджет
    max_context_tokens: int = Field(100000, alias="MAX_CONTEXT_TOKENS")
    max_knowledge_tokens: int = Field(50000, alias="MAX_KNOWLEDGE_TOKENS")
    max_history_messages: int = Field(20, alias="MAX_HISTORY_MESSAGES")
    context_reserve_tokens: int = Field(4096, alias="CONTEXT_RESERVE_TOKENS")

    # Имитация живого ответа
    human_response_enabled: bool = Field(True, alias="HUMAN_RESPONSE_ENABLED")
    min_response_delay: float = Field(15.0, alias="MIN_RESPONSE_DELAY")
    max_response_delay: float = Field(25.0, alias="MAX_RESPONSE_DELAY")
    typing_chars_per_second: float = Field(40.0, alias="TYPING_CHARS_PER_SECOND")
    typing_min_duration: float = Field(3.0, alias="TYPING_MIN_DURATION")
    typing_max_duration: float = Field(60.0, alias="TYPING_MAX_DURATION")

    # Follow-up планировщик
    followup_enabled: bool = Field(True, alias="FOLLOWUP_ENABLED")
    followup_check_interval: int = Field(60, alias="FOLLOWUP_CHECK_INTERVAL")
    followup_delay_minutes: int = Field(60, alias="FOLLOWUP_DELAY_MINUTES")
    followup_max_count: int = Field(1, alias="FOLLOWUP_MAX_COUNT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @validator('admin_user_ids')
    def parse_admin_ids(cls, v):
        """Парсим список админов из JSON"""
        if isinstance(v, str):
            try:
                # Пробуем парсить как JSON
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [int(user_id) for user_id in parsed]
                else:
                    # Если не список, то пробуем как строку через запятую
                    return [int(x.strip()) for x in v.split(',') if x.strip()]
            except (json.JSONDecodeError, ValueError):
                # Если не получается, пробуем как строку через запятую
                return [int(x.strip()) for x in v.split(',') if x.strip()]
        return v
    
    @property
    def database_url(self) -> str:
        """Формирование URL для подключения к базе данных"""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def redis_url(self) -> str:
        """Формирование URL для подключения к Redis"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь админом"""
        return user_id in self.admin_user_ids

    @property
    def local_api_url(self) -> str:
        """URL для подключения к Local Bot API Server"""
        return f"http://{self.local_api_host}:{self.local_api_port}"

    @property
    def file_upload_limit_mb(self) -> int:
        """Лимит загрузки файлов в MB"""
        return 2000 if self.use_local_api else 50

    @property
    def file_download_limit_mb(self) -> int:
        """Лимит скачивания файлов в MB"""
        return 2000 if self.use_local_api else 20

    @property
    def api_mode_name(self) -> str:
        """Человекочитаемое название режима API"""
        return "Local Bot API" if self.use_local_api else "Public Bot API"


# Создаем глобальный экземпляр настроек
settings = Settings()
