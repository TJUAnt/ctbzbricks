"""Validate Phase 4 connector instance generation."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import ConnectorInstance


REQUIRED_CONFIG_KEYS = (
    "unknown_connector_type",
    "validation_samples",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(
            f"Missing connector validation config keys: {', '.join(missing_keys)}"
        )
    return config


def validate_connector_instances(config_path: Path) -> int:
    config = _load_config(config_path)
    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    failures = []

    with Session() as session:
        total_count = session.execute(
            select(func.count()).select_from(ConnectorInstance)
        ).scalar_one()
        type_counts = session.execute(
            select(
                ConnectorInstance.normalized_connector_type,
                ConnectorInstance.connector_gender,
                func.count(),
            ).group_by(
                ConnectorInstance.normalized_connector_type,
                ConnectorInstance.connector_gender,
            )
        ).all()
        unknown_count = session.execute(
            select(func.count())
            .select_from(ConnectorInstance)
            .where(
                ConnectorInstance.normalized_connector_type
                == config["unknown_connector_type"]
            )
        ).scalar_one()

        sample_counts = []
        for sample in config["validation_samples"]:
            count = session.execute(
                select(func.count())
                .select_from(ConnectorInstance)
                .where(
                    ConnectorInstance.ldraw_part_num == sample["ldraw_part_num"]
                )
                .where(
                    ConnectorInstance.normalized_connector_type
                    == sample["normalized_connector_type"]
                )
                .where(
                    ConnectorInstance.connector_gender == sample["connector_gender"]
                )
            ).scalar_one()
            if "direction_group" in sample:
                count = session.execute(
                    select(func.count())
                    .select_from(ConnectorInstance)
                    .where(
                        ConnectorInstance.ldraw_part_num == sample["ldraw_part_num"]
                    )
                    .where(
                        ConnectorInstance.normalized_connector_type
                        == sample["normalized_connector_type"]
                    )
                    .where(
                        ConnectorInstance.connector_gender == sample["connector_gender"]
                    )
                    .where(
                        ConnectorInstance.direction_group == sample["direction_group"]
                    )
                ).scalar_one()
            sample_counts.append((sample, count))

    if total_count == 0:
        failures.append("connector_instances is empty")
    for sample, count in sample_counts:
        if count < sample["minimum_count"]:
            failures.append(
                "sample connector count below minimum: "
                f"{sample['ldraw_part_num']} "
                f"{sample['normalized_connector_type']} "
                f"{count} < {sample['minimum_count']}"
            )

    print(f"connector_instances: {total_count}")
    print(f"unknown_connector_instances: {unknown_count}")
    print("type_counts")
    for connector_type, gender, count in sorted(type_counts):
        print(f"  {connector_type} / {gender}: {count}")
    print("sample_counts")
    for sample, count in sample_counts:
        print(
            "  "
            f"{sample['ldraw_part_num']} "
            f"{sample['normalized_connector_type']} "
            f"{sample['connector_gender']} "
            f"{sample.get('direction_group', '')}: {count}"
        )

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
        default=Path("config/connector_generation.json"),
    )
    args = parser.parse_args()
    return validate_connector_instances(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
