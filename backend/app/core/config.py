import os
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")

class Settings(BaseSettings):
    
    app_name: str = "Employee API"
    debug: bool = False
    api_port: int = 8081
    frontend_url: str
    
    database_url: str
    
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_drive_redirect_uri: str

    clio_client_id: str
    clio_client_secret: str
    clio_redirect_uri: str
    clio_base_url: str = "https://app.clio.com"

    gemini_api_key: str = ""
    cerebras_api_key: str = ""
    generation_provider: str = "gemini"  # "gemini" or "cerebras"
    cerebras_model: str = "qwen-3-235b-instruct"
    
    # class Coonfig:
    #     # env_file = ".env"
    #     env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    #     env_file_encoding = "utf-8"
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding='utf-8',
        extra='ignore' 
    )
        
settings = Settings()
