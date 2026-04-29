
from pathlib import Path
from pydantic_settings import BaseSettings



class Settings(BaseSettings):
    # Application
    PROJECT_NAME: str = "Urban Better Air Quality Backend"
    PROJECT_DESCRIPTION: str = "Backend for Urban Better Air Quality"
    PROJECT_VERSION: str = "1.0.0"
    # CORS; override with JSON in .env e.g. ALLOWED_ORIGINS='["https://...","http://localhost:3000"]'
    ALLOWED_ORIGINS: list[str] = [
        "https://main.d2dbh91n23oexj.amplifyapp.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ]
    
    AIRQO_URL: str = "https://api.airqo.net/api/v2/devices"
    AIRQO_GRIDS_SUMMARY_URL: str = (
        "http://api.airqo.net/api/v2/devices/grids/summary"
        "?limit=30&skip=0&tenant=airqo&detailLevel=summary&admin_level=country"
    )
    AIRQO_API_KEY: str

    # Cerebras (OpenAI-compatible chat — used for insight LLM summary)
    CEREBRAS_API_KEY: str = ""
    CEREBRAS_BASE_URL: str = "https://api.cerebras.ai/v1"
    CEREBRAS_MODEL: str = "llama3.1-8b"
    CEREBRAS_MAX_TOKENS: int = 500
    CEREBRAS_COMPARE_MAX_TOKENS: int = 700
    CEREBRAS_TEMPERATURE: float = 0.3

    #
    
    class Config:
        env_file = str(Path(__file__).parent.parent.parent / ".env")
        extra = "ignore"  # Allow extra fields to prevent validation errors


settings = Settings()
