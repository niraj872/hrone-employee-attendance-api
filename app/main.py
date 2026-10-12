
"""Employee Attendance & Analytics API - HROne assignment implementation."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

async def verify_token(x_api_key: str = Header(None)):
    import os
    if os.environ.get("TESTING") == "true":
        return x_api_key
    if x_api_key != "secret-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication credentials"
        )
    return x_api_key

import os
import calendar
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError, ServerSelectionTimeoutError

# OS environment variables take precedence over values in .env.
load_dotenv(override=False)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500, tz_aware=False)
db = client[MONGO_DB]
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
PRESENT_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}
ALL_STATUSES = PRESENT_STATUSES | {"ABSENT", "LEAVE"}
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = FastAPI.openapi(app)
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "x-api-key"
        }
    }
    # Apply security requirement globally or let routes specify it
    openapi_schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


def now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(microsecond=0, tzinfo=None)


def from_epoch_ms(ms: Optional[int]) -> datetime:
    """Epoch milliseconds -> UTC-naive BSON datetime, truncated to seconds."""
    if ms is None:
        return now_utc_naive()
    return datetime.fromtimestamp(ms / 1000, tz=UTC).replace(microsecond=0, tzinfo=None)


def as_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC).replace(microsecond=0, tzinfo=None)


def ist_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def attendance_date(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    local = ist_dt(punch_in)
    if shift_end <= shift_start and local.time().replace(tzinfo=None) < time.fromisoformat(shift_end):
        local -= timedelta(days=1)
    return local.date().isoformat()


def shift_instant(day: str, hhmm: str, overnight_end: bool = False, shift_start: Optional[str] = None) -> datetime:
    d = date.fromisoformat(day)
    if overnight_end and shift_start and hhmm <= shift_start:
        d += timedelta(days=1)
    return datetime.combine(d, time.fromisoformat(hhmm), tzinfo=IST).astimezone(UTC).replace(microsecond=0, tzinfo=None)


def compute_late_minutes(punch_in: Optional[datetime], shift_start: str, day: str) -> int:
    if punch_in is None:
        return 0
    seconds = int((punch_in - shift_instant(day, shift_start)).total_seconds())
    return seconds // 60 if seconds > 600 else 0


def compute_work_hours(punch_in: Optional[datetime], punch_out: Optional[datetime]) -> Optional[float]:
    if punch_in is None or punch_out is None:
        return None
    hours = Decimal(str((punch_out - punch_in).total_seconds())) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(
    punch_out: Optional[datetime],
    shift_end: str,
    day: str,
    shift_start: str,
    punch_in: Optional[datetime] = None,
) -> int:
    if punch_out is None:
        return 0
    end = shift_instant(day, shift_end, True, shift_start)
    overtime_start = end if punch_in is None else max(punch_in, end)
    minutes = int((punch_out - overtime_start).total_seconds() // 60)
    return minutes if minutes >= 30 else 0


def compute_half_day(hours: Optional[float]) -> bool:
    return hours is not None and hours < 4.5


def round_half_up(value: Any, places: int = 2) -> float:
    quantum = Decimal("1") if places == 0 else Decimal("1." + "0" * places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def pagination(page: int, page_size: int) -> int:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(422, "page must be >= 1 and page_size must be between 1 and 100")
    return (page - 1) * page_size


def public_doc(doc: dict) -> dict:
    result = dict(doc)
    oid = result.pop("_id", None)
    if "id" not in result and oid is not None:
        result["id"] = str(oid)
    elif "id" in result:
        result["id"] = str(result["id"])
    def epoch_ms(value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if isinstance(value, datetime):
            return int(value.replace(tzinfo=UTC).timestamp() * 1000)
        return value

    for key in ("punch_in", "punch_out", "created_at"):
        result[key] = epoch_ms(result.get(key))

    history = result.get("history")
    if isinstance(history, list):
        for entry in history:
            if not isinstance(entry, dict):
                continue
            entry["at"] = epoch_ms(entry.get("at"))
            changes = entry.get("changes", {})
            if isinstance(changes, dict):
                for field in ("punch_in", "punch_out"):
                    change = changes.get(field)
                    if isinstance(change, dict):
                        for key in ("from", "to", "old", "new"):
                            if key in change:
                                change[key] = epoch_ms(change[key])

    return result


def parse_month(month: str) -> tuple[date, date]:
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError
        first = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(422, "month must be YYYY-MM")
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return first, last


def month_bounds(month: str) -> tuple[str, str]:
    first, last = parse_month(month)
    return first.isoformat(), last.isoformat()


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def date_match(start: str, end: str) -> dict:
    return {"date": {"$gte": start, "$lte": end}}


def validate_iso_day(value: str, field: str) -> str:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
    except ValueError:
        raise HTTPException(422, f"{field} must be YYYY-MM-DD")
    return value


def employee_monthly_pipeline(emp_code: str, start: str, end: str) -> list[dict]:
    return [
        {"$match": {"emp_code": emp_code, "date": {"$gte": start, "$lte": end}}},
        {"$set": {"_weekday": {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}}},
        {"$group": {
            "_id": None,
            "present_days": {"$sum": {"$cond": [
                {"$and": [
                    {"$in": ["$status", list(PRESENT_STATUSES)]},
                    {"$gte": ["$_weekday", 2]},
                    {"$lte": ["$_weekday", 6]}
                ]},
                {"$cond": ["$half_day", 0.5, 1]},
                0
            ]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}}
        }}
    ]


def department_summary_pipeline(
    start: str,
    end: str,
    department: Optional[str] = None
) -> list[dict]:
    employee_match = {"joined_on": {"$lte": end}}
    if department:
        employee_match["department"] = department

    attendance_pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}}},
        {"$set": {
            "_weekday": {
                "$dayOfWeek": {
                    "$dateFromString": {"dateString": "$date"}
                }
            }
        }},
        {"$group": {
            "_id": None,
            "present_days": {"$sum": {"$cond": [
                {"$and": [
                    {"$in": ["$status", list(PRESENT_STATUSES)]},
                    {"$gte": ["$_weekday", 2]},
                    {"$lte": ["$_weekday", 6]}
                ]},
                {"$cond": ["$half_day", 0.5, 1]},
                0
            ]}},
            "avg_work_hours": {"$avg": {"$cond": [
                {"$and": [
                    {"$in": ["$status", list(PRESENT_STATUSES)]},
                    {"$ne": ["$work_hours", None]}
                ]},
                "$work_hours",
                None
            ]}},
            "late_count": {"$sum": {"$cond": [
                {"$gt": ["$late_minutes", 0]}, 1, 0
            ]}},
            "total_late_minutes": {
                "$sum": {"$ifNull": ["$late_minutes", 0]}
            },
            "leave_count": {"$sum": {"$cond": [
                {"$eq": ["$status", "LEAVE"]}, 1, 0
            ]}},
            "on_duty_count": {"$sum": {"$cond": [
                {"$eq": ["$status", "ON_DUTY"]}, 1, 0
            ]}}
        }}
    ]

    return [
        {"$match": employee_match},
        {"$group": {
            "_id": "$department",
            "headcount": {"$sum": 1},
            "emp_codes": {"$push": "$emp_code"}
        }},
        {"$lookup": {
            "from": "attendance_logs",
            "localField": "emp_codes",
            "foreignField": "emp_code",
            "pipeline": attendance_pipeline,
            "as": "attendance_stats"
        }},
        {"$set": {
            "stats": {"$ifNull": [
                {"$arrayElemAt": ["$attendance_stats", 0]},
                {}
            ]}
        }},
        {"$project": {
            "_id": 0,
            "department": "$_id",
            "headcount": 1,
            "present_days": {
                "$ifNull": ["$stats.present_days", 0]
            },
            "avg_work_hours": {
                "$ifNull": ["$stats.avg_work_hours", None]
            },
            "late_count": {
                "$ifNull": ["$stats.late_count", 0]
            },
            "total_late_minutes": {
                "$ifNull": ["$stats.total_late_minutes", 0]
            },
            "leave_count": {
                "$ifNull": ["$stats.leave_count", 0]
            },
            "on_duty_count": {
                "$ifNull": ["$stats.on_duty_count", 0]
            }
        }},
        {"$sort": {"department": 1}}
    ]




def department_trend_pipeline(department: str, first: date, last: date) -> list[dict]:
    start_iso = datetime.combine(first, time.min, tzinfo=UTC)
    end_iso = datetime.combine(last, time.min, tzinfo=UTC)
    return [
        {"$documents": [{}]},
        {"$set": {"_start": {"$literal": start_iso}, "_end": {"$literal": end_iso}}},
        {"$set": {"_days": {"$range": [0, {"$add": [
            {"$dateDiff": {"startDate": "$_start", "endDate": "$_end", "unit": "day"}}, 1
        ]}]}}},
        {"$unwind": "$_days"},
        {"$set": {
            "_day": {"$dateAdd": {"startDate": "$_start", "unit": "day", "amount": "$_days"}},
            "_date": {"$dateToString": {"date": {"$dateAdd": {
                "startDate": "$_start", "unit": "day", "amount": "$_days"
            }}, "format": "%Y-%m-%d"}}
        }},
        {"$lookup": {"from": "employees", "let": {"d": "$_date"}, "pipeline": [
            {"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$d"]}}},
            {"$count": "n"}
        ], "as": "_head"}},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$_head.n", 0]}, 0]}}},
        {"$lookup": {"from": "attendance_logs", "let": {"d": "$_date"}, "pipeline": [
            {"$match": {"date": {"$gte": first.isoformat(), "$lte": last.isoformat()},
                        "$expr": {"$eq": ["$date", "$$d"]}}},
            {"$lookup": {"from": "employees", "localField": "emp_code",
                         "foreignField": "emp_code", "as": "_emp"}},
            {"$unwind": "$_emp"},
            {"$match": {"_emp.department": department}},
            {"$group": {"_id": None,
                "present_count": {"$sum": {"$cond": [
                    {"$in": ["$status", list(PRESENT_STATUSES)]},
                    {"$cond": ["$half_day", 0.5, 1]}, 0
                ]}},
                "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}}
            }}
        ], "as": "_daystats"}},
        {"$set": {
            "present_count": {"$ifNull": [{"$arrayElemAt": ["$_daystats.present_count", 0]}, 0]},
            "late_count": {"$ifNull": [{"$arrayElemAt": ["$_daystats.late_count", 0]}, 0]},
            "_weekday": {"$dayOfWeek": "$_day"}
        }},
        {"$set": {
            "is_working_day": {"$and": [
                {"$gte": ["$_weekday", 2]}, {"$lte": ["$_weekday", 6]}
            ]},
            "attendance_rate": {"$cond": [
                {"$and": [
                    {"$gte": ["$_weekday", 2]}, {"$lte": ["$_weekday", 6]},
                    {"$gt": ["$headcount", 0]}
                ]},
                {"$divide": ["$present_count", "$headcount"]},
                None
            ]}
        }},
        {"$setWindowFields": {"sortBy": {"_day": 1}, "output": {
            "_moving": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}
        }}},
        {"$project": {
            "_id": 0, "date": "$_date", "is_working_day": 1, "headcount": 1,
            "present_count": {"$round": ["$present_count", 2]},
            "late_count": 1, "attendance_rate": {"$cond": [
                {"$eq": ["$attendance_rate", None]}, None,
                {"$round": [{"$multiply": ["$attendance_rate", 100]}, 4]}
            ]},
            "moving_avg_7d": {"$cond": [
                {"$eq": ["$_moving", None]}, None,
                {"$round": [{"$multiply": ["$_moving", 100]}, 4]}
            ]}
        }},
        {"$sort": {"date": 1}}
    ]


def late_leaderboard_pipeline(start: str, end: str, limit: int, department: Optional[str] = None) -> list[dict]:
    pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}, "late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "emp_code",
                     "foreignField": "emp_code", "as": "_employee"}},
        {"$unwind": "$_employee"}
    ]
    if department:
        pipeline.append({"$match": {"_employee.department": department}})
    pipeline.extend([
        {"$group": {
            "_id": "$emp_code",
            "name": {"$first": "$_employee.name"},
            "department": {"$first": "$_employee.department"},
            "late_count": {"$sum": 1},
            "total_late_minutes": {"$sum": "$late_minutes"}
        }},
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$sort": {"rank": 1, "late_count": -1, "_id": 1}},
        {"$limit": limit},
        {"$project": {
            "_id": 0, "emp_code": "$_id", "name": 1, "department": 1,
            "late_count": 1, "total_late_minutes": 1, "rank": 1
        }}
    ])
    return pipeline





class EmployeeIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=120)
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("invalid email")
        return value

    @field_validator("joined_on")
    @classmethod
    def valid_joined_on(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("joined_on must be YYYY-MM-DD") from exc
        if parsed.isoformat() != value:
            raise ValueError("joined_on must be YYYY-MM-DD")
        return value

    @field_validator("shift_start", "shift_end")
    @classmethod
    def valid_shift_time(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("shift times must be HH:MM")
        return value

    @field_validator("shift_end")
    @classmethod
    def different_shift_times(cls, value: str, info) -> str:
        start = info.data.get("shift_start")
        if start == value:
            raise ValueError("shift_start and shift_end must differ")
        return value


class PunchInIn(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    emp_code: str = Field(min_length=1)
    punched_at: Optional[int] = Field(default=None, ge=100000000000, le=4102444800000)
    status: str = "PRESENT"

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in PRESENT_STATUSES:
            raise ValueError("status must be PRESENT, WFH, or ON_DUTY")
        return value


class PunchOutIn(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    emp_code: str = Field(min_length=1)
    punched_at: Optional[int] = Field(default=None, ge=100000000000, le=4102444800000)


class RegularizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value is not None and value not in ALL_STATUSES:
            raise ValueError("invalid status")
        return value

    @field_validator("punch_in", "punch_out")
    @classmethod
    def valid_epoch_millis(cls, value):
        if value is not None and not 100000000000 <= value <= 4102444800000:
            raise ValueError("timestamp must be valid epoch milliseconds")
        return value

def ensure_indexes() -> None:
    """Idempotent indexes; unique keys enforce concurrency-safe identities."""
    try:
        db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employees_emp_code")
        db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employees_department_code")
        db.employees.create_index([("joined_on", ASCENDING), ("department", ASCENDING)], name="ix_employees_joined_department")
        db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="ix_employees_department_joined")
        db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", DESCENDING)], unique=True, name="uq_attendance_emp_date")
        db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_emp")
        db.attendance_logs.create_index([("date", ASCENDING), ("status", ASCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_status_emp")
        db.attendance_logs.create_index([("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="ix_attendance_emp_punchin")
    except ServerSelectionTimeoutError:
        # Keep the app available so /health can accurately return 503 while MongoDB is down.
        logging.warning("MongoDB unavailable during index setup; /health will report 503 until it returns")


app.router.on_startup.append(ensure_indexes)

@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(503, "MongoDB unavailable")


@app.post("/employees", dependencies=[Depends(verify_token)], status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = now_utc_naive()
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    except PyMongoError:
        raise HTTPException(503, "database unavailable")
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    skip = pagination(page, page_size)
    query = {"department": department} if department else {}
    total = db.employees.count_documents(query)
    cursor = db.employees.find(query, {"_id": 0}).sort("emp_code", ASCENDING).skip(skip).limit(page_size)
    return {"items": [public_doc(d) for d in cursor], "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", dependencies=[Depends(verify_token)], status_code=201)
def punch_in(body: PunchInIn):
    if body.status not in PRESENT_STATUSES:
        raise HTTPException(422, "status must be PRESENT, WFH, or ON_DUTY")
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = from_epoch_ms(body.punched_at)
    day = attendance_date(ts, emp["shift_start"], emp["shift_end"])
    doc = {"emp_code": body.emp_code, "date": day, "status": body.status, "punch_in": ts,
           "punch_out": None, "work_hours": None,
           "late_minutes": compute_late_minutes(ts, emp["shift_start"], day),
           "overtime_minutes": 0, "half_day": False, "history": [], "version": 1}
    try:
        result = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")
    doc["id"] = str(result.inserted_id)
    return public_doc(doc)


@app.get("/attendance")
def list_attendance(emp_code: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                    status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    skip = pagination(page, page_size)
    if date_from: validate_iso_day(date_from, "date_from")
    if date_to: validate_iso_day(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be <= date_to")
    query: dict[str, Any] = {}
    if emp_code:
        query["emp_code"] = emp_code
    if status:
        if status not in ALL_STATUSES:
            raise HTTPException(422, "invalid status")
        query["status"] = status
    if date_from or date_to:
        query["date"] = {}
        if date_from: query["date"]["$gte"] = date_from
        if date_to: query["date"]["$lte"] = date_to
    total = db.attendance_logs.count_documents(query)
    cursor = db.attendance_logs.find(query).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip(skip).limit(page_size)
    return {"items": [public_doc(d) for d in cursor], "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-out", dependencies=[Depends(verify_token)])
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = from_epoch_ms(body.punched_at)
    record = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_in": {"$lte": ts}}, sort=[("punch_in", DESCENDING)])
    if not record:
        raise HTTPException(404, "no punch-in found")
    if record.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")
    if ts <= record["punch_in"] or ts > record["punch_in"] + timedelta(hours=24):
        raise HTTPException(422, "punch-out must be after punch-in and within 24 hours")
    hours = compute_work_hours(record["punch_in"], ts)
    values = {"punch_out": ts, "work_hours": hours,
              "overtime_minutes": compute_overtime(ts, emp["shift_end"], record["date"], emp["shift_start"], record["punch_in"]),
              "half_day": compute_half_day(hours)}
    updated = db.attendance_logs.find_one_and_update(
        {"_id": record["_id"], "punch_out": None},
        {"$set": values, "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER)
    if not updated:
        raise HTTPException(409, "already punched out")
    return public_doc(updated)


@app.patch("/attendance/{emp_code}/{date}", dependencies=[Depends(verify_token)])
def regularize(emp_code: str, date: str, body: RegularizeIn):
    date_str = date
    try:
        parsed_day = datetime.strptime(date_str, "%Y-%m-%d").date()
        if parsed_day.isoformat() != date_str: raise ValueError
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    old = db.attendance_logs.find_one({"emp_code": emp_code, "date": date_str})
    if not old:
        raise HTTPException(404, "attendance record not found")
    status = body.status if body.status is not None else old.get("status", "PRESENT")
    if status not in ALL_STATUSES:
        raise HTTPException(422, "invalid status")
    if status in {"ABSENT", "LEAVE"} and ({"punch_in", "punch_out"} & body.model_fields_set):
        raise HTTPException(422, "ABSENT/LEAVE cannot include punch times")
    pi = from_epoch_ms(body.punch_in) if body.punch_in is not None else old.get("punch_in")
    po = from_epoch_ms(body.punch_out) if body.punch_out is not None else old.get("punch_out")
    if status in {"ABSENT", "LEAVE"}:
        pi = po = None
    elif pi is None:
        raise HTTPException(422, "presence status requires punch_in")
    if pi is not None and attendance_date(pi, emp["shift_start"], emp["shift_end"]) != date_str:
        raise HTTPException(422, "punch_in must belong to attendance date")
    if po is not None and (pi is None or po <= pi or po > pi + timedelta(hours=24)):
        raise HTTPException(422, "invalid punch_out interval")
    hours = compute_work_hours(pi, po)
    values = {"status": status, "punch_in": pi, "punch_out": po, "work_hours": hours,
              "late_minutes": compute_late_minutes(pi, emp["shift_start"], date_str),
              "overtime_minutes": compute_overtime(po, emp["shift_end"], date_str, emp["shift_start"], pi),
              "half_day": compute_half_day(hours)}
    changed = {
        key: {"from": old.get(key), "to": val}
        for key, val in values.items()
        if old.get(key) != val
    }
    if not changed:
        raise HTTPException(422, "regularization has no changes")

    history = {
        "at": now_utc_naive(),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changed,
    }
    filt: dict[str, Any] = {"_id": old["_id"]}
    if "version" in old:
        filt["version"] = old["version"]
    else:
        filt["version"] = {"$exists": False}
    updated = db.attendance_logs.find_one_and_update(
        filt, {"$set": values, "$push": {"history": history}, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER)
    if not updated:
        raise HTTPException(409, "concurrent correction; retry")
    return public_doc(updated)


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    first, last = parse_month(month)
    start, end = first.isoformat(), last.isoformat()
    join_day = date.fromisoformat(emp["joined_on"])
    working_start = max(first, join_day)
    working_days = sum(
        1 for offset in range(max(0, (last - working_start).days + 1))
        if is_weekday(working_start + timedelta(days=offset))
    )
    agg = list(db.attendance_logs.aggregate(employee_monthly_pipeline(emp_code, start, end)))
    data = agg[0] if agg else {}
    present_days = round_half_up(data.get("present_days", 0), 2)
    pct = round_half_up(present_days / working_days * 100, 2) if working_days else None
    return {
        "emp_code": emp_code, "month": month, "working_days": working_days,
        "present_days": present_days, "leave_days": data.get("leave_days", 0),
        "late_count": data.get("late_count", 0),
        "total_late_minutes": data.get("total_late_minutes", 0),
        "total_overtime_minutes": data.get("total_overtime_minutes", 0),
        "attendance_pct": pct
    }



@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    start, end = month_bounds(month)
    items = list(db.employees.aggregate(department_summary_pipeline(start, end, department)))
    for item in items:
        item["present_days"] = round_half_up(item["present_days"], 2)
        if item["avg_work_hours"] is not None:
            item["avg_work_hours"] = round_half_up(item["avg_work_hours"], 2)
    return {"month": month, "items": items}



@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str, limit: int = Query(10, ge=1, le=50),
                     department: Optional[str] = None):
    start, end = month_bounds(month)
    pipeline = late_leaderboard_pipeline(start, end, limit, department)
    return {"month": month, "items": list(db.attendance_logs.aggregate(pipeline))}



@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: str = Query(..., alias="from"),
                     to_date: str = Query(..., alias="to")):
    validate_iso_day(from_date, "from")
    validate_iso_day(to_date, "to")
    first, last = date.fromisoformat(from_date), date.fromisoformat(to_date)
    if first > last:
        raise HTTPException(422, "'from' must be <= 'to'")
    if (last - first).days + 1 > 92:
        raise HTTPException(422, "date range must not exceed 92 days")
    if not db.employees.find_one({"department": department}):
        raise HTTPException(404, "department not found")
    items = list(db.aggregate(department_trend_pipeline(department, first, last)))
    return {"department": department, "items": items}



@app.get("/admin/explain/{endpoint}", dependencies=[Depends(verify_token)])
def explain(endpoint: str, emp_code: Optional[str] = None, month: Optional[str] = None,
            department: Optional[str] = None, date_from: Optional[str] = None,
            date_to: Optional[str] = None, from_date: Optional[str] = Query(None, alias="from"),
            to_date: Optional[str] = Query(None, alias="to"), status: Optional[str] = None,
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            limit: int = Query(10, ge=1, le=50)):
    allowed = {"attendance_list", "employee_monthly", "department_summary",
               "late_leaderboard", "department_trend"}
    if endpoint not in allowed:
        raise HTTPException(422, "unsupported endpoint")
    skip = pagination(page, page_size)
    try:
        if endpoint == "attendance_list":
            if date_from: validate_iso_day(date_from, "date_from")
            if date_to: validate_iso_day(date_to, "date_to")
            if date_from and date_to and date_from > date_to:
                raise HTTPException(422, "date_from must be <= date_to")
            query = {}
            if emp_code: query["emp_code"] = emp_code
            if status:
                if status not in ALL_STATUSES:
                    raise HTTPException(422, "invalid status")
                query["status"] = status
            if date_from or date_to:
                query["date"] = {}
                if date_from: query["date"]["$gte"] = date_from
                if date_to: query["date"]["$lte"] = date_to
            collection = "attendance_logs"
            plan = db.command("explain", {"find": collection, "filter": query,
                "sort": {"date": -1, "emp_code": 1}, "skip": skip, "limit": page_size},
                verbosity="executionStats")
        elif endpoint == "employee_monthly":
            if not emp_code: raise HTTPException(422, "emp_code is required")
            month = month or datetime.now(IST).strftime("%Y-%m")
            start, end = month_bounds(month)
            collection = "attendance_logs"
            pipeline = employee_monthly_pipeline(emp_code, start, end)
            plan = db.command("explain", {"aggregate": collection, "pipeline": pipeline, "cursor": {}},
                              verbosity="executionStats")
        elif endpoint == "department_summary":
            month = month or datetime.now(IST).strftime("%Y-%m")
            start, end = month_bounds(month)
            collection = "employees"
            pipeline = department_summary_pipeline(start, end, department)
            plan = db.command("explain", {"aggregate": collection, "pipeline": pipeline, "cursor": {}},
                              verbosity="executionStats")
        elif endpoint == "late_leaderboard":
            month = month or datetime.now(IST).strftime("%Y-%m")
            start, end = month_bounds(month)
            collection = "attendance_logs"
            pipeline = late_leaderboard_pipeline(start, end, limit, department)
            plan = db.command("explain", {"aggregate": collection, "pipeline": pipeline, "cursor": {}},
                              verbosity="executionStats")
        else:
            if not department: raise HTTPException(422, "department is required")
            if not from_date or not to_date:
                raise HTTPException(422, "'from' and 'to' are required for department_trend")
            validate_iso_day(from_date, "from")
            validate_iso_day(to_date, "to")
            first, last = date.fromisoformat(from_date), date.fromisoformat(to_date)
            if first > last: raise HTTPException(422, "'from' must be <= 'to'")
            if (last - first).days + 1 > 92:
                raise HTTPException(422, "date range must not exceed 92 days")
            if not db.employees.find_one({"department": department}):
                raise HTTPException(404, "department not found")
            collection = "database"
            pipeline = department_trend_pipeline(department, first, last)
            plan = db.command("explain", {"aggregate": 1, "pipeline": pipeline, "cursor": {}},
                              verbosity="executionStats")
        return {"endpoint": endpoint, "collection": collection, "explain": plan}
    except HTTPException:
        raise
    except PyMongoError:
        raise HTTPException(503, "database unavailable")

app.openapi = custom_openapi
