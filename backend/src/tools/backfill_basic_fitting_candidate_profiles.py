"""Synchronize the unified basic recall index for Parts and Components."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine

from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.config.db_config import get_db_url
from src.config.fitting_candidate_profile_config import (
    REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
)
from src.services.fitting_candidate_profile_service import (
    backfill_basic_fitting_candidate_profiles,
    ensure_fitting_candidate_profile_table,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    fitting_config = load_json_config(
        "fitting_candidate_profile.json",
        REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
    )
    component_config = load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )
    engine = create_engine(get_db_url(), pool_pre_ping=True)
    try:
        ensure_fitting_candidate_profile_table(engine)
        result = backfill_basic_fitting_candidate_profiles(
            engine,
            fitting_config,
            component_config["components"]["status"]["active"],
            batch_size=args.batch_size,
        )
        print(result)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
