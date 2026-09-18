from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_edit_state_forces_update(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.DB_PATH", tmp_path / "assistant.db")
    assert client.post("/v1/edit/begin", json={"chat_id": "1", "event_id": "event-1"}).status_code == 200
    response = client.post("/v1/voice/resolve", json={"chat_id": "1", "transcript": "Переименуй в встречу"})
    assert response.json() == {"intent": "update_event", "event_id": "event-1", "requires_update": True}


def test_cancel_never_creates_event(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.DB_PATH", tmp_path / "assistant.db")
    response = client.post("/v1/voice/resolve", json={"chat_id": "1", "transcript": "Всё, отбой, ничего не создавай"})
    assert response.json() == {"intent": "cancel_request", "event_id": None, "requires_update": False}
