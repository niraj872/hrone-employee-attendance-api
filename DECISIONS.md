# Design decisions

1. **Indexes:** unique indexes on `employees.emp_code` and `(attendance_logs.emp_code, attendance_logs.date)` enforce natural-key uniqueness and make concurrent duplicate punch-ins race-safe. Compound indexes support department employee listing, date/employee attendance sorting, status/date filtering, and most-recent employee punch lookup. Startup index creation is idempotent.

2. **Concurrent writes:** punch-in relies on the unique employee/date index rather than a check-then-insert. Punch-out uses a conditional atomic update where `punch_out` is null. Regularization uses an optimistic `version` predicate and `$push` for history; a concurrent edit returns 409 instead of silently losing history.

3. **Leaderboard ties:** ranking uses MongoDB `$rank` over `late_count` only, then sorts by rank and `emp_code`. Limit is applied after rank calculation, so competition ranks are preserved (1, 2, 2, 4).

4. **Employees without logs:** department summary starts from employees who joined by month end and looks up logs. Such employees still contribute to headcount; their department is included with zero counts and null average work hours when no qualifying hours exist.

5. **100x scale:** filtered, sorted, paginated lists use indexed MongoDB queries; analytical record calculations use aggregation pipelines rather than loading all logs into Python. Explain output is provided for plan inspection. At larger scale, benchmark with production-like data and review index selectivity and lookup costs before adding indexes blindly.
