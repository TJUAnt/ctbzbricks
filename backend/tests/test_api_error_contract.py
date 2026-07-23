"""Contract tests for machine-readable, locale-independent API errors."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.api.errors import DomainError, ERROR_RESPONSES, install_error_handlers


ROOT = Path(__file__).resolve().parents[2]
BACKEND_CONFIG = ROOT / "backend" / "config"
FRONTEND_RESOURCES = ROOT / "frontend" / "src" / "i18n" / "resources"
MACHINE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
PUBLIC_CODE_PREFIXES = (
    "auth.",
    "common.",
    "component_repo.",
    "dem_lego_design.",
    "dem_slope_catalog.",
    "fitting_candidate_profile.",
    "fitting_candidate_recall.",
    "lego_design.",
    "lego_heightmap.",
    "ldraw.",
    "mesh_model.",
    "model_fitting.",
    "part_shape_profile.",
    "part_search.",
    "pixel_art.",
    "request.",
    "submodel.",
    "terrain.",
)


class ValidationPayload(BaseModel):
    count: int


def contract_app() -> FastAPI:
    app = FastAPI(responses=ERROR_RESPONSES)
    install_error_handlers(app)

    @app.get("/domain")
    def domain_error() -> None:
        raise DomainError("terrain.job_not_found", {"jobId": "job-42"}, 404)

    @app.post("/validation")
    def validation(payload: ValidationPayload) -> ValidationPayload:
        return payload

    @app.get("/unknown")
    def unknown_error() -> None:
        raise RuntimeError("private database details")

    return app


def test_domain_error_response_contains_code_params_and_trace_id() -> None:
    response = TestClient(contract_app()).get("/domain")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "terrain.job_not_found",
            "params": {"jobId": "job-42"},
            "traceId": response.headers["X-Trace-Id"],
        }
    }
    assert response.headers["X-Trace-Id"].startswith("req_")


def test_validation_errors_have_stable_field_paths_codes_and_params() -> None:
    response = TestClient(contract_app()).post("/validation", json={})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "request.validation_failed"
    assert error["params"]["errors"] == [
        {"path": ["body", "count"], "code": "request.validation.missing", "params": {}}
    ]


def test_unknown_errors_do_not_leak_exception_text() -> None:
    response = TestClient(contract_app(), raise_server_exceptions=False).get("/unknown")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "common.internal_error"
    assert "private database details" not in response.text


def test_openapi_documents_the_unified_error_schema() -> None:
    responses = contract_app().openapi()["paths"]["/domain"]["get"]["responses"]

    for status in ("400", "401", "403", "404", "409", "413", "422", "500", "502"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ApiErrorResponse"}


def test_backend_error_codes_have_matching_english_and_chinese_resources() -> None:
    english = load_error_resources("en-US")
    chinese = load_error_resources("zh-CN")
    assert english.keys() == chinese.keys()
    english_tasks = load_resources("en-US", "tasks")
    chinese_tasks = load_resources("zh-CN", "tasks")
    assert english_tasks.keys() == chinese_tasks.keys()

    config_codes = set()
    for config_path in BACKEND_CONFIG.glob("*.json"):
        collect_error_codes(json.loads(config_path.read_text(encoding="utf-8")), config_codes)

    backend_codes = config_codes | source_error_codes()
    missing = sorted(backend_codes - english.keys() - english_tasks.keys())
    assert not missing, f"Missing structured message resources: {missing}"


def test_public_routes_do_not_construct_legacy_http_error_details() -> None:
    public_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "backend" / "src" / "api" / "routes").glob("*.py")
    )
    auth_source = (ROOT / "backend" / "src" / "auth" / "current_user.py").read_text(encoding="utf-8")

    assert "HTTPException" not in public_source
    assert "detail=" not in public_source
    assert "HTTPException" not in auth_source
    assert "detail=" not in auth_source


def load_error_resources(locale: str) -> dict[str, str]:
    return load_resources(locale, "errors")


def load_resources(locale: str, namespace: str) -> dict[str, str]:
    path = FRONTEND_RESOURCES / locale / f"{namespace}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def collect_error_codes(value: object, codes: set[str], inside_errors: bool = False) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            collect_error_codes(child, codes, inside_errors or key == "errors")
    elif inside_errors and isinstance(value, str) and MACHINE_CODE_PATTERN.fullmatch(value):
        codes.add(value)


def source_error_codes() -> set[str]:
    codes: set[str] = set()
    source_root = ROOT / "backend" / "src"
    quoted_code = re.compile(r"[\"']([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)[\"']")
    dynamic_component_operation = re.compile(r"component_repo_operation_error\([^\n]+\n?\s*[^,]+,\s*[\"']([^\"']+)[\"']")
    for path in source_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for code in quoted_code.findall(source):
            if code.startswith(PUBLIC_CODE_PREFIXES) and not code.endswith((".json", ".geojson")):
                codes.add(code)
        for operation in dynamic_component_operation.findall(source):
            codes.add(f"component_repo.{operation}_failed")
    return codes
