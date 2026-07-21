"""Build unified fitting candidate profiles."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.db_config import get_db_url
from src.config.fitting_candidate_profile_config import (
    REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
)
from src.model.models import (
    FittingCandidateProfile,
    LDrawPart,
    LDrawPartGeometry,
    LDrawSubmodel,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
    save_part_fitting_candidate_profile,
    save_submodel_fitting_candidate_profile,
)


def build_fitting_candidate_profiles(
    part_ids: list[str] | None = None,
    submodel_ids: list[str] | None = None,
    candidate_type: str | None = None,
    categories: list[str] | None = None,
    missing_only: bool | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    config = load_json_config(
        "fitting_candidate_profile.json",
        REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
    )
    engine = create_engine(get_db_url(), echo=False)
    ensure_fitting_candidate_profile_table(engine)
    active_candidate_type = candidate_type or config["profile"]["candidate_types"]["part"]
    active_missing_only = (
        config["build"]["default_missing_only"]
        if missing_only is None
        else missing_only
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate_ids = load_candidate_ids(
            session,
            config,
            active_candidate_type,
            part_ids,
            submodel_ids,
            categories,
            active_missing_only,
            offset,
            limit,
        )
    ready_count = config["build"]["default_limit"]
    failed_count = config["build"]["default_limit"]
    for candidate_id in candidate_ids:
        try:
            profile = save_fitting_candidate_profile(
                engine,
                config,
                active_candidate_type,
                candidate_id,
            )
            if profile["profileStatus"] == config["profile"]["ready_status"]:
                ready_count += 1
            if profile["profileStatus"] == config["profile"]["failed_status"]:
                failed_count += 1
        except ValueError:
            failed_count += 1
    return {
        "ready": ready_count,
        "failed": failed_count,
        "total": len(candidate_ids),
    }


def save_fitting_candidate_profile(
    engine: object,
    config: dict,
    candidate_type: str,
    candidate_id: str,
) -> dict:
    if candidate_type == config["profile"]["candidate_types"]["part"]:
        return save_part_fitting_candidate_profile(engine, config, candidate_id)
    if candidate_type == config["profile"]["candidate_types"]["submodel"]:
        return save_submodel_fitting_candidate_profile(engine, config, candidate_id)
    raise ValueError(
        config["errors"]["unsupported_candidate_type"].format(candidate_type=candidate_type)
    )


def load_candidate_ids(
    session: object,
    config: dict,
    candidate_type: str,
    part_ids: list[str] | None,
    submodel_ids: list[str] | None,
    categories: list[str] | None,
    missing_only: bool,
    offset: int | None,
    limit: int | None,
) -> list[str]:
    if candidate_type == config["profile"]["candidate_types"]["part"]:
        return load_candidate_parts(
            session,
            config,
            part_ids,
            categories,
            missing_only,
            offset,
            limit,
        )
    if candidate_type == config["profile"]["candidate_types"]["submodel"]:
        return load_candidate_submodels(
            session,
            config,
            submodel_ids,
            missing_only,
            offset,
            limit,
        )
    raise ValueError(
        config["errors"]["unsupported_candidate_type"].format(candidate_type=candidate_type)
    )


def load_candidate_parts(
    session: object,
    config: dict,
    part_ids: list[str] | None,
    categories: list[str] | None,
    missing_only: bool,
    offset: int | None,
    limit: int | None,
) -> list[str]:
    stmt = (
        select(LDrawPart.ldraw_part_num)
        .join(
            LDrawPartGeometry,
            LDrawPartGeometry.ldraw_part_id == LDrawPart.id,
        )
        .where(LDrawPartGeometry.logical_width_stud.is_not(None))
        .where(LDrawPartGeometry.logical_depth_stud.is_not(None))
        .where(LDrawPartGeometry.logical_height_plate.is_not(None))
        .order_by(LDrawPart.id)
    )
    if part_ids is not None:
        stmt = stmt.where(LDrawPart.ldraw_part_num.in_([part_id.lower() for part_id in part_ids]))
    if categories is not None:
        stmt = stmt.where(LDrawPart.category.in_(categories))
    if missing_only:
        stmt = (
            stmt.outerjoin(
                FittingCandidateProfile,
                (FittingCandidateProfile.candidate_type == config["profile"]["candidate_types"]["part"])
                & (FittingCandidateProfile.candidate_id == LDrawPart.ldraw_part_num)
                & (
                    FittingCandidateProfile.profile_key
                    == config["profile"]["default_profile_key"]
                ),
            )
            .where(FittingCandidateProfile.id.is_(None))
        )
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [part_id for (part_id,) in session.execute(stmt)]


def load_candidate_submodels(
    session: object,
    config: dict,
    submodel_ids: list[str] | None,
    missing_only: bool,
    offset: int | None,
    limit: int | None,
) -> list[str]:
    stmt = select(LDrawSubmodel.id).order_by(LDrawSubmodel.created_at, LDrawSubmodel.id)
    if submodel_ids is not None:
        stmt = stmt.where(LDrawSubmodel.id.in_(submodel_ids))
    if missing_only:
        stmt = (
            stmt.outerjoin(
                FittingCandidateProfile,
                (FittingCandidateProfile.candidate_type == config["profile"]["candidate_types"]["submodel"])
                & (FittingCandidateProfile.candidate_id == LDrawSubmodel.id)
                & (
                    FittingCandidateProfile.profile_key
                    == config["profile"]["default_profile_key"]
                ),
            )
            .where(FittingCandidateProfile.id.is_(None))
        )
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [submodel_id for (submodel_id,) in session.execute(stmt)]


def main() -> None:
    config = load_json_config(
        "fitting_candidate_profile.json",
        REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--part",
        action="append",
        dest="parts",
    )
    parser.add_argument(
        "--submodel",
        action="append",
        dest="submodels",
    )
    parser.add_argument(
        "--candidate-type",
        choices=[
            config["profile"]["candidate_types"]["part"],
            config["profile"]["candidate_types"]["submodel"],
        ],
        default=config["profile"]["candidate_types"]["part"],
    )
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        dest="include_existing",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=config["build"]["default_offset"],
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=config["build"]["default_batch_size"],
    )
    args = parser.parse_args()
    result = build_fitting_candidate_profiles(
        part_ids=args.parts,
        submodel_ids=args.submodels,
        candidate_type=args.candidate_type,
        categories=args.categories,
        missing_only=not args.include_existing,
        offset=args.offset,
        limit=args.limit,
    )
    print(result)


if __name__ == "__main__":
    main()
