from app.healthcheck import is_ready


def test_container_health_requires_ready_ok_catalog() -> None:
    assert is_ready({"status": "ok", "ready": True}) is True
    assert is_ready({"status": "starting", "ready": False}) is False
    assert is_ready({"status": "ok", "ready": False}) is False
    assert is_ready({"status": "starting", "ready": True}) is False
    assert is_ready(None) is False
