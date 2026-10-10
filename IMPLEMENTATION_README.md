# HROne Employee Attendance & Analytics API

This implementation uses FastAPI, PyMongo and MongoDB. It includes the required route surface:

- `GET /health`
- `POST /employees`, `GET /employees`
- `POST /attendance/punch-in`, `POST /attendance/punch-out`, `GET /attendance`
- `PATCH /attendance/{emp_code}/{date}`
- `GET /analytics/employees/{emp_code}/monthly`
- `GET /analytics/departments/summary`
- `GET /analytics/leaderboard/late`
- `GET /analytics/departments/{department}/trend`
- `GET /admin/explain/{endpoint}`

## Local run

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --port 8000
```

MongoDB defaults to `mongodb://localhost:27017`, database `attendance_db`. Set `MONGO_URI` and `MONGO_DB` as process environment variables to override `.env` settings.

## Important implementation notes

- UTC-naive datetimes are stored in BSON; epoch milliseconds are used by the punch APIs.
- IST determines attendance dates and shift boundaries, including overnight shifts.
- Unique compound indexes make same-employee/day punch-in race-safe.
- Punch-out uses an atomic conditional update; regularization uses optimistic version checks and appends history atomically.
- Lists are sorted/paginated in MongoDB. Monthly, department, leaderboard, and trend record calculations use aggregation pipelines.
- Department trend generates its calendar date spine and moving average in MongoDB.

Before submission, run the implementation against the actual provided seed data and MongoDB version. `REVIEW.md` contains the release checks that require the assignment dataset and concurrent/performance testing.
