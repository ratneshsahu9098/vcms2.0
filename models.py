from datetime import datetime, date
import json

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class TaxDetail(db.Model):
    __tablename__ = "tax_details"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    tax_mode = db.Column(db.String(50))
    latest_tax_from = db.Column(db.Date)
    latest_tax_upto = db.Column(db.Date)
    tax_amount = db.Column(db.Float, default=0)
    penalty = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = db.relationship("Vehicle", backref=db.backref("tax_details", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "vehicle_number": self.vehicle.vehicle_number if self.vehicle else "",
            "tax_mode": self.tax_mode or "",
            "latest_tax_from": self.latest_tax_from.isoformat() if self.latest_tax_from else "",
            "latest_tax_upto": self.latest_tax_upto.isoformat() if self.latest_tax_upto else "",
            "tax_amount": self.tax_amount or 0,
            "penalty": self.penalty or 0,
        }


class Vehicle(db.Model):
    __tablename__ = "vehicles"

    id = db.Column(db.Integer, primary_key=True)

    sr_no = db.Column(db.String(30))
    vehicle_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    chassis_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    engine_number = db.Column(db.String(50))
    owner_name = db.Column(db.String(120), nullable=False)
    mobile_number = db.Column(db.String(15), nullable=False)
    owner_email = db.Column(db.String(255))
    vehicle_type = db.Column(db.String(50))
    district = db.Column(db.String(80))

    registration_date = db.Column(db.Date)

    puc_expiry = db.Column(db.Date)
    fitness_expiry = db.Column(db.Date)
    permit_from = db.Column(db.Date)
    permit_expiry = db.Column(db.Date)
    permit_auth_no = db.Column(db.String(50))
    permit_address = db.Column(db.String(255))
    tax_from = db.Column(db.Date)
    tax_expiry = db.Column(db.Date)
    tax_mode = db.Column(db.String(30))
    tax_amount = db.Column(db.Float, default=0)
    insurance_expiry = db.Column(db.Date)
    national_permit_expiry = db.Column(db.Date)
    state_permit_expiry = db.Column(db.Date)

    pollution_certificate_number = db.Column(db.String(50))
    insurance_company = db.Column(db.String(120))
    policy_number = db.Column(db.String(50))

    remarks = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ---- Compliance helpers -------------------------------------------------

    DOCUMENT_FIELDS = {
        "PUC": "puc_expiry",
        "Fitness": "fitness_expiry",
        "Permit": "permit_expiry",
        "Tax": "tax_expiry",
        "Insurance": "insurance_expiry",
    }

    @staticmethod
    def status_for(expiry_date):
        """Return (status, css_class) for a given expiry date."""
        if expiry_date is None:
            return "N/A", "status-gray"
        today = date.today()
        days_left = (expiry_date - today).days
        if days_left < 0:
            return "Expired", "status-red"
        if days_left == 0:
            return "Expires Today", "status-orange"
        if days_left <= 7:
            return "Expiring Soon", "status-orange"
        if days_left <= 30:
            return "Expiring Soon", "status-yellow"
        return "Valid", "status-green"

    def document_statuses(self):
        result = {}
        for label, field in self.DOCUMENT_FIELDS.items():
            expiry = getattr(self, field)
            status, css_class = self.status_for(expiry)
            result[label] = {"expiry": expiry, "status": status, "class": css_class}
        return result

    def overall_status(self):
        """Worst-case status across all tracked documents."""
        priority = ["status-red", "status-orange", "status-yellow", "status-gray", "status-green"]
        statuses = [v["class"] for v in self.document_statuses().values()]
        for p in priority:
            if p in statuses:
                return p
        return "status-green"

    def to_dict(self):
        return {
            "id": self.id,
            "sr_no": self.sr_no or "",
            "vehicle_number": self.vehicle_number,
            "chassis_number": self.chassis_number,
            "engine_number": self.engine_number,
            "owner_name": self.owner_name,
            "mobile_number": self.mobile_number,
            "owner_email": self.owner_email or "",
            "vehicle_type": self.vehicle_type,
            "district": self.district,
            "registration_date": self.registration_date.isoformat() if self.registration_date else "",
            "puc_expiry": self.puc_expiry.isoformat() if self.puc_expiry else "",
            "fitness_expiry": self.fitness_expiry.isoformat() if self.fitness_expiry else "",
            "permit_expiry": self.permit_expiry.isoformat() if self.permit_expiry else "",
            "permit_from": self.permit_from.isoformat() if self.permit_from else "",
            "permit_auth_no": self.permit_auth_no or "",
            "permit_address": self.permit_address or "",
            "tax_from": self.tax_from.isoformat() if self.tax_from else "",
            "tax_expiry": self.tax_expiry.isoformat() if self.tax_expiry else "",
            "tax_mode": self.tax_mode or "",
            "tax_amount": self.tax_amount or 0,
            "insurance_expiry": self.insurance_expiry.isoformat() if self.insurance_expiry else "",
            "national_permit_expiry": self.national_permit_expiry.isoformat() if self.national_permit_expiry else "",
            "state_permit_expiry": self.state_permit_expiry.isoformat() if self.state_permit_expiry else "",
            "pollution_certificate_number": self.pollution_certificate_number or "",
            "insurance_company": self.insurance_company or "",
            "policy_number": self.policy_number or "",
            "remarks": self.remarks or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class ChatSession(db.Model):
    __tablename__ = "chat_sessions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default="New Chat")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship("ChatMessage", backref="session", lazy="dynamic", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.strftime("%d %b %Y, %I:%M %p") if self.created_at else "",
            "updated_at": self.updated_at.strftime("%d %b %Y, %I:%M %p") if self.updated_at else "",
            "message_count": self.messages.count(),
        }


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("chat_sessions.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ReminderLog(db.Model):
    __tablename__ = "reminder_logs"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True)
    document_type = db.Column(db.String(30), nullable=False)
    recipient_email = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), default="sent")
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    kind = db.Column(db.String(20), default="reminder")

    vehicle = db.relationship("Vehicle", backref=db.backref("reminder_logs", lazy="dynamic"))


class DocumentScan(db.Model):
    __tablename__ = "document_scans"

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255))
    document_type = db.Column(db.String(50))
    parsed_data = db.Column(db.Text)          # JSON string of extracted fields
    ocr_text = db.Column(db.Text)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)

    vehicle = db.relationship("Vehicle", backref=db.backref("document_scans", lazy="dynamic"))

    def data_dict(self):
        try:
            return json.loads(self.parsed_data or "{}")
        except Exception:
            return {}

    def to_dict(self):
        return {
            "id": self.id,
            "file_name": self.file_name or "",
            "document_type": self.document_type or "",
            "data": self.data_dict(),
            "vehicle_id": self.vehicle_id,
            "scanned_at": self.scanned_at.strftime("%d %b %Y, %I:%M %p") if self.scanned_at else "",
        }
