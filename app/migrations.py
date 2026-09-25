"""Lightweight SQLite migrations for columns added after first release.

Kept deliberately simple (guarded ALTER TABLE / table rebuilds) — no Alembic.
Runs automatically on every app start; each step is idempotent.
"""
import logging

from app.extensions import db
from app.models import Vehicle

logger = logging.getLogger(__name__)


def run_migrations():
    """Add missing columns / rebuild tables as needed. Never raises."""
    try:
        inspector = db.inspect(db.engine)
        table_names = inspector.get_table_names()
        if "vehicles" not in table_names:
            return
        migrations = [
            ("vehicles", "owner_email", "VARCHAR(255)"),
            ("vehicles", "permit_from", "DATE"),
            ("vehicles", "permit_auth_no", "VARCHAR(50)"),
            ("vehicles", "permit_address", "VARCHAR(255)"),
            ("reminder_logs", "kind", "VARCHAR(20)"),
        ]
        with db.engine.begin() as conn:
            for table, column, col_type in migrations:
                existing_cols = [c["name"] for c in inspector.get_columns(table)]
                if column not in existing_cols:
                    try:
                        conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                        logger.info(f"Migration: added {table}.{column}")
                    except Exception as e:
                        logger.warning(f"Migration skipped {table}.{column}: {e}")

        # reminder_logs: backfill kind for old rows and make vehicle_id nullable
        # (manual detail emails / tests are not tied to a single vehicle).
        try:
            if "reminder_logs" in table_names:
                cols = {c["name"]: c for c in db.inspect(db.engine).get_columns("reminder_logs")}
                if "kind" in cols:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("UPDATE reminder_logs SET kind = 'reminder' WHERE kind IS NULL"))
                    logger.info("Migration: reminder_logs.kind backfilled")
                vc = cols.get("vehicle_id")
                if vc is not None and not vc.get("nullable", True):
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE reminder_logs RENAME TO reminder_logs_old"))
                        conn.execute(db.text(
                            "CREATE TABLE reminder_logs ("
                            "id INTEGER NOT NULL PRIMARY KEY, "
                            "vehicle_id INTEGER, "
                            "document_type VARCHAR(30) NOT NULL, "
                            "recipient_email VARCHAR(120) NOT NULL, "
                            "status VARCHAR(20), "
                            "error_message TEXT, "
                            "sent_at DATETIME, "
                            "kind VARCHAR(20), "
                            "FOREIGN KEY(vehicle_id) REFERENCES vehicles (id))"
                        ))
                        conn.execute(db.text(
                            "INSERT INTO reminder_logs (id, vehicle_id, document_type, recipient_email,"
                            " status, error_message, sent_at, kind)"
                            " SELECT id, vehicle_id, document_type, recipient_email,"
                            " status, error_message, sent_at, kind FROM reminder_logs_old"
                        ))
                        conn.execute(db.text("DROP TABLE reminder_logs_old"))
                    logger.info("Migration: reminder_logs.vehicle_id is now nullable")
        except Exception as e:
            logger.warning(f"Migration skipped reminder_logs rebuild: {e}")
    except Exception as e:
        logger.warning(f"Migration check failed: {e}")


def resequence_sr_nos():
    """Renumber SN001..SNnnn in vehicle-number order."""
    vehicles = Vehicle.query.order_by(Vehicle.vehicle_number).all()
    for i, v in enumerate(vehicles, 1):
        v.sr_no = f"SN{i:03d}"
    db.session.commit()
