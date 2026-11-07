from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from app.main import app

OUTPUT = ROOT / "openapi.yaml"


def main():
    schema = app.openapi()
    OUTPUT.write_text(
        yaml.safe_dump(schema, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Generated: {OUTPUT}")
    print(f"OpenAPI version: {schema['openapi']}")
    print(f"Endpoints: {len(schema['paths'])}")


if __name__ == "__main__":
    main()
