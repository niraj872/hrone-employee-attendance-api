from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

import app.main as m


def test_health_returns_200_when_mongodb_is_available(monkeypatch):
    database_type = type(m.client.admin)

    def successful_ping(self, *args, **kwargs):
        return {"ok": 1}

    monkeypatch.setattr(database_type, "command", successful_ping)

    with TestClient(m.app) as api:
        response = api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_503_when_mongodb_is_unavailable(monkeypatch):
    database_type = type(m.client.admin)

    def failed_ping(self, *args, **kwargs):
        raise ServerSelectionTimeoutError("MongoDB unavailable")

    monkeypatch.setattr(database_type, "command", failed_ping)

    with TestClient(m.app) as api:
        response = api.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "MongoDB unavailable"
