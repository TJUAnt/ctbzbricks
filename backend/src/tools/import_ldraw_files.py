"""
导入 LDraw parts/ 与 p/ 目录下的 .dat 文件索引。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import LDrawFile, LDrawPart
from src.resource.db.upsert import upsert_statement


DEFAULT_LDRAW_ROOT = r"D:\Program Files\LDraw"
UPSERT_BATCH_SIZE = 1000


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _read_header_text(path: Path) -> str:
    with path.open("rb") as file:
        content = file.read(8192)
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix().lower()


def _classify_file(root: Path, path: Path) -> tuple[str, str]:
    relative_parts = path.relative_to(root).parts
    library_section = relative_parts[0].lower()
    parent_parts = [part.lower() for part in relative_parts[:-1]]

    if library_section == "parts" and len(relative_parts) == 2:
        return library_section, "part"
    if library_section == "parts" and "s" in parent_parts:
        return library_section, "subpart"
    if library_section == "p":
        return library_section, "primitive"
    return library_section, "unknown"


def _parse_header(text: str) -> tuple[str | None, str | None]:
    title = None
    category = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("0"):
            break

        content = line[1:].strip()
        if title is None and content and not content.startswith("!"):
            title = content
            continue
        if content.upper().startswith("!CATEGORY "):
            category = content[len("!CATEGORY ") :].strip() or None
            continue

    return title, category


def _scan_dat_files(ldraw_root: Path) -> list[dict]:
    records = []
    scan_roots = [ldraw_root / "parts", ldraw_root / "p"]

    for scan_root in scan_roots:
        if not scan_root.exists():
            raise FileNotFoundError(f"LDraw 目录不存在: {scan_root}")

        for path in scan_root.rglob("*.dat"):
            if not path.is_file():
                continue

            text = _read_header_text(path)
            title, category = _parse_header(text)
            library_section, file_role = _classify_file(ldraw_root, path)

            records.append(
                {
                    "relative_path": _relative_path(ldraw_root, path),
                    "file_name": path.name.lower(),
                    "library_section": library_section,
                    "file_role": file_role,
                    "title": title,
                    "category": category,
                    "file_hash": None,
                    "line_count": None,
                    "source": "ldraw_official",
                    "import_status": "parsed",
                    "parse_error": None,
                }
            )

    return records


def _upsert_files(session, records: list[dict]) -> None:
    if not records:
        return

    for batch in _chunks(records, UPSERT_BATCH_SIZE):
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
                    "title",
                    "category",
                    "file_hash",
                    "line_count",
                    "source",
                    "import_status",
                    "parse_error",
                ),
            )
        )


def _upsert_parts(session, records: list[dict]) -> int:
    part_file_paths = [
        record["relative_path"]
        for record in records
        if record["file_role"] == "part"
    ]
    if not part_file_paths:
        return 0

    file_rows = session.execute(
        select(LDrawFile.id, LDrawFile.relative_path).where(
            LDrawFile.relative_path.in_(part_file_paths)
        )
    ).all()
    file_ids_by_path = {relative_path: file_id for file_id, relative_path in file_rows}

    part_records = []
    for record in records:
        if record["file_role"] != "part":
            continue
        file_id = file_ids_by_path[record["relative_path"]]
        part_records.append(
            {
                "ldraw_part_num": record["file_name"],
                "file_id": file_id,
                "name": record["title"],
                "category": record["category"],
                "relative_path": record["relative_path"],
                "file_hash": record["file_hash"],
                "source": record["source"],
                "import_status": record["import_status"],
                "parse_error": None,
            }
        )

    for batch in _chunks(part_records, UPSERT_BATCH_SIZE):
        session.execute(
            upsert_statement(
                session,
                LDrawPart,
                batch,
                conflict_columns=("ldraw_part_num",),
                update_columns=(
                    "file_id",
                    "name",
                    "category",
                    "relative_path",
                    "file_hash",
                    "source",
                    "import_status",
                    "parse_error",
                ),
            )
        )
    return len(part_records)


def import_ldraw_files(ldraw_root: str = DEFAULT_LDRAW_ROOT) -> None:
    root = Path(ldraw_root)
    if not root.exists():
        raise FileNotFoundError(f"LDraw 根目录不存在: {root}")

    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    records = _scan_dat_files(root)

    with Session.begin() as session:
        _upsert_files(session, records)
        part_count = _upsert_parts(session, records)

    file_counts = {}
    for record in records:
        file_counts[record["file_role"]] = file_counts.get(record["file_role"], 0) + 1

    print(f"已扫描 .dat 文件: {len(records)}")
    print(f"已导入真实零件: {part_count}")
    for file_role, count in sorted(file_counts.items()):
        print(f"{file_role}: {count}")


if __name__ == "__main__":
    import_ldraw_files(os.getenv("LDRAW_ROOT", DEFAULT_LDRAW_ROOT))
