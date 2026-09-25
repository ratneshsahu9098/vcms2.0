from datetime import datetime

from app.extensions import db


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
