import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OCR_API_KEY: str = os.getenv("OCR_API_KEY", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    # Telethon application credentials — required for /string, /create_session, /login_session
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")
    REQUEST_TIMEOUT: int = 15
    MAX_RETRIES: int = 3
    
    class Config:
        env_file = ".env"

    def validate_startup(self) -> None:
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is missing!")
        # Non-fatal warnings — bot starts but affected features will degrade
        import logging
        _log = logging.getLogger("ShadePlatform")
        if not self.OCR_API_KEY:
            _log.warning({
                "event": "config_warning",
                "key": "OCR_API_KEY",
                "impact": "/ocr command will fail with 401 until key is set",
            })
        if not self.API_ID or not self.API_HASH:
            _log.warning({
                "event": "config_warning",
                "key": "API_ID/API_CREDENTIALS",
                "impact": "/string, /create_session, /login_session will fail until API_ID and credentials are set",
            })

settings = Settings()
