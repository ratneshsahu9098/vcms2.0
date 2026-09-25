"""Small JSON endpoints used by dashboards/AJAX."""
import time
from collections import defaultdict
from flask import (Blueprint, jsonify, request)

from app.middleware import login_required
from app.models import (Vehicle)

bp = Blueprint("api", __name__)

# Simple in-memory rate limiter: 30 requests per minute per IP
_RATE_LIMITS = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 30


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    requests = _RATE_LIMITS[ip]
    # Remove old requests outside window
    while requests and requests[0] < now - _RATE_LIMIT_WINDOW:
        requests.pop(0)
    if len(requests) >= _RATE_LIMIT_MAX:
        return False
    requests.append(now)
    return True


@bp.before_request
def _rate_limit_api():
    if request.path.startswith("/api/check-duplicate"):
        ip = request.remote_addr or "unknown"
        if not _check_rate_limit(ip):
            return jsonify({"error": "Rate limit exceeded. Try again later."}), 429


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


