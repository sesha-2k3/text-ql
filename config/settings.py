"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables with sensible defaults.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Keys
    groq_api_key: str = ""

    # Model Configuration
    planner_model: str = "llama-3.3-70b-versatile"
    sql_writer_model: str = "llama-3.3-70b-versatile"

    # Local SQLCoder Configuration via Ollama
    use_local_sqlcoder: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "sqlcoder"

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # SQL Generation Settings
    default_dialect: str = "postgres"
    max_row_limit: int = 50

    # Validation Settings
    placeholder_pattern: str = r"<[A-Z][A-Z0-9_]*>"

    @property
    def forbidden_keywords(self) -> list[str]:
        """SQL keywords that trigger review_required status."""
        return [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "TRUNCATE",
            "ALTER",
            "CREATE",
            "GRANT",
            "REVOKE",
            "EXEC",
            "EXECUTE",
            "MERGE",
            "UPSERT",
        ]

    @property
    def modifying_keywords(self) -> dict[str, str]:
        """Mapping of SQL keywords to warning messages."""
        return {
            "INSERT": "This is an INSERT statement - it will add new data when executed",
            "UPDATE": "This is an UPDATE statement - it will modify existing data when executed. Verify the WHERE clause carefully.",
            "DELETE": "This is a DELETE statement - it will permanently remove data when executed. Verify the WHERE clause carefully.",
            "DROP": "This is a DROP statement - it will permanently delete the entire object and cannot be undone. Ensure you have backups.",
            "TRUNCATE": "This is a TRUNCATE statement - it will permanently delete all data in the table and cannot be undone.",
            "ALTER": "This is an ALTER statement - it will modify the table structure.",
            "CREATE": "This is a CREATE statement - it will create a new database object.",
            "GRANT": "This is a GRANT statement - it will change database permissions.",
            "REVOKE": "This is a REVOKE statement - it will remove database permissions.",
        }


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
