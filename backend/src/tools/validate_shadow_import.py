"""Validate Phase 3 LDCad Shadow raw import."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import LDrawShadowFile, LDrawShadowInclude, LDrawShadowMetaRaw


REQUIRED_CONFIG_KEYS = (
    "parsed_status",
    "validation_required_meta_types",
    "validation_sample",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(f"Missing shadow validation config keys: {', '.join(missing_keys)}")
    return config


def validate_shadow_import(config_path: Path) -> int:
    config = _load_config(config_path)
    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    failures = []

    with Session() as session:
        file_count = session.execute(
            select(func.count()).select_from(LDrawShadowFile)
        ).scalar_one()
        meta_count = session.execute(
            select(func.count()).select_from(LDrawShadowMetaRaw)
        ).scalar_one()
        include_count = session.execute(
            select(func.count()).select_from(LDrawShadowInclude)
        ).scalar_one()
        failed_meta_count = session.execute(
            select(func.count())
            .select_from(LDrawShadowMetaRaw)
            .where(LDrawShadowMetaRaw.parse_status != config["parsed_status"])
        ).scalar_one()
        meta_type_counts = dict(
            session.execute(
                select(LDrawShadowMetaRaw.meta_type, func.count())
                .group_by(LDrawShadowMetaRaw.meta_type)
            ).all()
        )

        sample = config["validation_sample"]
        sample_row = session.execute(
            select(LDrawShadowMetaRaw.parsed_json)
            .join(
                LDrawShadowFile,
                LDrawShadowFile.id == LDrawShadowMetaRaw.shadow_file_id,
            )
            .where(LDrawShadowFile.ldraw_part_num == sample["ldraw_part_num"])
            .where(LDrawShadowMetaRaw.meta_type == sample["meta_type"])
        ).first()

    if file_count == 0:
        failures.append("ldraw_shadow_files is empty")
    if meta_count == 0:
        failures.append("ldraw_shadow_meta_raw is empty")
    if include_count == 0:
        failures.append("ldraw_shadow_includes is empty")
    if failed_meta_count != 0:
        failures.append("shadow meta rows contain parse failures")

    for meta_type in config["validation_required_meta_types"]:
        if meta_type not in meta_type_counts:
            failures.append(f"required meta type missing: {meta_type}")

    if sample_row is None:
        failures.append("validation sample meta row missing")
    else:
        parsed_json = sample_row[0]
        for key in sample["required_param_keys"]:
            if key not in parsed_json:
                failures.append(f"validation sample param missing: {key}")
            elif not isinstance(parsed_json[key], list):
                failures.append(f"validation sample param is not a list: {key}")

    print(f"shadow_files: {file_count}")
    print(f"shadow_meta_rows: {meta_count}")
    print(f"shadow_includes: {include_count}")
    print(f"failed_meta_rows: {failed_meta_count}")
    print("meta_type_counts")
    for meta_type, count in sorted(meta_type_counts.items()):
        print(f"  {meta_type}: {count}")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/shadow_import.json"),
    )
    args = parser.parse_args()
    return validate_shadow_import(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
