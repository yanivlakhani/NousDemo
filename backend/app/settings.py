from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_agent_id: str | None = None
    elevenlabs_phone_number_id: str | None = None
    elevenlabs_webhook_secret: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"
    demo_capacity_slot_minutes: int | None = None
    demo_capacity_horizon_days: int = 28
    use_fake_voice: bool = True


settings = Settings()
