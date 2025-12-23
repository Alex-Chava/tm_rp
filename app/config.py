# config.py

import os
import json

class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    # читаем config.json
    CONFIG_JSON = os.path.join(BASE_DIR, '..', 'config.json')

    DEVICE_NAME = "default"

    if os.path.exists(CONFIG_JSON):
        with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            DEVICE_NAME = cfg.get("DEVICE_NAME", DEVICE_NAME)

    # БД = имя устройства
    DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, '..', f'{DEVICE_NAME}.db')}"

    SECRET_KEY = 'your-secret'
