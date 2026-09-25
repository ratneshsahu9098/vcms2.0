import json
from datetime import datetime

from app.extensions import db


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

    @property
    def vehicle_number(self):
        return self.data_dict().get("vehicle_number") or (
            self.vehicle.vehicle_number if self.vehicle else ""
        )

    @property
    def owner_name(self):
        return self.data_dict().get("owner_name") or (
            self.vehicle.owner_name if self.vehicle else ""
        )

    def to_dict(self):
        return {
            "id": self.id,
            "file_name": self.file_name or "",
            "document_type": self.document_type or "",
            "data": self.data_dict(),
            "vehicle_id": self.vehicle_id,
            "scanned_at": self.scanned_at.strftime("%d %b %Y, %I:%M %p") if self.scanned_at else "",
        }
