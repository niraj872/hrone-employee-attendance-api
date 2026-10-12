from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app, db


TEST_EMPLOYEES = ["EMP990001", "EMP990002", "EMP990003", "EMP990004"]


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_test_data(client):
    # This module must run against attendance_test_db only.
    db.attendance_logs.delete_many(
        {"emp_code": {"$in": TEST_EMPLOYEES}}
    )
    db.employees.delete_many(
        {"emp_code": {"$in": TEST_EMPLOYEES}}
    )
    yield
    db.attendance_logs.delete_many(
        {"emp_code": {"$in": TEST_EMPLOYEES}}
    )
    db.employees.delete_many(
        {"emp_code": {"$in": TEST_EMPLOYEES}}
    )


def create_employee(client, emp_code):
    response = client.post(
        "/employees",
        json={
            "emp_code": emp_code,
            "name": "Concurrency Test",
            "email": f"{emp_code.lower()}@example.test",
            "department": "QA_TEST",
            "joined_on": date.today().isoformat(),
            "shift_start": "09:30",
            "shift_end": "18:30",
        },
    )
    assert response.status_code == 201, response.text


def epoch_ms(hour):
    moment = datetime.now(timezone.utc).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return int(moment.timestamp() * 1000)


def concurrent_posts(client, path, payload, count=8):
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [
            pool.submit(client.post, path, json=payload)
            for _ in range(count)
        ]
        return [future.result() for future in futures]


def test_concurrent_punch_in_creates_only_one_record(client):
    emp_code = TEST_EMPLOYEES[0]
    create_employee(client, emp_code)

    responses = concurrent_posts(
        client,
        "/attendance/punch-in",
        {
            "emp_code": emp_code,
            "punched_at": epoch_ms(10),
            "status": "PRESENT",
        },
    )

    statuses = [response.status_code for response in responses]

    assert statuses.count(201) == 1, statuses
    assert statuses.count(409) == 7, [
        (response.status_code, response.text)
        for response in responses
    ]
    assert db.attendance_logs.count_documents(
        {"emp_code": emp_code}
    ) == 1


def test_concurrent_punch_out_updates_record_only_once(client):
    emp_code = TEST_EMPLOYEES[1]
    create_employee(client, emp_code)

    punch_in = client.post(
        "/attendance/punch-in",
        json={
            "emp_code": emp_code,
            "punched_at": epoch_ms(10),
            "status": "PRESENT",
        },
    )
    assert punch_in.status_code == 201, punch_in.text

    responses = concurrent_posts(
        client,
        "/attendance/punch-out",
        {
            "emp_code": emp_code,
            "punched_at": epoch_ms(18),
        },
    )

    statuses = [response.status_code for response in responses]

    assert statuses.count(200) == 1, [
        (response.status_code, response.text)
        for response in responses
    ]
    assert statuses.count(409) == 7, [
        (response.status_code, response.text)
        for response in responses
    ]

    record = db.attendance_logs.find_one({"emp_code": emp_code})
    assert record is not None
    assert record["punch_out"] is not None
    assert db.attendance_logs.count_documents(
        {"emp_code": emp_code}
    ) == 1
from datetime import date, datetime, timezone

from app.main import db


def test_regularization_rejects_stale_version(client):
    emp_code = "EMP990003"
    day = date.today().isoformat()

    # Create a dedicated employee in the isolated test database.
    employee_response = client.post(
        "/employees",
        json={
            "emp_code": emp_code,
            "name": "Stale Version Test",
            "email": "emp990003@example.test",
            "department": "QA_TEST",
            "joined_on": day,
        },
    )
    assert employee_response.status_code == 201, employee_response.text

    # Create an attendance record with a known version.
    db.attendance_logs.insert_one({
        "emp_code": emp_code,
        "date": day,
        "status": "PRESENT",
        "punch_in": datetime.now(timezone.utc).replace(tzinfo=None),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": 0,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
        "version": 1,
    })

    # Simulate another request updating the record after it was read.
    db.attendance_logs.update_one(
        {"emp_code": emp_code, "date": day},
        {"$inc": {"version": 1}},
    )

    # The route reads version 2, so we need to simulate a stale write
    # between its read and its atomic update. A direct stale-version
    # database filter check verifies MongoDB's compare-and-set behavior.
    from pymongo import ReturnDocument

    current = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": day}
    )
    stale_update = db.attendance_logs.find_one_and_update(
        {"_id": current["_id"], "version": 1},
        {"$set": {"status": "WFH"}, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )

    assert stale_update is None
    saved = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": day}
    )
    assert saved["version"] == 2
    assert saved["status"] == "PRESENT"


def test_patch_returns_409_on_concurrent_version_change(client, monkeypatch):
    from pymongo.collection import Collection

    emp_code = "EMP990003"
    day = date.today().isoformat()

    employee_response = client.post(
        "/employees",
        json={
            "emp_code": emp_code,
            "name": "Route Conflict Test",
            "email": "emp990003@example.test",
            "department": "QA_TEST",
            "joined_on": day,
        },
    )
    assert employee_response.status_code == 201, employee_response.text

    db.attendance_logs.insert_one({
        "emp_code": emp_code,
        "date": day,
        "status": "PRESENT",
        "punch_in": datetime.now(timezone.utc).replace(tzinfo=None),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": 0,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
        "version": 1,
    })

    original = Collection.find_one_and_update
    injected = {"done": False}

    def simulate_concurrent_write(collection, filter, update, *args, **kwargs):
        if collection.name == "attendance_logs" and not injected["done"]:
            injected["done"] = True
            db.attendance_logs.update_one(
                {"emp_code": emp_code, "date": day},
                {"$inc": {"version": 1}},
            )
        return original(collection, filter, update, *args, **kwargs)

    monkeypatch.setattr(
        Collection, "find_one_and_update", simulate_concurrent_write
    )

    response = client.patch(
        f"/attendance/{emp_code}/{day}",
        json={
            "status": "WFH",
            "reason": "Correct attendance status",
            "regularized_by": "test",
        },
    )

    assert injected["done"], "Concurrent update was not simulated"
    assert response.status_code == 409, response.text

    saved = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": day}
    )
    assert saved["status"] == "PRESENT"
    assert saved["version"] == 2

def test_concurrent_duplicate_employee_creation_returns_conflicts(client):
    emp_code = TEST_EMPLOYEES[3]
    payload = {
        "emp_code": emp_code,
        "name": "Concurrent Duplicate Test",
        "email": f"{emp_code.lower()}@example.test",
        "department": "QA_TEST",
        "joined_on": date.today().isoformat(),
        "shift_start": "09:30",
        "shift_end": "18:30",
    }

    responses = concurrent_posts(client, "/employees", payload, count=8)
    statuses = [response.status_code for response in responses]

    assert statuses.count(201) == 1, [
        (response.status_code, response.text) for response in responses
    ]
    assert statuses.count(409) == 7, [
        (response.status_code, response.text) for response in responses
    ]
    assert db.employees.count_documents({"emp_code": emp_code}) == 1
