import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "main.py"
spec = importlib.util.spec_from_file_location("ri_assistant_main", MODULE_PATH)
assert spec and spec.loader
main = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = main
spec.loader.exec_module(main)
app = main.app


client = TestClient(app)


def test_edit_state_forces_update(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "assistant.db")
    assert client.post("/v1/edit/begin", json={"chat_id": "1", "event_id": "event-1"}).status_code == 200
    response = client.post("/v1/voice/resolve", json={"chat_id": "1", "transcript": "Переименуй в встречу"})
    assert response.json() == {"intent": "update_event", "event_id": "event-1", "requires_update": True}


def test_cancel_never_creates_event(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "assistant.db")
    response = client.post("/v1/voice/resolve", json={"chat_id": "1", "transcript": "Всё, отбой, ничего не создавай"})
    assert response.json() == {"intent": "cancel_request", "event_id": None, "requires_update": False}


def test_day_plan_keeps_event_buffer_and_places_tasks(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "assistant.db")
    response = client.post(
        "/v1/day-plan",
        json={
            "date": "2026-09-20",
            "tasks": [
                {"title": "Подготовить документы", "duration_minutes": 60},
                {"title": "Забрать заказ", "duration_minutes": 30, "location": "Тверская"},
            ],
            "calendar": [
                {
                    "start": "2026-09-20T10:00:00+03:00",
                    "end": "2026-09-20T11:00:00+03:00",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["planned"]] == ["Забрать заказ", "Подготовить документы"]
    assert body["unplanned"] == []
    # The meeting buffers 09:30–11:30, so no task may intrude into it.
    assert body["planned"][1]["end"] == "2026-09-20T09:30:00+03:00"
    assert body["free_slots"][0]["start"] == "2026-09-20T11:30:00+03:00"


def test_voice_tool_call_allows_only_declared_actions():
    action = main.parse_voice_tool_call(
        "calendar_search", '{"query":"встреча с Иваном","date_hint":"завтра"}'
    )
    assert action.action == "calendar_search"
    assert action.arguments["query"] == "встреча с Иваном"


def test_voice_tool_call_rejects_unknown_action():
    try:
        main.parse_voice_tool_call("run_shell", "{}")
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unknown tool must be rejected")


def test_voice_instruction_supplies_current_date_and_timezone():
    instruction = main.voice_instruction(
        main.VoiceInterpretRequest(chat_id="1", transcript="Поставь встречу завтра в 10")
    )
    assert main.datetime.now(main.MOSCOW).date().isoformat() in instruction
    assert "ISO 8601 datetimes with the +03:00 offset" in instruction
