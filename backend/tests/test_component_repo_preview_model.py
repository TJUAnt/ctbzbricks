"""Preview-cache ownership and artifact-boundary tests."""

from src.component_repo.preview_model_service import preview_storage_key
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
