"""Build persisted LDraw part shape profiles."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.db_config import get_db_url
from src.config.part_shape_profile_config import (
    REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
)
from src.ldraw.mesh import collect_ldraw_mesh
from src.ldraw.surface_profile import build_part_surface_profile
from src.model.models import LDrawFile, LDrawPart, LDrawPartShapeProfile
from src.services.part_shape_profile_service import (
    ensure_part_shape_profile_table,
    save_failed_part_shape_profile,
    save_part_surface_profile,
)


def build_part_shape_profiles(
    part_ids: list[str] | None = None,
    categories: list[str] | None = None,
    missing_only: bool | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    shape_config = load_json_config(
        "part_shape_profile.json",
        REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
    )
    dem_config = load_json_config("dem_lego_design.json", ("surface_profile",))
    profile_config = dem_config["surface_profile"]
    sampling_config = profile_config["sampling"]
    engine = create_engine(get_db_url(), echo=False)
    ensure_part_shape_profile_table(engine)
    active_missing_only = (
        shape_config["build"]["default_missing_only"]
        if missing_only is None
        else missing_only
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ldraw_files = {
            relative_path: Path(profile_config["ldraw_root"]) / Path(relative_path)
            for relative_path in session.scalars(select(LDrawFile.relative_path))
        }
        parts = load_parts(
            session,
            shape_config,
            part_ids,
            categories,
            active_missing_only,
            offset,
            limit,
        )

    ready_count = shape_config["build"]["default_limit"]
    failed_count = shape_config["build"]["default_limit"]
    for part in parts:
        source_hash = part["file_hash"] or shape_config["profile"]["source_hash_missing"]
        try:
            mesh = collect_ldraw_mesh(
                part["relative_path"],
                ldraw_files,
                profile_config["mesh"],
            )
            if mesh.errors:
                raise ValueError(
                    shape_config["errors"]["mesh_error_separator"].join(mesh.errors)
                )
            profile = build_part_surface_profile(
                part["ldraw_part_num"],
                mesh.surface_triangles,
                mesh.triangles,
                mesh.top_connection_origins,
                sampling_config,
            )
            save_part_surface_profile(
                engine,
                shape_config,
                part["ldraw_part_num"],
                profile,
                source_hash,
            )
            ready_count += 1
        except ValueError as error:
            save_failed_part_shape_profile(
                engine,
                shape_config,
                part["ldraw_part_num"],
                source_hash,
                str(error),
            )
            failed_count += 1
    return {
        "ready": ready_count,
        "failed": failed_count,
        "total": len(parts),
    }


def load_parts(
    session: object,
    config: dict,
    part_ids: list[str] | None,
    categories: list[str] | None,
    missing_only: bool,
    offset: int | None,
    limit: int | None,
) -> list[dict]:
    stmt = select(LDrawPart).order_by(LDrawPart.id)
    if part_ids is not None:
        stmt = stmt.where(LDrawPart.ldraw_part_num.in_([part_id.lower() for part_id in part_ids]))
    if categories is not None:
        stmt = stmt.where(LDrawPart.category.in_(categories))
    if missing_only:
        stmt = (
            stmt.outerjoin(
                LDrawPartShapeProfile,
                (LDrawPartShapeProfile.ldraw_part_id == LDrawPart.id)
                & (
                    LDrawPartShapeProfile.profile_key
                    == config["profile"]["default_profile_key"]
                ),
            )
            .where(LDrawPartShapeProfile.id.is_(None))
        )
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [
        {
            "ldraw_part_num": part.ldraw_part_num,
            "relative_path": part.relative_path,
            "file_hash": part.file_hash,
        }
        for part in session.scalars(stmt)
    ]


def main() -> None:
    config = load_json_config(
        "part_shape_profile.json",
        REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--part",
        action="append",
        dest="parts",
    )
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
    active_categories = (
        config["build"]["pilot_categories"]
        if args.pilot_categories
        else args.categories
    )
    result = build_part_shape_profiles(
        part_ids=args.parts,
        categories=active_categories,
        missing_only=not args.include_existing,
        offset=args.offset,
        limit=args.limit,
    )
    print(result)


if __name__ == "__main__":
    main()
