"""Backfill normalized connector analysis for existing Component candidates."""

from __future__ import annotations

import argparse
import os
import sys
from time import perf_counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, exists, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from src.component_repo.interface_recognition_service import (
    persist_component_connector_analysis,
)
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.config.db_config import get_db_engine_options, get_db_url
from src.model.models import ComponentCandidate, ComponentConnectorAnalysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id")
    parser.add_argument("--refresh-all", action="store_true")
    args = parser.parse_args()
    config = load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )
    engine = create_engine(
        get_db_url(),
        poolclass=QueuePool,
        **get_db_engine_options(),
    )
    Session = sessionmaker(bind=engine)
    try:
        with Session() as session:
            candidate_query = select(ComponentCandidate.id).order_by(
                ComponentCandidate.created_at.asc()
            )
            if args.candidate_id:
                candidate_query = candidate_query.where(
                    ComponentCandidate.id == args.candidate_id
                )
            elif not args.refresh_all:
                candidate_query = candidate_query.where(
                    ~exists().where(
                        ComponentConnectorAnalysis.component_candidate_id
                        == ComponentCandidate.id
                    )
                )
            candidate_ids = list(session.scalars(candidate_query).all())

        completed = 0
        failed = 0
        for candidate_id in candidate_ids:
            started = perf_counter()
            try:
                with Session() as session:
                    analysis = persist_component_connector_analysis(
                        session,
                        config,
                        candidate_id,
                    )
                    session.commit()
                completed += 1
                print(
                    "candidateId="
                    f"{candidate_id} connectors={len(analysis['connectors'])} "
                    f"durationMs={(perf_counter() - started) * 1000:.1f}"
                )
            except Exception as error:
                failed += 1
                print(
                    "candidateId="
                    f"{candidate_id} failed errorType={type(error).__name__}"
                )
        print(
            f"selected={len(candidate_ids)} completed={completed} failed={failed}"
        )
        if failed:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
