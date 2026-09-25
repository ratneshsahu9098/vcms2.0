"""VCMS application package.

`create_app()` is the application factory: configuration, database,
migrations, scheduled jobs, request hooks and blueprints.
"""
import logging
import os

from flask import Flask

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from app.config import Config
from app.extensions import db

logging.basicConfig(level=logging.INFO)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    for folder in (app.config["UPLOAD_FOLDER"], app.config["EXPORT_FOLDER"], app.config["BACKUP_FOLDER"]):
        os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.dirname(Config.SETTINGS_FILE), exist_ok=True)

    from app.migrations import resequence_sr_nos, run_migrations
    from app.scheduler import start_scheduler

    with app.app_context():
        db.create_all()
        run_migrations()
        resequence_sr_nos()
        start_scheduler(app)

    from app.csrf import init_csrf
    from app.hooks import register_hooks
    from app.routes import register_blueprints

    register_blueprints(app)
    init_csrf(app)
    register_hooks(app)

    return app
