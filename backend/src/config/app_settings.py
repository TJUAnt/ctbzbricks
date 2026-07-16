"""Application configuration file loading."""
import json
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = BACKEND_ROOT / "config"


def config_file(file_name: str) -> Path:
    return CONFIG_ROOT / file_name


def load_json_config(file_name: str, required_keys: tuple[str, ...]) -> dict:
    config = json.loads(config_file(file_name).read_text(encoding="utf-8"))
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise KeyError(f"Missing config keys in {file_name}: {', '.join(missing_keys)}")
    return config
