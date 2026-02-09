import os
from typing import Optional

from pydantic import BaseModel


class Settings(BaseModel):
    environment: str = os.getenv("ENVIRONMENT", "development")
    http_base_url: str = os.getenv("HTTP_BASE_URL", "http://localhost:8000")
    ws_base_url: str = os.getenv("WS_BASE_URL", "ws://localhost:8000")
    backend_base_url: str = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
    livekit_url: Optional[str] = os.getenv("LIVEKIT_URL")
    livekit_api_key: Optional[str] = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret: Optional[str] = os.getenv("LIVEKIT_API_SECRET")
    livekit_agent_name: str = os.getenv("LIVEKIT_AGENT_NAME", "voice-agent")
    supabase_url: Optional[str] = os.getenv("SUPABASE_URL")
    supabase_key: Optional[str] = os.getenv("SUPABASE_KEY")
    openrouter_api_key: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    openai_api_base: str = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    deepgram_api_key: Optional[str] = os.getenv("DEEPGRAM_API_KEY")
    cartesia_api_key: Optional[str] = os.getenv("CARTESIA_API_KEY")
    beyond_presence_api_key: Optional[str] = os.getenv("BEYOND_PRESENCE_API_KEY")
    bey_api_key: Optional[str] = os.getenv("BEY_API_KEY")
    bey_avatar_id: Optional[str] = os.getenv("BEY_AVATAR_ID")
    bey_enabled: bool = os.getenv("BEY_ENABLED", "true").lower() == "true"
    agent_greeting: str = os.getenv(
        "AGENT_GREETING",
        "Hi! I’m Katie, your appointment assistant. I can help you book, reschedule, cancel, or retrieve appointments. How can I help you today?",
    )


settings = Settings()
