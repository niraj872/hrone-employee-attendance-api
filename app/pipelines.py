from datetime import date, datetime, time, timezone
from typing import Optional

UTC = timezone.utc
PRESENT_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}


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
