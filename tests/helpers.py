from datetime import datetime


def employee_payload(
    code="EMP980001",
    *,
    name="Regression Test Employee",
    department="QA_REGRESSION",
    joined_on="2026-10-12",
    shift_start="09:30",
    shift_end="18:30",
):
    return {
        "emp_code": code,
        "name": name,
        "email": f"{code.lower()}@example.test",
        "department": department,
        "joined_on": joined_on,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }


def create_employee(
    client,
    code="EMP980001",
    *,
    name="Regression Test Employee",
    department="QA_REGRESSION",
    joined_on="2026-10-12",
    shift_start="09:30",
    shift_end="18:30",
):
    response = client.post(
        "/employees",
        json=employee_payload(
            code,
            name=name,
            department=department,
            joined_on=joined_on,
            shift_start=shift_start,
            shift_end=shift_end,
        ),
    )
    assert response.status_code == 201, response.text
    return response


def epoch_ms(moment: datetime):
    if not isinstance(moment, datetime):
        raise TypeError("moment must be a datetime object")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("moment must be timezone-aware")
    return int(moment.timestamp() * 1000)
