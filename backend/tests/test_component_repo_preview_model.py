"""Preview-cache ownership and artifact-boundary tests."""

from pathlib import Path

from src.component_repo.preview_model_service import (
    component_version_preview_artifact_id,
    component_version_preview_storage_key,
    preview_storage_key,
)
from src.component_repo.storage import LocalArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS


def component_repo_config() -> dict:
    return load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )


def test_preview_storage_key_matches_user_first_storage_rls() -> None:
    config = component_repo_config()

    storage_key = preview_storage_key(config, "user-123", "abcdef")

    assert storage_key == "user-123/component-repo/previews/ab/abcdef.glb"


def test_preview_glb_is_internal_derived_artifact_not_upload_type() -> None:
    config = component_repo_config()
    preview_type = config["artifacts"]["component_preview_glb"]

    assert preview_type not in config["artifacts"]["allowed_types"]
    assert preview_type in config["artifacts"]["derived_types"]


def test_component_version_preview_identity_does_not_require_scene_content() -> None:
    config = component_repo_config()
    storage = LocalArtifactStorage(Path("/tmp/component-preview-test"), "test-bucket")

    first = component_version_preview_artifact_id(
        storage,
        "version-123",
        config["preview"]["generator_version"],
    )
    repeated = component_version_preview_artifact_id(
        storage,
        "version-123",
        config["preview"]["generator_version"],
    )
    upgraded = component_version_preview_artifact_id(
        storage,
        "version-123",
        "component-preview-glb-v2",
    )

    assert first == repeated
    assert first != upgraded


def test_component_version_preview_storage_path_is_version_addressed() -> None:
    config = component_repo_config()

    storage_key = component_version_preview_storage_key(
        config,
        "user-123",
        "version-123",
        config["preview"]["generator_version"],
    )

    assert storage_key == (
        "user-123/component-repo/previews/versions/version-123/"
        "component-preview-glb-v1/version-123.glb"
    )
