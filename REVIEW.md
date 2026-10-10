# Implementation review checklist

The implementation includes all routes named in the assignment contract, core calculations, MongoDB aggregation pipelines, natural-key indexes, optimistic regularization updates, and concurrency-safe punch-in/out writes.

Before submission, run and record these checks against MongoDB 6+/7:

- [ ] `python -m compileall -q app tests`
- [ ] `python -m pytest -q`
- [ ] `/health` returns 200 when MongoDB is reachable and 503 when unavailable.
- [ ] Concurrent duplicate employee and same-employee/same-date punch-in requests produce one success and conflicts for duplicates.
- [ ] Concurrent punch-out requests produce only one success.
- [ ] Concurrent regularization does not lose history entries; stale updates return 409.
- [ ] Verify monthly/department results for weekends, half-days, mid-month joiners, no-log employees, ties, missing weekdays, and overnight shifts.
- [ ] Run all `/admin/explain/{endpoint}` variants on the 100k-record fixture and inspect execution stats/index use.
- [ ] Confirm startup index creation succeeds with the actual dataset (unique indexes require no existing duplicate natural keys).
- [ ] Check response schemas and status codes against `openapi.yaml`.

**Verification status:** Python syntax compilation was checked when this bundle was prepared. Full pytest/MongoDB integration and 100k-record performance verification have not been completed here. Do not treat those checks as passed until run locally.
