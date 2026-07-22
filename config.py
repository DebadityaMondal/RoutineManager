"""Application configuration."""

import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
    SQLALCHEMY_DATABASE_URI = (
        "mysql+pymysql://routineuser:P%40ssw0rd@localhost/routinemanagerdb"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
