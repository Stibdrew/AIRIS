import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = "airis-dev-secret-key-change-in-production"
    DATA_DIR = os.path.join(BASE_DIR, "data")
    DATABASE_PATH = os.path.join(DATA_DIR, "airis.db")

    BUILDING_NAME = "SH Building"
    RESTROOM_COUNT = 6

    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "airis2025"
