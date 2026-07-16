"""Required database configuration for DEM slope candidate models."""

from src.config.app_settings import load_json_config


DEM_SLOPE_CATALOG_CONFIG_FILE = "dem_slope_catalog.json"
DEM_SLOPE_CANDIDATE_CONFIG = load_json_config(
    DEM_SLOPE_CATALOG_CONFIG_FILE,
    ("database", "classification"),
)
DEM_SLOPE_CANDIDATE_DATABASE_CONFIG = DEM_SLOPE_CANDIDATE_CONFIG["database"]
