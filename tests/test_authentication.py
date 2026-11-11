import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    "path",
    [
        "/employees",
        "/analytics/employees/EMP0001/monthly?month=2026-11",
        "/analytics/departments/summary?month=2026-11",
        "/analytics/leaderboard/late?month=2026-11",
        "/analytics/departments/QA/trend?from=2026-11-01&to=2026-11-07",
    ],
)
def test_data_read_routes_reject_missing_api_key(path, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key")

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing authentication credentials"
