import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key")
    with TestClient(app) as test_client:
        test_client.headers.update({"x-api-key": "test-api-key"})
        yield test_client
