from datetime import datetime

from app.extensions import db


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
