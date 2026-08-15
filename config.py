"""Application configuration."""

import os
from urllib.parse import quote_plus


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "mysql+pymysql://{user}:{password}@{host}/{db}".format(
            user=os.environ.get("DB_USER", "routineuser"),
            password=quote_plus(os.environ.get("DB_PASSWORD", "")),
            host=os.environ.get("DB_HOST", "localhost"),
            db=os.environ.get("DB_NAME", "routinemanagerdb"),
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
