"""Model fitting configuration access."""

from src.config.app_settings import load_json_config


REQUIRED_MODEL_FITTING_CONFIG_KEYS = (
    "routes",
    "database",
    "schema",
    "job_status",
    "solution_status",
    "target_block",
    "semantic",
    "recall",
    "model_asset",
    "normalization",
    "glb",
    "json_keys",
    "http_status",
    "errors",
)

MODEL_FITTING_CONFIG = load_json_config(
    "model_fitting.json",
    REQUIRED_MODEL_FITTING_CONFIG_KEYS,
)
MODEL_FITTING_DATABASE_CONFIG = MODEL_FITTING_CONFIG["database"]
