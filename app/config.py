# config.py

import os

class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, '../database.db')}"
    SECRET_KEY = 'your-secret'
