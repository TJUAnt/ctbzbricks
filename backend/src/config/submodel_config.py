"""Submodel configuration access."""

from src.config.app_settings import load_json_config


REQUIRED_SUBMODEL_CONFIG_KEYS = (
    "routes",
    "database",
    "storage",
    "pagination",
    "ldraw",
    "color_percentages",
    "connection_points",
    "errors",
    "http_status",
)

SUBMODEL_CONFIG = load_json_config(
    "submodel.json",
    REQUIRED_SUBMODEL_CONFIG_KEYS,
)
SUBMODEL_DATABASE_CONFIG = SUBMODEL_CONFIG["database"]
