"""Load LDraw xref query configuration."""
import json
import os
from pathlib import Path

from src.config.app_settings import config_file


REQUIRED_CONFIG_KEYS = (
    "default_recall_relation_types",
    "substitute_recall_relation_types",
    "relation_type_sort_priority",
    "exclude_obsolete_candidates_by_default",
    "obsolete_ldraw_name_prefixes",
    "obsolete_ldraw_name_tokens",
)


def load_xref_config() -> dict:
    config_path = Path(os.getenv("LDRAW_XREF_CONFIG", config_file("ldraw_xref_import.json")))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(f"Missing xref config keys: {', '.join(missing_keys)}")
    return config


def get_default_recall_relation_types() -> tuple[str, ...]:
    return tuple(load_xref_config()["default_recall_relation_types"])


def get_substitute_recall_relation_types() -> tuple[str, ...]:
    return tuple(load_xref_config()["substitute_recall_relation_types"])


def get_relation_type_sort_priority() -> dict[str, int]:
    return load_xref_config()["relation_type_sort_priority"]


def should_exclude_obsolete_candidates_by_default() -> bool:
    return load_xref_config()["exclude_obsolete_candidates_by_default"]


def get_obsolete_ldraw_name_prefixes() -> tuple[str, ...]:
    return tuple(load_xref_config()["obsolete_ldraw_name_prefixes"])


def get_obsolete_ldraw_name_tokens() -> tuple[str, ...]:
    return tuple(load_xref_config()["obsolete_ldraw_name_tokens"])
