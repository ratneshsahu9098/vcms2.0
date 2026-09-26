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

        # Create document_expiries table for multi-expiry support
        if "document_expiries" not in table_names:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text(
                        "CREATE TABLE document_expiries ("
                        "id INTEGER NOT NULL PRIMARY KEY, "
                        "vehicle_id INTEGER NOT NULL, "
                        "document_type VARCHAR(30) NOT NULL, "
                        "expiry_date DATE NOT NULL, "
                        "certificate_number VARCHAR(100), "
                        "issuing_authority VARCHAR(200), "
                        "remarks TEXT, "
                        "is_current BOOLEAN DEFAULT 1, "
                        "created_at DATETIME, "
                        "updated_at DATETIME, "
                        "FOREIGN KEY(vehicle_id) REFERENCES vehicles (id))"
                    ))
                    conn.execute(db.text("CREATE INDEX ix_document_expiries_vehicle_id ON document_expiries (vehicle_id)"))
                    conn.execute(db.text("CREATE INDEX ix_document_expiries_document_type ON document_expiries (document_type)"))
                    conn.execute(db.text("CREATE INDEX ix_document_expiries_expiry_date ON document_expiries (expiry_date)"))
                logger.info("Migration: created document_expiries table")
            except Exception as e:
                logger.warning(f"Migration skipped document_expiries table: {e}")

        # Migrate legacy single-date fields to document_expiries
        try:
            with db.engine.begin() as conn:
                # Check if migration already done
                result = conn.execute(db.text("SELECT COUNT(*) FROM document_expiries")).scalar()
                if result == 0:
                    vehicles = conn.execute(db.text("SELECT id, vehicle_number, puc_expiry, fitness_expiry, permit_expiry, tax_expiry, insurance_expiry, national_permit_expiry, state_permit_expiry FROM vehicles")).fetchall()
                    for v in vehicles:
                        vid = v[0]
                        vnum = v[1]
                        # Map legacy fields to document types
                        legacy_map = {
                            "PUC": v[2],
                            "Fitness": v[3],
                            "Permit": v[4],
                            "Tax": v[5],
                            "Insurance": v[6],
                            "National Permit": v[7],
                            "State Permit": v[8],
                        }
                        for doc_type, expiry_date in legacy_map.items():
                            if expiry_date:
                                conn.execute(db.text(
                                    "INSERT INTO document_expiries (vehicle_id, document_type, expiry_date, is_current, created_at, updated_at) "
                                    "VALUES (:vid, :dtype, :edate, 1, datetime('now'), datetime('now'))"
                                ), {"vid": vid, "dtype": doc_type, "edate": expiry_date})
                    logger.info(f"Migration: migrated legacy expiries for {len(vehicles)} vehicles")
        except Exception as e:
            logger.warning(f"Migration skipped legacy expiry migration: {e}")

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
