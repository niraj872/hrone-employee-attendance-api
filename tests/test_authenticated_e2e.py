from datetime import datetime, timezone

from app.main import db
from tests.helpers import employee_payload, epoch_ms


EMP_CODE = "EMP982024"
DEPARTMENT = "AUTH_E2E_TEST"


def test_authenticated_employee_attendance_round_trip(client):
    """Exercise create -> list -> punch-in -> punch-out -> read with the CI API key."""
    # Guard cleanup to ensure this test can only touch the dedicated CI database.
    assert db.name == "attendance_test_db", (
        f"Refusing end-to-end test against database: {db.name}"
    )

    db.attendance_logs.delete_many({"emp_code": EMP_CODE})
    db.employees.delete_many({"emp_code": EMP_CODE})

    try:
        employee = client.post(
            "/employees",
            json=employee_payload(
                EMP_CODE,
                name="Authenticated E2E Employee",
                department=DEPARTMENT,
                joined_on="2026-11-12",
            ),
        )
        assert employee.status_code == 201, employee.text

        employee_list = client.get(
            "/employees",
            params={"department": DEPARTMENT},
        )
        assert employee_list.status_code == 200, employee_list.text
        assert any(
            item["emp_code"] == EMP_CODE
            for item in employee_list.json()["items"]
        )

        punch_in = client.post(
            "/attendance/punch-in",
            json={
                "emp_code": EMP_CODE,
                "punched_at": epoch_ms(
                    datetime(2026, 11, 12, 4, 0, tzinfo=timezone.utc)
                ),
                "status": "PRESENT",
            },
        )
        assert punch_in.status_code == 201, punch_in.text

        punch_out = client.post(
            "/attendance/punch-out",
            json={
                "emp_code": EMP_CODE,
                "punched_at": epoch_ms(
                    datetime(2026, 11, 12, 13, 0, tzinfo=timezone.utc)
                ),
            },
        )
        assert punch_out.status_code == 200, punch_out.text
        assert punch_out.json()["work_hours"] == 9.0

        attendance = client.get(
            "/attendance",
            params={"emp_code": EMP_CODE},
        )
        assert attendance.status_code == 200, attendance.text
        records = attendance.json()["items"]
        assert len(records) == 1
        assert records[0]["emp_code"] == EMP_CODE
        assert records[0]["punch_out"] is not None
    finally:
        db.attendance_logs.delete_many({"emp_code": EMP_CODE})
        db.employees.delete_many({"emp_code": EMP_CODE})
