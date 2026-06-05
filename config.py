import os
from dotenv import load_dotenv

load_dotenv(".env")

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    OWNER_ID = int(os.environ.get("OWNER_ID", 0))
    
    _storage_channel_str = os.environ.get("STORAGE_CHANNEL")
    if _storage_channel_str:
        try:
            STORAGE_CHANNEL = int(_storage_channel_str)
        except ValueError:
            STORAGE_CHANNEL = _storage_channel_str
    else:
        STORAGE_CHANNEL = 0
    
    BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    
    _fsub_channel_str = os.environ.get("FORCE_SUB_CHANNEL")
    if _fsub_channel_str:
        try:
            FORCE_SUB_CHANNEL = int(_fsub_channel_str)
        except ValueError:
            FORCE_SUB_CHANNEL = _fsub_channel_str
    else:
        FORCE_SUB_CHANNEL = 0
    
    BOT_USERNAME = ""