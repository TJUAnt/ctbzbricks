"""M3 contracts for locale-independent asynchronous task data."""

import pytest
from pydantic import ValidationError

from src.api.schemas.task import TaskContextRequest
from src.i18n.messages import error_from_exception, progress
from src.model.models import (
    ComponentImport,
    ComponentUploadSession,
    FittingCandidateProfile,
    LDrawFile,
    LDrawFileReference,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
    LDrawShadowFile,
    LDrawShadowInclude,
    LDrawShadowMetaRaw,
    ModelFittingJob,
)


def test_task_context_normalizes_supported_locale_and_validates_timezone() -> None:
    assert TaskContextRequest(locale="en-GB", timezone="UTC").model_dump() == {
        "locale": "en-US",
        "timezone": "UTC",
    }
    assert TaskContextRequest(locale="zh-Hant", timezone="Asia/Shanghai").model_dump() == {
        "locale": "zh-CN",
        "timezone": "Asia/Shanghai",
    }
    with pytest.raises(ValidationError):
        TaskContextRequest(locale="fr-FR", timezone="UTC")
    with pytest.raises(ValidationError):
        TaskContextRequest(locale="en-US", timezone="Mars/Olympus")


def test_progress_payload_is_identical_for_every_task_locale() -> None:
    english_context = TaskContextRequest(locale="en-US", timezone="UTC")
    chinese_context = TaskContextRequest(locale="zh-CN", timezone="Asia/Shanghai")
    payload = progress(42, "terrain.progress.processing")

    assert english_context.locale != chinese_context.locale
    assert payload == {
        "percent": 42,
        "code": "terrain.progress.processing",
        "params": {"percent": 42},
    }


def test_unexpected_task_failure_uses_safe_code_without_exception_text() -> None:
    failure = error_from_exception(
        RuntimeError("private database details"),
        "terrain.generation_failed",
        {"jobId": "job-42"},
    )

    assert failure == {
        "code": "terrain.generation_failed",
        "params": {"jobId": "job-42"},
    }
    assert "private database details" not in str(failure)


def test_persistent_models_use_machine_codes_and_params_not_final_messages() -> None:
    structured_error_models = (
        (LDrawFile, "parse_error"),
        (LDrawFileReference, "resolve_error"),
        (LDrawPart, "parse_error"),
        (LDrawPartGeometry, "geometry_error"),
        (LDrawPartShapeProfile, "profile_error"),
        (LDrawShadowFile, "parse_error"),
        (LDrawShadowMetaRaw, "parse_error"),
        (LDrawShadowInclude, "expand_error"),
        (FittingCandidateProfile, "profile_error"),
        (ComponentUploadSession, "failure_reason"),
        (ComponentImport, "failure_reason"),
        (ModelFittingJob, "error_message"),
    )

    for model, legacy_column in structured_error_models:
        columns = model.__table__.columns.keys()
        assert legacy_column not in columns

    model_fitting_columns = ModelFittingJob.__table__.columns.keys()
    assert "locale" in model_fitting_columns
    assert "timezone" in model_fitting_columns
    assert "error_code" in model_fitting_columns
    assert "error_params_json" in model_fitting_columns
