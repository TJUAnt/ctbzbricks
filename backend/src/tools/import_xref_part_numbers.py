"""Import Phase 2 exact Rebrickable-to-LDraw part number mappings."""
import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, func, insert, inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import LDrawPart, Part, PartRelationship, XrefPartNumber
from src.tools.create_ldraw_tables import create_ldraw_tables


REQUIRED_CONFIG_KEYS = (
    "batch_size",
    "ldraw_part_suffix",
    "direct_exact_relation_type",
    "direct_exact_source",
    "direct_exact_confidence",
    "relationship_mappings",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(f"Missing xref import config keys: {', '.join(missing_keys)}")
    return config


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _ensure_unique_index(engine) -> None:
    index_names = {
        index["name"]
        for index in inspect(engine).get_indexes(XrefPartNumber.__tablename__)
    }
    constraint_names = {
        constraint["name"]
        for constraint in inspect(engine).get_unique_constraints(
            XrefPartNumber.__tablename__
        )
    }
    index_name = "uk_xref_rb_ldraw_relation_source"
    if index_name in index_names or index_name in constraint_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uk_xref_rb_ldraw_relation_source "
                "ON xref_part_numbers "
                "(rebrickable_part_num, ldraw_part_num, relation_type, source)"
            )
        )


def _read_direct_exact_rows(session, config: dict) -> list[dict]:
    rows = session.execute(
        select(
            Part.part_num,
            LDrawPart.ldraw_part_num,
        ).join(
            LDrawPart,
            func.lower(func.concat(Part.part_num, config["ldraw_part_suffix"]))
            == LDrawPart.ldraw_part_num,
        )
    ).all()

    return [
        {
            "rebrickable_part_num": rebrickable_part_num,
            "ldraw_part_num": ldraw_part_num,
            "bricklink_part_num": None,
            "lego_design_id": None,
            "relation_type": config["direct_exact_relation_type"],
            "source": config["direct_exact_source"],
            "confidence": Decimal(config["direct_exact_confidence"]),
        }
        for rebrickable_part_num, ldraw_part_num in rows
    ]


def _read_relationship_rows(session, mapping: dict, config: dict) -> list[dict]:
    rows = session.execute(
        select(
            PartRelationship.part_num,
            XrefPartNumber.ldraw_part_num,
        )
        .join(
            XrefPartNumber,
            XrefPartNumber.rebrickable_part_num == PartRelationship.related_part_num,
        )
        .where(PartRelationship.rel_type == mapping["rebrickable_rel_type"])
        .where(XrefPartNumber.relation_type == config["direct_exact_relation_type"])
        .where(XrefPartNumber.source == config["direct_exact_source"])
        .where(PartRelationship.part_num.is_not(None))
        .where(PartRelationship.related_part_num.is_not(None))
    ).all()

    return [
        {
            "rebrickable_part_num": rebrickable_part_num,
            "ldraw_part_num": ldraw_part_num,
            "bricklink_part_num": None,
            "lego_design_id": None,
            "relation_type": mapping["xref_relation_type"],
            "source": mapping["xref_source"],
            "confidence": Decimal(mapping["confidence"]),
        }
        for rebrickable_part_num, ldraw_part_num in rows
    ]


def _existing_mapping_keys(session, rows: list[dict]) -> set[tuple[str, str, str, str]]:
    if not rows:
        return set()

    existing_rows = session.execute(
        select(
            XrefPartNumber.rebrickable_part_num,
            XrefPartNumber.ldraw_part_num,
            XrefPartNumber.relation_type,
            XrefPartNumber.source,
        )
    ).all()
    return {
        (
            rebrickable_part_num,
            ldraw_part_num,
            relation_type,
            source,
        )
        for rebrickable_part_num, ldraw_part_num, relation_type, source in existing_rows
    }


def _insert_missing_rows(session, rows: list[dict], batch_size: int) -> int:
    existing_keys = _existing_mapping_keys(session, rows)
    missing_rows = [
        row
        for row in rows
        if (
            row["rebrickable_part_num"],
            row["ldraw_part_num"],
            row["relation_type"],
            row["source"],
        )
        not in existing_keys
    ]

    for batch in _chunks(missing_rows, batch_size):
        session.execute(insert(XrefPartNumber).values(batch))

    return len(missing_rows)


def import_xref_part_numbers(config_path: Path) -> dict:
    create_ldraw_tables()

    config = _load_config(config_path)
    engine = create_engine(get_db_url(), echo=False)
    _ensure_unique_index(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        direct_exact_rows = _read_direct_exact_rows(session, config)
        direct_exact_inserted = _insert_missing_rows(
            session,
            direct_exact_rows,
            config["batch_size"],
        )

        relationship_results = []
        relationship_inserted = 0
        relationship_matches = 0
        for mapping in config["relationship_mappings"]:
            relationship_rows = _read_relationship_rows(session, mapping, config)
            inserted = _insert_missing_rows(
                session,
                relationship_rows,
                config["batch_size"],
            )
            relationship_results.append(
                {
                    "rebrickable_rel_type": mapping["rebrickable_rel_type"],
                    "xref_relation_type": mapping["xref_relation_type"],
                    "matches": len(relationship_rows),
                    "inserted": inserted,
                    "existing": len(relationship_rows) - inserted,
                }
            )
            relationship_inserted += inserted
            relationship_matches += len(relationship_rows)

    return {
        "direct_exact_matches": len(direct_exact_rows),
        "direct_exact_inserted": direct_exact_inserted,
        "direct_exact_existing": len(direct_exact_rows) - direct_exact_inserted,
        "relationship_matches": relationship_matches,
        "relationship_inserted": relationship_inserted,
        "source": config["direct_exact_source"],
        "relation_type": config["direct_exact_relation_type"],
        "relationship_results": relationship_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/ldraw_xref_import.json"),
    )
    args = parser.parse_args()

    result = import_xref_part_numbers(args.config)
    for key, value in result.items():
        if key == "relationship_results":
            print(key)
            for row in value:
                print(
                    "  "
                    f"{row['rebrickable_rel_type']} -> "
                    f"{row['xref_relation_type']}: "
                    f"matches={row['matches']} "
                    f"inserted={row['inserted']} "
                    f"existing={row['existing']}"
                )
        else:
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
