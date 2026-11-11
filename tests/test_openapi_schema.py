import yaml

from app.main import app, verify_token


def test_openapi_yaml_matches_application_schema():
    schema = app.openapi()
    yaml_schema = yaml.safe_load(
        (app_root() / "openapi.yaml").read_text(encoding="utf-8")
    )
    assert yaml_schema == schema


def test_openapi_metadata_and_endpoints():
    schema = app.openapi()

    assert schema["openapi"] == "3.1.0"
    assert schema["info"]["title"] == app.title
    assert schema["info"]["version"] == app.version
    assert len(schema["paths"]) == 11


def test_openapi_security_matches_route_dependencies():
    schema = app.openapi()

    expected_protected = {
        (route.path, method.lower())
        for route in app.routes
        if getattr(route, "dependencies", None)
        for method in (route.methods or set())
        if any(
            getattr(dependency, "dependency", None) is verify_token
            for dependency in route.dependencies
        )
    }

    actual_protected = {
        (path, method)
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if {"ApiKeyAuth": []} in operation.get("security", [])
    }

    assert actual_protected == expected_protected
    assert len(actual_protected) == 11
    assert ('/health', 'get') not in actual_protected


def app_root():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent