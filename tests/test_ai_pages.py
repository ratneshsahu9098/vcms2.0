"""AI pages: chat send endpoint, sidebar, history, insights cache, parser UI."""
import os

import pytest

from app.config import Config
from app.models import ChatSession, db
from app.services import ai_service


@pytest.fixture()
def ai_on(monkeypatch):
    monkeypatch.setattr(ai_service, "check_api_key", lambda: True)
    monkeypatch.setattr(ai_service, "ask_assistant",
                        lambda q, v, history=None: f"REPLY: {q}")
    return monkeypatch


def _cleanup_sessions(app, *titles):
    with app.app_context():
        ChatSession.query.filter(ChatSession.title.in_(list(titles))).delete(
            synchronize_session=False)
        db.session.commit()


def test_chat_page_renders_sidebar_and_send_url(app, auth_client, ai_on):
    with app.app_context():
        db.session.add(ChatSession(title="Sidebar Probe"))
        db.session.commit()
    try:
        html = auth_client.get("/ai/chat").get_data(as_text=True)
        assert "Sidebar Probe" in html, "recent chats listed in sidebar"
        assert 'data-send-url="/ai/chat/send"' in html, "AJAX endpoint wired"
        assert 'id="chatInput"' in html and "chat-textarea" in html, "auto-grow textarea"
        assert "Ask anything about your fleet compliance data." in html
        assert "ai-suggestion-btn" in html, "suggestion chips kept"
        assert 'id="typingIndicator"' in html, "typing indicator present"
    finally:
        _cleanup_sessions(app, "Sidebar Probe")


def test_chat_send_creates_session_and_reply(app, auth_client, ai_on):
    _cleanup_sessions(app, "Send Probe")
    r = auth_client.post("/ai/chat/send", data={"message": "Send Probe"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["reply"] == "REPLY: Send Probe"
    assert data["session_id"]
    assert str(data["session_id"]) in data["session_url"]

    with app.app_context():
        s = ChatSession.query.get(data["session_id"])
        assert s is not None and s.title == "Send Probe"
        msgs = s.messages.all()
        assert [m.role for m in msgs] == ["user", "assistant"]

    # second send attaches to the same session
    r = auth_client.post("/ai/chat/send",
                         data={"message": "again", "session_id": str(data["session_id"])})
    data2 = r.get_json()
    assert data2["session_id"] == data["session_id"]
    with app.app_context():
        s = ChatSession.query.get(data["session_id"])
        assert s.messages.count() == 4
    _cleanup_sessions(app, "Send Probe")


def test_chat_send_validation_and_key(app, auth_client, ai_on):
    r = auth_client.post("/ai/chat/send", data={"message": "  "})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False

    ai_on.setattr(ai_service, "check_api_key", lambda: False)
    r = auth_client.post("/ai/chat/send", data={"message": "hi"})
    assert r.status_code == 503
    assert "API key" in r.get_json()["error"]


def test_chat_page_without_key(app, auth_client, monkeypatch):
    monkeypatch.setattr(ai_service, "check_api_key", lambda: False)
    html = auth_client.get("/ai/chat").get_data(as_text=True)
    assert "API Key Not Configured" in html
    assert 'data-send-url' not in html


def test_chat_history_page(app, auth_client, ai_on):
    with app.app_context():
        db.session.add(ChatSession(title="History Probe"))
        db.session.commit()
    try:
        html = auth_client.get("/ai/chat/history").get_data(as_text=True)
        assert "History Probe" in html
        assert 'id="histSearch"' in html, "search filter present"
        assert 'class="hist-title"' in html, "linked conversation titles"
        assert "Start a conversation" not in html
    finally:
        _cleanup_sessions(app, "History Probe")


def test_chat_history_empty_state(app, auth_client, ai_on):
    with app.app_context():
        ChatSession.query.delete()
        db.session.commit()
    html = auth_client.get("/ai/chat/history").get_data(as_text=True)
    assert "No chat history yet" in html
    assert 'id="histSearch"' not in html


def test_insights_cached_until_refresh(app, auth_client, monkeypatch):
    calls = {"n": 0}

    def fake_insights(vehicles):
        calls["n"] += 1
        return {"risk_summary": "RISK-ONE", "top_issues": ["issue a"],
                "recommendations": ["rec b"], "monthly_outlook": "calm month",
                "vehicle_risks": []}

    monkeypatch.setattr(ai_service, "check_api_key", lambda: True)
    monkeypatch.setattr(ai_service, "generate_insights", fake_insights)
    if os.path.isfile(Config.INSIGHTS_CACHE):
        os.remove(Config.INSIGHTS_CACHE)

    try:
        html = auth_client.get("/ai/insights").get_data(as_text=True)
        assert "RISK-ONE" in html and calls["n"] == 1
        assert "Generated" in html, "shows generation timestamp"
        assert "refresh=1" in html, "regenerate link forces refresh"

        html = auth_client.get("/ai/insights").get_data(as_text=True)
        assert "RISK-ONE" in html and calls["n"] == 1, "second load served from cache"

        html = auth_client.get("/ai/insights?refresh=1").get_data(as_text=True)
        assert "RISK-ONE" in html and calls["n"] == 2, "refresh forces regeneration"
        assert 'id="genOverlay"' in html, "loading overlay present"
    finally:
        if os.path.isfile(Config.INSIGHTS_CACHE):
            os.remove(Config.INSIGHTS_CACHE)


def test_parser_upload_overlay_render(app):
    with app.test_request_context("/ai/parse-document"):
        from flask import session
        session["logged_in"] = True
        html = app.jinja_env.get_template("ai_document_parser.html").render(
            parsed_data=None, ocr_text=None, ai_enabled=True, last_scans=[])
    assert 'id="scanOverlay"' in html, "processing overlay for OCR+AI wait"
    assert 'id="dropZone"' in html
    assert "Click or drag a document here" in html


def test_parser_form_sections_render(app):
    with app.test_request_context("/ai/parse-document"):
        from flask import session
        session["logged_in"] = True
        parsed = {
            "vehicle_number": "SECT01", "chassis_number": "SCH01",
            "owner_name": "Section Owner", "mobile_number": "9876500009",
            "tax_from": "2025-04-01", "tax_expiry": "2025-06-30",
            "tax_mode": "Quarterly (Q)", "tax_amount": 100,
            "permit_from": "2024-01-01", "permit_expiry": "2027-01-01",
        }
        html = app.jinja_env.get_template("ai_document_parser.html").render(
            parsed_data=parsed, ocr_text=None, ai_enabled=True,
            last_scans=[], current_scan_id=None, existing_vehicle=None, comparison=None)
    assert "Identity" in html and "Document Expiry" in html
    assert "Permit</h5>" in html and "Insurance</h5>" in html and "Tax</h5>" in html
    assert "form-actions-sticky" in html, "sticky action bar"
    assert 'name="vehicle_number"' in html and 'name="tax_amount"' in html
