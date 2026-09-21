from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    assemblyai_api_key: str = os.getenv("ASSEMBLYAI_API_KEY", "")
    db_path: Path = Path(os.getenv("TACITOS_DB_PATH", "data/tacitos.db"))
    app_env: str = os.getenv("APP_ENV", "development")
    voice_ws_url: str = "wss://agents.assemblyai.com/v1/ws"
    voice_token_url: str = "https://agents.assemblyai.com/v1/token"


settings = Settings()
