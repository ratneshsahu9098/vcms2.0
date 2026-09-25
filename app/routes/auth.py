"""Login / logout (single-user session auth)."""

from flask import (Blueprint, flash, redirect, render_template, request, session, url_for)

from app.config import Config

bp = Blueprint("auth", __name__)

# ---- Auth ------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if not Config.LOGIN_REQUIRED:
        session["logged_in"] = True
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            flash("Welcome back!", "success")
            next_url = request.args.get("next") or url_for("main.dashboard")
            return redirect(next_url)
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


