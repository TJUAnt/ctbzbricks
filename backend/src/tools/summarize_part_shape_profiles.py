"""Summarize persisted LDraw part shape profile coverage."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import case, create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.db_config import get_db_url
from src.config.part_shape_profile_config import (
    REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
)
from src.model.models import LDrawPart, LDrawPartShapeProfile


def summarize_part_shape_profiles(
    categories: list[str],
    failure_limit: int,
) -> dict:
    config = load_json_config(
        "part_shape_profile.json",
        REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
    )
    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        return {
            "statuses": profile_status_counts(session),
            "errorTypes": profile_error_type_counts(session),
            "categories": category_profile_counts(session, config, categories),
            "failures": profile_failures(session, failure_limit),
        }


def profile_status_counts(session: object) -> dict[str, int]:
    return {
        status: count
        for status, count in session.execute(
            select(
                LDrawPartShapeProfile.profile_status,
                func.count(LDrawPartShapeProfile.id),
            )
            .group_by(LDrawPartShapeProfile.profile_status)
            .order_by(LDrawPartShapeProfile.profile_status)
        )
    }


def profile_error_type_counts(session: object) -> dict[str, int]:
    return {
        error_type: count
        for error_type, count in session.execute(
            select(
                LDrawPartShapeProfile.profile_error_type,
                func.count(LDrawPartShapeProfile.id),
            )
            .where(LDrawPartShapeProfile.profile_error_type.is_not(None))
            .group_by(LDrawPartShapeProfile.profile_error_type)
            .order_by(LDrawPartShapeProfile.profile_error_type)
        )
    }


def category_profile_counts(
    session: object,
    config: dict,
    categories: list[str],
) -> list[dict]:
    rows = session.execute(
        select(
            LDrawPart.category,
            func.count(LDrawPart.id),
            func.count(LDrawPartShapeProfile.id),
            func.sum(
                case(
                    (
                        LDrawPartShapeProfile.profile_status
                        == config["profile"]["ready_status"],
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        LDrawPartShapeProfile.profile_status
                        == config["profile"]["failed_status"],
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .outerjoin(
            LDrawPartShapeProfile,
            (LDrawPartShapeProfile.ldraw_part_id == LDrawPart.id)
            & (
                LDrawPartShapeProfile.profile_key
                == config["profile"]["default_profile_key"]
            ),
        )
        .where(LDrawPart.category.in_(categories))
        .group_by(LDrawPart.category)
        .order_by(LDrawPart.category)
    )
    return [
        {
            "category": category,
            "total": total,
            "profiled": profiled,
            "ready": int(ready or config["build"]["default_limit"]),
            "failed": int(failed or config["build"]["default_limit"]),
            "missing": total - profiled,
        }
        for category, total, profiled, ready, failed in rows
    ]


def profile_failures(session: object, failure_limit: int) -> list[dict]:
    rows = session.execute(
        select(
            LDrawPart.category,
            LDrawPart.ldraw_part_num,
            LDrawPartShapeProfile.profile_error_type,
            LDrawPartShapeProfile.profile_error_code,
            LDrawPartShapeProfile.profile_error_params_json,
        )
        .join(
            LDrawPartShapeProfile,
            LDrawPartShapeProfile.ldraw_part_id == LDrawPart.id,
        )
        .where(LDrawPartShapeProfile.profile_error_code.is_not(None))
        .order_by(LDrawPart.category, LDrawPart.ldraw_part_num)
        .limit(failure_limit)
    )
    return [
        {
            "category": category,
            "partId": part_id,
            "errorType": error_type,
            "error": {"code": error, "params": params or {}},
        }
        for category, part_id, error_type, error, params in rows
    ]


def main() -> None:
    config = load_json_config(
        "part_shape_profile.json",
        REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
    )
    parser.add_argument(
        "--pilot-categories",
        action="store_true",
        dest="pilot_categories",
    )
    parser.add_argument(
        "--failure-limit",
        type=int,
        default=config["build"]["default_batch_size"],
    )
    args = parser.parse_args()
    categories = (
        config["build"]["pilot_categories"]
        if args.pilot_categories or args.categories is None
        else args.categories
    )
    result = summarize_part_shape_profiles(categories, args.failure_limit)
    print(result)


if __name__ == "__main__":
    main()
