"""Small JSON endpoints used by dashboards/AJAX."""

from flask import (Blueprint, jsonify, request)

from app.middleware import login_required
from app.models import (Vehicle)

bp = Blueprint("api", __name__)

# ---- API used by dashboard charts / AJAX --------------------------------

@bp.route("/api/vehicle/<int:vehicle_id>")
@login_required
def api_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    return jsonify(vehicle.to_dict())

@bp.route("/api/check-duplicate")
@login_required
def check_duplicate():
    field = request.args.get("field", "")
    value = request.args.get("value", "").strip().upper()
    exclude_id = request.args.get("exclude_id", type=int)
    if not field or not value:
        return jsonify({"exists": False})
    if field not in {c.name for c in Vehicle.__table__.columns}:
        return jsonify({"error": "unknown field"}), 400
    query = Vehicle.query.filter(getattr(Vehicle, field) == value)
    if exclude_id:
        query = query.filter(Vehicle.id != exclude_id)
    return jsonify({"exists": query.first() is not None})


