"""Fitting candidate recall API configuration access."""

from src.config.app_settings import load_json_config


REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS = (
    "routes",
    "defaults",
    "limits",
    "scoring",
    "fuzzy_type",
    "part_filters",
    "irregular",
    "json_keys",
    "response",
    "http_status",
    "errors",
)

FITTING_CANDIDATE_RECALL_CONFIG = load_json_config(
    "fitting_candidate_recall.json",
    REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
)
