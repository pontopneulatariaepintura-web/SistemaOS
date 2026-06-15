import os

class Config:
    SECRET_KEY = "SISTEMA-OS-2026"

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///database.db"  # local fallback
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False