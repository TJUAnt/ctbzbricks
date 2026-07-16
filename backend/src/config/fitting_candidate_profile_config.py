"""Fitting candidate profile configuration access."""

from src.config.app_settings import load_json_config


REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS = (
    "database",
    "profile",
    "signature",
    "geometry",
    "json_keys",
    "build",
    "errors",
)

FITTING_CANDIDATE_PROFILE_CONFIG = load_json_config(
    "fitting_candidate_profile.json",
    REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
)
FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG = FITTING_CANDIDATE_PROFILE_CONFIG["database"]
