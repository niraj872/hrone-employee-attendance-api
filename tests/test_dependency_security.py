"""Guards the minimum versions declared for security-sensitive dependencies.

The app declares lower bounds with ``>=`` in requirements.txt. A floor below
the version that fixes a published advisory leaves fresh installs vulnerable
and, in the case of FastAPI 0.65.2, would also downgrade to a release that
requires Pydantic v1. Keep every declared floor at or above the fixed version.
"""

import re
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

# Package -> lowest version that contains the fix for the advisories we track.
FIXED_FLOORS = {
    "httpx": "0.23.0",      # GHSA-h8pj-cxx2-jfg2
    "fastapi": "0.109.1",   # PYSEC-2024-38 (also covers GHSA-8h2j-cgx8-6xv7)
    "pymongo": "4.18.2",    # GHSA-v4x9-3549-crwv
    "uvicorn": "0.11.7",    # GHSA-33c7-2mpw-hg34, GHSA-f97h-2pfx-f59f
}


def _version_tuple(version: str) -> tuple:
    parts = [int(part) for part in re.findall(r"\d+", version)[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def _declared_floor(contents: str, package: str) -> str:
    pattern = rf"^{re.escape(package)}(?:\[[^\]]+\])?>=([0-9][0-9.]*)"
    match = re.search(pattern, contents, re.MULTILINE)
    assert match, f"{package} is not declared with a '>=' floor in requirements.txt"
    return match.group(1)


def test_declared_dependency_floors_are_at_or_above_security_fixes():
    declared = REQUIREMENTS.read_text(encoding="utf-8")
    for package, fixed in FIXED_FLOORS.items():
        floor = _declared_floor(declared, package)
        assert _version_tuple(floor) >= _version_tuple(fixed), (
            f"{package}>={floor} is below the fixed version {fixed}"
        )
