import json
import os
import re
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from sqlalchemy import desc, func, inspect, text
from sqlalchemy.orm import Session

if __package__ in {None, ""}:
    # Allow running the file directly with `python app/main.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import auth, models
    from app.config import get_settings
    from app.database import Base, SessionLocal, engine
    from app.exporters import (
        build_forecast_csv_bytes,
        build_forecast_pdf_bytes,
        make_safe_filename,
    )
    from app.forecasting import (
        ForecastInputError,
        build_forecast,
        parse_history_csv,
    )
else:
    from . import auth, models
    from .config import get_settings
    from .database import Base, SessionLocal, engine
    from .exporters import (
        build_forecast_csv_bytes,
        build_forecast_pdf_bytes,
        make_safe_filename,
    )
    from .forecasting import (
        ForecastInputError,
        build_forecast,
        parse_history_csv,
    )

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _is_truthy_env(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in TRUTHY_ENV_VALUES

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
)
is_debug = _is_truthy_env(os.getenv("FLASK_DEBUG"))
app.config.update(
    SECRET_KEY=settings.secret_key,
    SESSION_COOKIE_NAME=settings.session_cookie_name,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not is_debug,
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)


def _suppress_werkzeug_dev_warning() -> None:
    if not _is_truthy_env(os.getenv("HIDE_FLASK_DEV_WARNING")):
        return
    try:
        from werkzeug import serving as werkzeug_serving
    except Exception:
        return

    original_log = getattr(werkzeug_serving, "_log", None)
    if original_log is None:
        return
    if getattr(original_log, "__name__", "") == "_log_without_dev_warning":
        return

    def _log_without_dev_warning(
        level: str,
        message: str,
        *args: object,
    ) -> None:
        if isinstance(message, str):
            filtered_lines = [
                line
                for line in message.splitlines()
                if "WARNING: This is a development server." not in line
            ]
            message = "\n".join(filtered_lines).rstrip()
            if not message:
                return
        original_log(level, message, *args)

    setattr(werkzeug_serving, "_log", _log_without_dev_warning)


def _ensure_role_column() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as connection:
        if "role" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN role "
                    "VARCHAR(20) DEFAULT 'user' NOT NULL"
                )
            )
        connection.execute(
            text(
                "UPDATE users SET role = 'user' "
                "WHERE role IS NULL OR role = ''"
            )
        )


def _promote_configured_admin() -> None:
    if not settings.admin_email:
        return
    db = SessionLocal()
    try:
        user = auth.get_user_by_email(db, settings.admin_email)
        if user is None:
            return
        if user.role != "admin":
            user.role = "admin"
            db.commit()
    finally:
        db.close()


def _init_database() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_role_column()
    _promote_configured_admin()


def _redirect(path: str, **query_params: str) -> Response:
    filtered = {k: v for k, v in query_params.items() if v}
    qs = urlencode(filtered)
    url = f"{path}?{qs}" if qs else path
    return redirect(url, code=303)


def _require_user(db: Session) -> models.User | None:
    return auth.get_current_user(session, db)


def _get_run_with_access(
    db: Session,
    current_user: models.User | None,
    run_id: int,
) -> models.ForecastRun | None:
    if not current_user:
        return None
    run = (
        db.query(models.ForecastRun)
        .filter(models.ForecastRun.id == run_id)
        .first()
    )
    if not run:
        return None
    if run.user_id == current_user.id or auth.is_admin(current_user):
        return run
    return None


_suppress_werkzeug_dev_warning()
_init_database()


@app.before_request
def csrf_protect() -> Response | None:
    if request.method == "POST":
        token = session.get("csrf_token")
        if not token or token != request.form.get("csrf_token"):
            return _redirect(
                "/login",
                error="CSRF token mismatch. Please try again.",
            )
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return None


@app.context_processor
def inject_csrf() -> dict[str, str | None]:
    return dict(csrf_token=session.get("csrf_token"))


@app.get("/")
def home() -> Response:
    with SessionLocal() as db:
        user = _require_user(db)
    if user:
        return _redirect("/dashboard")
    return _redirect("/login")


@app.get("/health")
def health() -> Response:
    return jsonify({"status": "ok"})


@app.get("/register")
def register_page() -> str | Response:
    with SessionLocal() as db:
        if _require_user(db):
            return _redirect("/dashboard")

    return render_template(
        "register.html",
        error=request.args.get("error"),
        message=request.args.get("message"),
        user=None,
    )


@app.post("/register")
def register() -> Response:
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    with SessionLocal() as db:
        if "@" not in email or "." not in email:
            return _redirect("/register", error="Please enter a valid email.")
        has_uppercase = re.search(r"[A-Z]", password)
        has_number = re.search(r"[0-9]", password)
        if len(password) < 8 or not has_uppercase or not has_number:
            return _redirect(
                "/register",
                error=(
                    "Password must be at least 8 characters long, "
                    "and contain at least 1 uppercase letter and 1 number."
                ),
            )
        if auth.get_user_by_email(db, email):
            return _redirect(
                "/register",
                error="An account with this email already exists.",
            )

        user = auth.create_user(db, email, password)

    session["user_id"] = user.id
    session.permanent = True
    return _redirect("/dashboard", message="Account created successfully.")


@app.get("/login")
def login_page() -> str | Response:
    with SessionLocal() as db:
        if _require_user(db):
            return _redirect("/dashboard")

    return render_template(
        "login.html",
        error=request.args.get("error"),
        message=request.args.get("message"),
        user=None,
    )


@app.post("/login")
def login() -> Response:
    email = request.form.get("email", "")
    password = request.form.get("password", "")

    with SessionLocal() as db:
        user = auth.authenticate_user(db, email, password)
        if not user:
            return _redirect("/login", error="Invalid email or password.")

    session["user_id"] = user.id
    session.permanent = True
    return _redirect("/dashboard", message="Welcome back.")


@app.post("/logout")
def logout() -> Response:
    session.clear()
    return _redirect("/login", message="You have been logged out.")


@app.get("/dashboard")
def dashboard() -> str | Response:
    run_id = request.args.get("run_id", type=int)
    with SessionLocal() as db:
        user = _require_user(db)
        if not user:
            return _redirect("/login", message="Please login first.")

        runs = (
            db.query(models.ForecastRun)
            .filter(models.ForecastRun.user_id == user.id)
            .order_by(desc(models.ForecastRun.created_at))
            .all()
        )

        active_run = None
        if run_id:
            active_run = (
                db.query(models.ForecastRun)
                .filter(
                    models.ForecastRun.id == run_id,
                    models.ForecastRun.user_id == user.id,
                )
                .first()
            )
        if not active_run and runs:
            active_run = runs[0]

        context = {
            "user": user,
            "runs": runs,
            "active_run": active_run,
            "message": request.args.get("message"),
            "error": request.args.get("error"),
            "summary": None,
            "historical": [],
            "forecast": [],
            "chart_payload": "{}",
        }

        if active_run:
            summary = json.loads(str(active_run.summary_json))
            historical = json.loads(str(active_run.historical_json))
            forecast = json.loads(str(active_run.forecast_json))

            chart = {
                "labels": [item["date"] for item in historical + forecast],
                "historical_values": [item["demand"] for item in historical]
                + [None] * len(forecast),
                "forecast_values": [None] * len(historical)
                + [item["demand"] for item in forecast],
            }

            context.update(
                {
                    "summary": summary,
                    "historical": historical,
                    "forecast": forecast,
                    "chart_payload": json.dumps(chart),
                }
            )

    return render_template("dashboard.html", **context)


@app.get("/admin")
def admin_dashboard() -> str | Response:
    with SessionLocal() as db:
        current_user = _require_user(db)
        if not current_user:
            return _redirect("/login", message="Please login first.")
        if not auth.is_admin(current_user):
            return _redirect("/dashboard", error="Admin access required.")

        total_users = db.query(func.count(models.User.id)).scalar() or 0
        total_forecasts = (
            db.query(func.count(models.ForecastRun.id)).scalar() or 0
        )
        total_admins = (
            db.query(func.count(models.User.id))
            .filter(models.User.role == "admin")
            .scalar()
            or 0
        )

        users = (
            db.query(
                models.User.id,
                models.User.email,
                models.User.role,
                models.User.created_at,
                func.count(models.ForecastRun.id).label("forecast_count"),
            )
            .outerjoin(
                models.ForecastRun,
                models.ForecastRun.user_id == models.User.id,
            )
            .group_by(
                models.User.id,
                models.User.email,
                models.User.role,
                models.User.created_at,
            )
            .order_by(desc(models.User.created_at))
            .all()
        )

        recent_runs = (
            db.query(
                models.ForecastRun.id,
                models.ForecastRun.product_name,
                models.ForecastRun.input_points,
                models.ForecastRun.created_at,
                models.User.email.label("user_email"),
            )
            .join(models.User, models.User.id == models.ForecastRun.user_id)
            .order_by(desc(models.ForecastRun.created_at))
            .limit(20)
            .all()
        )

    return render_template(
        "admin.html",
        user=current_user,
        users=users,
        recent_runs=recent_runs,
        total_users=total_users,
        total_forecasts=total_forecasts,
        total_admins=total_admins,
        message=request.args.get("message"),
        error=request.args.get("error"),
    )


@app.post("/admin/users/<int:user_id>/role")
def update_user_role(user_id: int) -> Response:
    role = request.form.get("role", "")

    with SessionLocal() as db:
        current_user = _require_user(db)
        if not current_user:
            return _redirect("/login", message="Please login first.")
        if not auth.is_admin(current_user):
            return _redirect("/dashboard", error="Admin access required.")

        normalized_role = role.strip().lower()
        if normalized_role not in {"user", "admin"}:
            return _redirect("/admin", error="Invalid role.")

        target_user = (
            db.query(models.User)
            .filter(models.User.id == user_id)
            .first()
        )
        if not target_user:
            return _redirect("/admin", error="User not found.")

        if current_user.id == target_user.id and normalized_role != "admin":
            return _redirect(
                "/admin",
                error="You cannot remove your own admin role.",
            )

        if normalized_role == "user" and target_user.role == "admin":
            total_admins = (
                db.query(func.count(models.User.id))
                .filter(models.User.role == "admin")
                .scalar()
                or 0
            )
            if total_admins <= 1:
                return _redirect(
                    "/admin",
                    error="At least one admin account is required.",
                )

        target_user.role = normalized_role
        db.commit()
        target_email = target_user.email

    return _redirect("/admin", message=f"Role updated for {target_email}.")


@app.post("/forecast")
def create_forecast() -> Response:
    product_name = request.form.get("product_name", "").strip()
    history_file = request.files.get("history_file")

    with SessionLocal() as db:
        user = _require_user(db)
        if not user:
            return _redirect("/login", message="Please login first.")

        if not product_name:
            return _redirect("/dashboard", error="Product name is required.")
        if history_file is None or not history_file.filename:
            return _redirect("/dashboard", error="CSV file is required.")

        try:
            file_content = history_file.read()
            monthly = parse_history_csv(file_content)
            result = build_forecast(monthly, horizon_months=60)
        except ForecastInputError as exc:
            return _redirect("/dashboard", error=str(exc))
        except Exception:
            return _redirect(
                "/dashboard",
                error=(
                    "Forecasting failed. "
                    "Please review your data and try again."
                ),
            )

        run = models.ForecastRun(
            user_id=user.id,
            product_name=product_name,
            input_points=len(result["historical"]),
            historical_json=json.dumps(result["historical"]),
            forecast_json=json.dumps(result["forecast"]),
            summary_json=json.dumps(result["summary"]),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    return _redirect(
        "/dashboard",
        run_id=str(run_id),
        message=f"Forecast generated for {product_name}.",
    )


@app.get("/api/forecast/<int:run_id>")
def forecast_api(run_id: int) -> tuple[Response, int] | Response:
    with SessionLocal() as db:
        user = _require_user(db)
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        run = _get_run_with_access(db, user, run_id)
        if not run:
            return jsonify({"error": "Forecast run not found."}), 404

        payload = {
            "id": run.id,
            "product_name": run.product_name,
            "input_points": run.input_points,
            "summary": json.loads(str(run.summary_json)),
            "historical": json.loads(str(run.historical_json)),
            "forecast": json.loads(str(run.forecast_json)),
            "created_at": (
                run.created_at.isoformat()
                if run.created_at is not None
                else None
            ),
        }

    return jsonify(payload)


@app.get("/export/forecast/<int:run_id>.csv")
def export_forecast_csv(run_id: int) -> Response:
    with SessionLocal() as db:
        user = _require_user(db)
        if not user:
            return _redirect("/login", message="Please login first.")

        run = _get_run_with_access(db, user, run_id)
        if not run:
            return _redirect("/dashboard", error="Forecast run not found.")

        historical = json.loads(str(run.historical_json))
        forecast = json.loads(str(run.forecast_json))
        summary = json.loads(str(run.summary_json))
        created_at = (
            run.created_at.isoformat() if run.created_at is not None else None
        )

    csv_bytes = build_forecast_csv_bytes(
        product_name=run.product_name,
        historical=historical,
        forecast=forecast,
        summary=summary,
        created_at=created_at,
    )
    filename = make_safe_filename(f"{run.product_name}_forecast_{run.id}.csv")

    return Response(
        csv_bytes,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/forecast/<int:run_id>.pdf")
def export_forecast_pdf(run_id: int) -> Response:
    with SessionLocal() as db:
        user = _require_user(db)
        if not user:
            return _redirect("/login", message="Please login first.")

        run = _get_run_with_access(db, user, run_id)
        if not run:
            return _redirect("/dashboard", error="Forecast run not found.")

        historical = json.loads(str(run.historical_json))
        forecast = json.loads(str(run.forecast_json))
        summary = json.loads(str(run.summary_json))
        created_at = run.created_at.isoformat() if run.created_at else None

    pdf_bytes = build_forecast_pdf_bytes(
        product_name=run.product_name,
        historical=historical,
        forecast=forecast,
        summary=summary,
        created_at=created_at,
    )
    filename = make_safe_filename(f"{run.product_name}_forecast_{run.id}.pdf")

    return Response(
        pdf_bytes,
        content_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = _is_truthy_env(os.getenv("FLASK_DEBUG"))
    app.run(host=host, port=port, debug=debug)
