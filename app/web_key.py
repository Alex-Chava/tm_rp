import secrets
from datetime import datetime
from threading import Lock

_key_lock = Lock()

def get_web_key_daily(config: dict) -> str:
    """
    Ключ действует 1 сутки и меняется только при смене даты (локальное время).
    config — это current_app.config (обычный dict-подобный объект).
    """
    today = datetime.now().date()

    with _key_lock:
        key = config.get("CURRENT_KEY")
        key_date = config.get("CURRENT_KEY_DATE")

        if not key or not key_date:
            key = secrets.token_urlsafe(16)
            config["CURRENT_KEY"] = key
            config["CURRENT_KEY_DATE"] = today
            return key

        if key_date != today:
            key = secrets.token_urlsafe(16)
            config["CURRENT_KEY"] = key
            config["CURRENT_KEY_DATE"] = today
            return key

        return key
