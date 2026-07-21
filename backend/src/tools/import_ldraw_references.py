"""
导入 LDraw 子文件引用关系。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import LDrawFile, LDrawFileReference
from src.resource.db.upsert import upsert_statement
from src.tools.create_ldraw_tables import create_ldraw_tables


DEFAULT_LDRAW_ROOT = r"D:\Program Files\LDraw"
UPSERT_BATCH_SIZE = 1000
REFERENCE_UPSERT_BATCH_SIZE = 250


def _chunks(records: list, size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _normalize_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix().lower()


def _normalize_ref_name(ref_name: str) -> str:
    return ref_name.strip().strip('"').replace("\\", "/").lower()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _scan_support_files(ldraw_root: Path) -> list[dict]:
    scan_roots = [
        (ldraw_root / "parts" / "s", "parts", "subpart"),
        (ldraw_root / "p", "p", "primitive"),
    ]
    records = []

    for scan_root, library_section, file_role in scan_roots:
        if not scan_root.exists():
            continue

        for path in scan_root.rglob("*.dat"):
            records.append(
                {
                    "relative_path": _normalize_relative_path(path, ldraw_root),
                    "file_name": path.name.lower(),
                    "library_section": library_section,
                    "file_role": file_role,
                    "title": None,
                    "category": None,
                    "file_hash": None,
                    "line_count": None,
                    "source": "ldraw_official",
                    "import_status": "parsed",
                    "parse_error_code": None,
                    "parse_error_params_json": None,
                }
            )

    return records


def _upsert_files(session, file_records: list[dict]) -> None:
    for batch in _chunks(file_records, UPSERT_BATCH_SIZE):
        session.execute(
            upsert_statement(
                session,
                LDrawFile,
                batch,
                conflict_columns=("relative_path",),
                update_columns=(
                    "file_name",
                    "library_section",
                    "file_role",
                    "source",
                    "import_status",
                    "parse_error_code",
                    "parse_error_params_json",
                ),
            )
        )


def _candidate_paths(from_relative_path: str, ref_name: str) -> list[str]:
    ref = _normalize_ref_name(ref_name)
    from_parts = from_relative_path.split("/")
    from_section = from_parts[0]
    from_dir = "/".join(from_parts[:-1])

    candidates = []
    if ref.startswith(("parts/", "p/")):
        candidates.append(ref)
    elif "/" in ref:
        if ref.startswith("s/"):
            candidates.append(f"parts/{ref}")
        if from_section == "p":
            candidates.append(f"p/{ref}")
        candidates.append(f"p/{ref}")
        candidates.append(ref)
    else:
        if from_dir:
            candidates.append(f"{from_dir}/{ref}")
        if from_section == "parts":
            candidates.append(f"parts/{ref}")
        candidates.append(f"p/{ref}")

    deduped = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _resolve_ref(
    from_relative_path: str,
    ref_name: str,
    file_ids_by_path: dict[str, int],
) -> tuple[int | None, str | None, str, str | None, dict | None]:
    for candidate in _candidate_paths(from_relative_path, ref_name):
        file_id = file_ids_by_path.get(candidate)
        if file_id is not None:
            return file_id, candidate, "resolved", None, None

    return None, None, "missing", "ldraw.reference_not_found", {"reference": ref_name}


def _parse_reference_line(line: str):
    parts = line.strip().split(maxsplit=14)
    if len(parts) != 15 or parts[0] != "1":
        return None

    try:
        values = [float(value) for value in parts[2:14]]
    except ValueError:
        return None

    return {
        "color_code": parts[1],
        "pos_x": values[0],
        "pos_y": values[1],
        "pos_z": values[2],
        "ori_11": values[3],
        "ori_12": values[4],
        "ori_13": values[5],
        "ori_21": values[6],
        "ori_22": values[7],
        "ori_23": values[8],
        "ori_31": values[9],
        "ori_32": values[10],
        "ori_33": values[11],
        "ref_name": _normalize_ref_name(parts[14]),
    }


def _parse_references(
    ldraw_root: Path,
    file_rows: list[tuple[int, str]],
    file_ids_by_path: dict[str, int],
) -> list[dict]:
    records = []

    for from_file_id, relative_path in file_rows:
        path = ldraw_root / Path(relative_path)
        if not path.exists():
            continue

        for line_no, line in enumerate(_read_text(path).splitlines(), start=1):
            parsed = _parse_reference_line(line)
            if parsed is None:
                continue

            to_file_id, resolved_path, status, error_code, error_params = _resolve_ref(
                relative_path,
                parsed["ref_name"],
                file_ids_by_path,
            )
            records.append(
                {
                    "from_file_id": from_file_id,
                    "to_file_id": to_file_id,
                    "line_no": line_no,
                    "color_code": parsed["color_code"],
                    "ref_name": parsed["ref_name"],
                    "resolved_relative_path": resolved_path,
                    "resolve_status": status,
                    "resolve_error_code": error_code,
                    "resolve_error_params_json": error_params,
                    "pos_x": parsed["pos_x"],
                    "pos_y": parsed["pos_y"],
                    "pos_z": parsed["pos_z"],
                    "ori_11": parsed["ori_11"],
                    "ori_12": parsed["ori_12"],
                    "ori_13": parsed["ori_13"],
                    "ori_21": parsed["ori_21"],
                    "ori_22": parsed["ori_22"],
                    "ori_23": parsed["ori_23"],
                    "ori_31": parsed["ori_31"],
                    "ori_32": parsed["ori_32"],
                    "ori_33": parsed["ori_33"],
                }
            )

    return records


def _upsert_reference_batch(session, reference_records: list[dict]) -> None:
    session.execute(
        upsert_statement(
            session,
            LDrawFileReference,
            reference_records,
            conflict_columns=("from_file_id", "line_no"),
            update_columns=(
                "to_file_id",
                "color_code",
                "ref_name",
                "resolved_relative_path",
                "resolve_status",
                "resolve_error_code",
                "resolve_error_params_json",
                "pos_x",
                "pos_y",
                "pos_z",
                "ori_11",
                "ori_12",
                "ori_13",
                "ori_21",
                "ori_22",
                "ori_23",
                "ori_31",
                "ori_32",
                "ori_33",
            ),
        )
    )


def _upsert_references(Session, reference_records: list[dict]) -> None:
    for batch in _chunks(reference_records, REFERENCE_UPSERT_BATCH_SIZE):
        with Session.begin() as session:
            _upsert_reference_batch(session, batch)


def _ensure_unique_reference_index(engine) -> None:
    inspector = inspect(engine)
    indexes = inspector.get_indexes("ldraw_file_references")
    if any(index["name"] == "uk_ldraw_ref_file_line" for index in indexes):
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uk_ldraw_ref_file_line "
                "ON ldraw_file_references (from_file_id, line_no)"
            )
        )


def import_ldraw_references(ldraw_root: str = DEFAULT_LDRAW_ROOT) -> None:
    create_ldraw_tables()

    root = Path(ldraw_root)
    if not root.exists():
        raise FileNotFoundError(f"LDraw 根目录不存在: {root}")

    engine = create_engine(get_db_url(), echo=False)
    _ensure_unique_reference_index(engine)
    Session = sessionmaker(bind=engine)

    support_records = _scan_support_files(root)
    with Session.begin() as session:
        _upsert_files(session, support_records)

    with Session.begin() as session:
        file_rows = session.execute(
            select(LDrawFile.id, LDrawFile.relative_path).where(
                LDrawFile.library_section.in_(["parts", "p"])
            )
        ).all()
        file_ids_by_path = {relative_path: file_id for file_id, relative_path in file_rows}
        reference_records = _parse_references(root, file_rows, file_ids_by_path)

    _upsert_references(Session, reference_records)

    resolved_count = sum(
        1 for record in reference_records if record["resolve_status"] == "resolved"
    )
    missing_count = len(reference_records) - resolved_count

    print(f"已确认依赖文件: {len(support_records)}")
    print(f"已解析引用: {len(reference_records)}")
    print(f"resolved: {resolved_count}")
    print(f"missing: {missing_count}")


if __name__ == "__main__":
    import_ldraw_references(os.getenv("LDRAW_ROOT", DEFAULT_LDRAW_ROOT))
