"""LDraw part shape profile configuration access."""

from src.config.app_settings import load_json_config


REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS = (
    "database",
    "profile",
    "json_keys",
    "build",
    "errors",
)

PART_SHAPE_PROFILE_CONFIG = load_json_config(
    "part_shape_profile.json",
    REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
)
PART_SHAPE_PROFILE_DATABASE_CONFIG = PART_SHAPE_PROFILE_CONFIG["database"]
