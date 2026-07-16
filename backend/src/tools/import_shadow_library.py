"""Import raw LDCad Shadow Library metadata."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import (
    LDrawShadowFile,
    LDrawShadowInclude,
    LDrawShadowMetaRaw,
)
from src.resource.db.upsert import upsert_statement
from src.tools.create_ldraw_tables import create_ldraw_tables


REQUIRED_CONFIG_KEYS = (
    "shadow_root",
    "scan_directories",
    "file_extension",
    "batch_size",
    "ldcad_meta_prefix",
    "snap_meta_prefix",
    "mirror_meta_prefix",
    "snap_include_meta_type",
    "parsed_status",
    "failed_status",
    "pending_status",
    "source_repo",
    "source_commit",
    "param_pattern",
    "sequence_param_keys",
    "include_ref_key",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(f"Missing shadow import config keys: {', '.join(missing_keys)}")
    return config


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _read_text(path: Path) -> str:
    content = path.read_bytes()
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_shadow_files(root: Path, config: dict) -> list[Path]:
    files = []
    for directory in config["scan_directories"]:
        scan_root = root / directory
        if scan_root.exists():
            files.extend(scan_root.rglob(f"*{config['file_extension']}"))
    return sorted(files)


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix().lower()


def _ldraw_part_num(root: Path, path: Path) -> str:
    relative_path = _relative_path(root, path)
    if relative_path.startswith("parts/"):
        return relative_path.removeprefix("parts/")
    return relative_path


def _meta_type(line: str, config: dict) -> str | None:
    stripped = line.strip()
    if not stripped.startswith(config["ldcad_meta_prefix"]):
        return None
    payload = stripped.removeprefix(config["ldcad_meta_prefix"]).strip()
    if not payload:
        return None
    return payload.split(maxsplit=1)[0]


def _parse_scalar(value: str):
    stripped = value.strip()
    if not stripped:
        return stripped
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def _parse_sequence(value: str) -> list:
    return [_parse_scalar(token) for token in value.split()]


def _parse_params(raw_line: str, config: dict) -> dict:
    params = {}
    pattern = re.compile(config["param_pattern"])
    for key, value in pattern.findall(raw_line):
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key in config["sequence_param_keys"]:
            params[normalized_key] = _parse_sequence(normalized_value)
        else:
            params[normalized_key] = normalized_value
    return params


def _extract_meta_rows(root: Path, path: Path, config: dict) -> tuple[dict, list[dict]]:
    text = _read_text(path)
    relative_path = _relative_path(root, path)
    ldraw_part_num = _ldraw_part_num(root, path)
    meta_rows = []
    has_snap_meta = False
    has_mirror_meta = False

    for line_no, line in enumerate(text.splitlines(), 1):
        meta_type = _meta_type(line, config)
        if meta_type is None:
            continue

        has_snap_meta = has_snap_meta or meta_type.startswith(config["snap_meta_prefix"])
        has_mirror_meta = has_mirror_meta or meta_type.startswith(
            config["mirror_meta_prefix"]
        )
        try:
            parsed_json = _parse_params(line, config)
            parse_status = config["parsed_status"]
            parse_error = None
        except ValueError as error:
            parsed_json = None
            parse_status = config["failed_status"]
            parse_error = str(error)

        meta_rows.append(
            {
                "line_no": line_no,
                "meta_type": meta_type,
                "raw_line": line.strip(),
                "parsed_json": parsed_json,
                "parse_status": parse_status,
                "parse_error": parse_error,
            }
        )

    file_record = {
        "ldraw_part_num": ldraw_part_num,
        "relative_path": relative_path,
        "file_hash": _hash_file(path),
        "source_repo": config["source_repo"],
        "source_commit": config["source_commit"],
        "has_snap_meta": has_snap_meta,
        "has_mirror_meta": has_mirror_meta,
        "import_status": config["parsed_status"],
        "parse_error": None,
    }
    return file_record, meta_rows


def _upsert_shadow_files(session, file_records: list[dict], batch_size: int) -> None:
    for batch in _chunks(file_records, batch_size):
        session.execute(
            upsert_statement(
                session,
                LDrawShadowFile,
                batch,
                conflict_columns=("ldraw_part_num", "relative_path"),
                update_columns=(
                    "file_hash",
                    "source_repo",
                    "source_commit",
                    "has_snap_meta",
                    "has_mirror_meta",
                    "import_status",
                    "parse_error",
                ),
            )
        )


def _shadow_file_ids(session, relative_paths: list[str]) -> dict[str, int]:
    rows = session.execute(
        select(LDrawShadowFile.id, LDrawShadowFile.relative_path).where(
            LDrawShadowFile.relative_path.in_(relative_paths)
        )
    ).all()
    return {relative_path: file_id for file_id, relative_path in rows}


def _replace_meta_rows(
    session,
    file_records: list[dict],
    meta_rows_by_relative_path: dict[str, list[dict]],
    batch_size: int,
) -> None:
    session.execute(delete(LDrawShadowInclude))
    file_ids = _shadow_file_ids(
        session,
        [record["relative_path"] for record in file_records],
    )
    ids = list(file_ids.values())
    if ids:
        session.execute(
            delete(LDrawShadowMetaRaw).where(
                LDrawShadowMetaRaw.shadow_file_id.in_(ids)
            )
        )

    rows = []
    for relative_path, meta_rows in meta_rows_by_relative_path.items():
        for meta_row in meta_rows:
            rows.append(
                {
                    "shadow_file_id": file_ids[relative_path],
                    **meta_row,
                }
            )

    for batch in _chunks(rows, batch_size):
        session.execute(insert(LDrawShadowMetaRaw).values(batch))


def _replace_include_rows(session, config: dict, batch_size: int) -> int:
    rows = session.execute(
        select(
            LDrawShadowMetaRaw.id,
            LDrawShadowMetaRaw.parsed_json,
            LDrawShadowFile.ldraw_part_num,
        )
        .join(LDrawShadowFile, LDrawShadowFile.id == LDrawShadowMetaRaw.shadow_file_id)
        .where(LDrawShadowMetaRaw.meta_type == config["snap_include_meta_type"])
    ).all()

    include_rows = []
    for meta_id, params, from_ldraw_part_num in rows:
        if not params or config["include_ref_key"] not in params:
            continue
        pos = params.get("pos")
        include_rows.append(
            {
                "from_ldraw_part_num": from_ldraw_part_num,
                "to_shadow_ref": params[config["include_ref_key"]].lower(),
                "source_meta_id": meta_id,
                "pos_x": pos[0] if pos and len(pos) > 0 else None,
                "pos_y": pos[1] if pos and len(pos) > 1 else None,
                "pos_z": pos[2] if pos and len(pos) > 2 else None,
                "ori_json": params.get("ori"),
                "grid_json": params.get("grid"),
                "raw_params": params,
                "expand_status": config["pending_status"],
                "expand_error": None,
            }
        )

    for batch in _chunks(include_rows, batch_size):
        session.execute(insert(LDrawShadowInclude).values(batch))
    return len(include_rows)


def import_shadow_library(config_path: Path) -> dict:
    config = _load_config(config_path)
    root = Path(config["shadow_root"])
    if not root.exists():
        raise FileNotFoundError(f"Shadow root does not exist: {root}")

    create_ldraw_tables()

    file_records = []
    meta_rows_by_relative_path = {}
    for path in _scan_shadow_files(root, config):
        file_record, meta_rows = _extract_meta_rows(root, path, config)
        file_records.append(file_record)
        meta_rows_by_relative_path[file_record["relative_path"]] = meta_rows

    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        _upsert_shadow_files(session, file_records, config["batch_size"])
        _replace_meta_rows(
            session,
            file_records,
            meta_rows_by_relative_path,
            config["batch_size"],
        )
        include_count = _replace_include_rows(session, config, config["batch_size"])

    meta_count = sum(len(rows) for rows in meta_rows_by_relative_path.values())
    return {
        "shadow_files": len(file_records),
        "shadow_meta_rows": meta_count,
        "shadow_includes": include_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/shadow_import.json"),
    )
    args = parser.parse_args()

    result = import_shadow_library(args.config)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
