import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OCR_API_KEY: str = os.getenv("OCR_API_KEY", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    REQUEST_TIMEOUT: int = 15
    MAX_RETRIES: int = 3
    
    class Config:
        env_file = ".env"

    def validate_startup(self):
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is missing!")

settings = Settings()
