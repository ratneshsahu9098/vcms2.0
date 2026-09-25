"""Per-vehicle tax detail records (CRUD)."""

from flask import (Blueprint, flash, redirect, render_template, request, url_for)

from app.extensions import db
from app.middleware import login_required
from app.models import (TaxDetail, Vehicle)
from app.utils import (parse_date, to_float)

bp = Blueprint("tax", __name__)

# ---- Tax Details ----------------------------------------------------------

@bp.route("/vehicles/<int:vehicle_id>/tax")
@login_required
def vehicle_tax(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    taxes = vehicle.tax_details.order_by(TaxDetail.latest_tax_from.desc()).all()
    return render_template("vehicle_tax.html", vehicle=vehicle, taxes=taxes)

@bp.route("/vehicles/<int:vehicle_id>/tax/add", methods=["GET", "POST"])
@login_required
def add_tax(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if request.method == "POST":
        tax = TaxDetail(
            vehicle_id=vehicle.id,
            tax_mode=request.form.get("tax_mode", "").strip(),
            latest_tax_from=parse_date(request.form.get("latest_tax_from")),
            latest_tax_upto=parse_date(request.form.get("latest_tax_upto")),
            tax_amount=to_float(request.form.get("tax_amount")),
            penalty=to_float(request.form.get("penalty")),
        )
        db.session.add(tax)
        db.session.commit()
        flash("Tax detail added successfully.", "success")
        return redirect(url_for("tax.vehicle_tax", vehicle_id=vehicle.id))
    return render_template("tax_form.html", vehicle=vehicle, tax=None)

@bp.route("/tax/<int:tax_id>/edit", methods=["GET", "POST"])
@login_required
def edit_tax(tax_id):
    tax = TaxDetail.query.get_or_404(tax_id)
    if request.method == "POST":
        tax.tax_mode = request.form.get("tax_mode", "").strip()
        tax.latest_tax_from = parse_date(request.form.get("latest_tax_from"))
        tax.latest_tax_upto = parse_date(request.form.get("latest_tax_upto"))
        tax.tax_amount = to_float(request.form.get("tax_amount"))
        tax.penalty = to_float(request.form.get("penalty"))
        db.session.commit()
        flash("Tax detail updated.", "success")
        return redirect(url_for("tax.vehicle_tax", vehicle_id=tax.vehicle_id))
    return render_template("tax_form.html", vehicle=tax.vehicle, tax=tax)

@bp.route("/tax/<int:tax_id>/delete", methods=["POST"])
@login_required
def delete_tax(tax_id):
    tax = TaxDetail.query.get_or_404(tax_id)
    vid = tax.vehicle_id
    db.session.delete(tax)
    db.session.commit()
    flash("Tax detail deleted.", "success")
    return redirect(url_for("tax.vehicle_tax", vehicle_id=vid))


