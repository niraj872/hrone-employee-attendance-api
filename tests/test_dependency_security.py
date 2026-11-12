"""Guard security-sensitive dependency minimums against known advisories."""

import re
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

# Package -> minimum known-safe version. Keep these aligned with the advisories
# named in comments and let pip-audit validate the full transitive dependency tree.
FIXED_FLOORS = {
    "httpx": "0.23.0",       # GHSA-h8pj-cxx2-jfg2
    "fastapi": "0.109.1",    # PYSEC-2024-38 / GHSA-8h2j-cgx8-6xv7
    "pymongo": "4.18.3",     # CVE-2026-96747/8/9 and CVE-2026-106435
    "uvicorn": "0.11.7",     # GHSA-33c7-2mpw-hg34, GHSA-f97h-2pfx-f59f
    "certifi": "2026.10.19", # GHSA-6q48-6c7w-9gw2 (eMudhra CA incident)
    "PyYAML": "6.0.3",       # Avoid vulnerable pre-6.x releases
    "anyio": "4.16.0",       # CVE-2026-63374, CVE-2026-63349, CVE-2026-64847
}


def _version_tuple(version: str) -> tuple:
    parts = [int(part) for part in re.findall(r"\d+", version)[:4]]
    return tuple(parts + [0] * (4 - len(parts)))


def _declared_floor(contents: str, package: str) -> str:
    pattern = rf"^{re.escape(package)}(?:\[[^\]]+\])?>=([0-9][0-9.]*)"
    match = re.search(pattern, contents, re.MULTILINE | re.IGNORECASE)
    assert match, f"{package} is not declared with a '>=' floor in requirements.txt"
    return match.group(1)


def test_declared_dependency_floors_are_at_or_above_security_fixes():
    declared = REQUIREMENTS.read_text(encoding="utf-8").lstrip("\ufeff")
    for package, fixed in FIXED_FLOORS.items():
        floor = _declared_floor(declared, package)
        assert _version_tuple(floor) >= _version_tuple(fixed), (
            f"{package}>={floor} is below the minimum secure version {fixed}"
        )


def test_production_python_runtime_is_pinned_to_the_ca_patched_release():
    version_file = REQUIREMENTS.parent / ".python-version"
    assert version_file.exists(), "Pin the Python runtime in .python-version"
    assert version_file.read_text(encoding="utf-8").strip() == "3.14.10"


def test_starlette_test_client_uses_httpx2_backend():
    declared = REQUIREMENTS.read_text(encoding="utf-8").lstrip("\ufeff")
    floor = _declared_floor(declared, "httpx2")
    assert _version_tuple(floor) >= _version_tuple("2.13.0"), (
        "Starlette TestClient should use httpx2 instead of deprecated httpx fallback"
    )
