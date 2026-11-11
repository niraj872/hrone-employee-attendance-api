# Employee Attendance & Analytics API - HROne Assignment

FastAPI + PyMongo implementation for the provided employee attendance assignment.

## Requirements
- Python 3.11+
- MongoDB 6.0+ (MongoDB 7 recommended)

## Windows PowerShell setup
Run these commands from the `candidate_kit` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Start MongoDB separately, for example with Docker:
docker run -d --name hrone-mongodb -p 27017:27017 -e MONGO_INITDB_DATABASE=attendance_db mongo:7
python sample_seed.py
python -m uvicorn app.main:app --port 8000 --reload
```

If the container already exists, start it with `docker start hrone-mongodb` instead of running `docker run` again.

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

## Run tests
```powershell
python -m pytest -q
python -m compileall -q app tests
```

## Environment
`MONGO_URI` and `MONGO_DB` may be configured in `.env` or the process environment. Process environment variables take precedence. Do not commit `.env` or secrets.

## Important verification note
The included unit tests and syntax check are not a substitute for running the API against MongoDB 6+/7 with the assignment's full edge cases and performance dataset. Check `REVIEW.md` before submission.



## Authentication
All employee, attendance, analytics, and admin API operations require an `x-api-key` header whose value matches the `API_KEY` environment variable. The `/health` endpoint is public. Configure `API_KEY` before starting the application, and never commit real API keys.

For a protected endpoint, pass `x-api-key: <your-api-key>` in the request headers. Missing or invalid keys return HTTP 401. The interactive API documentation is available at `/docs`.

## Deployment health checks
Configure the Render web service health-check path to `/health` (Render Dashboard → service → Settings → Health Check Path). The application does not expose a `/` route; a 404 at `/` is expected and is not a health-check result. The `/health` endpoint reports database availability and returns HTTP 503 when MongoDB is unavailable.
