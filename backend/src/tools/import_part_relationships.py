"""Import Rebrickable part relationships with explicit column mapping."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import Base, PartRelationship


REQUIRED_CONFIG_KEYS = (
    "csv_path",
    "batch_size",
    "columns",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(
            f"Missing part relationship import config keys: {', '.join(missing_keys)}"
        )
    return config


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _read_relationship_records(config: dict) -> list[dict]:
    columns = config["columns"]
    frame = pd.read_csv(config["csv_path"])
    missing_columns = [
        source_column
        for source_column in columns.values()
        if source_column not in frame.columns
    ]
    if missing_columns:
        raise KeyError(
            "Missing part relationship CSV columns: "
            f"{', '.join(missing_columns)}"
        )

    records = []
    for row in frame.to_dict("records"):
        records.append(
            {
                "rel_type": row[columns["rel_type"]],
                "part_num": row[columns["part_num"]],
                "related_part_num": row[columns["related_part_num"]],
            }
        )
    return records


def import_part_relationships(config_path: Path) -> dict:
    config = _load_config(config_path)
    records = _read_relationship_records(config)

    engine = create_engine(get_db_url(), echo=False)
    Base.metadata.create_all(engine, tables=[PartRelationship.__table__])
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        session.execute(text("DELETE FROM rb_part_relationships"))
        for batch in _chunks(records, config["batch_size"]):
            session.bulk_insert_mappings(PartRelationship, batch)

    return {
        "imported": len(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/part_relationship_import.json"),
    )
    args = parser.parse_args()

    result = import_part_relationships(args.config)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
