"""
导入 LDraw parts.lst 中列出的真实零件。
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
from src.tools.create_ldraw_tables import create_ldraw_tables


DEFAULT_LDRAW_ROOT = r"D:\Program Files\LDraw"
UPSERT_BATCH_SIZE = 1000


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _infer_category(title: str | None) -> str | None:
    if not title:
        return None

    normalized = title.lstrip("~_").strip()
    if normalized.startswith("|"):
        normalized = normalized[1:].strip()
    if not normalized or normalized.lower().startswith("moved to"):
        return None

    return normalized.split()[0]


def _read_title_from_part_file(path: Path) -> str | None:
    with path.open("rb") as file:
        content = file.read(2048)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("0 "):
            title = line[2:].strip()
            if title and not title.startswith("!"):
                return title
        if line and not line.startswith("0"):
            break
    return None


def _read_parts_list(ldraw_root: Path) -> list[dict]:
    parts_list_path = ldraw_root / "parts.lst"
    parts_dir = ldraw_root / "parts"

    if not parts_list_path.exists():
        raise FileNotFoundError(f"LDraw parts.lst 不存在: {parts_list_path}")
    if not parts_dir.exists():
        raise FileNotFoundError(f"LDraw parts 目录不存在: {parts_dir}")

    parts_by_num = {}
    for raw_line in parts_list_path.read_text(encoding="latin-1").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        columns = line.split(maxsplit=1)
        if len(columns) != 2:
            continue

        part_num, title = columns
        part_num = part_num.lower()
        title = title.strip() or None
        if title and title.startswith("="):
            title = title[1:].strip() or None
        if not part_num.endswith(".dat"):
            continue

        part_path = parts_dir / part_num
        if not part_path.exists():
            continue

        parts_by_num[part_num] = {
            "ldraw_part_num": part_num,
            "name": title,
            "category": _infer_category(title),
            "relative_path": f"parts/{part_num}",
            "file_name": part_num,
        }

    for part_path in parts_dir.glob("*.dat"):
        part_num = part_path.name.lower()
        if part_num in parts_by_num:
            continue

        title = _read_title_from_part_file(part_path)
        parts_by_num[part_num] = {
            "ldraw_part_num": part_num,
            "name": title,
            "category": _infer_category(title),
            "relative_path": f"parts/{part_num}",
            "file_name": part_num,
        }

    return list(parts_by_num.values())


def _upsert_files(session, part_records: list[dict]) -> None:
    file_records = [
        {
            "relative_path": record["relative_path"],
            "file_name": record["file_name"],
            "library_section": "parts",
            "file_role": "part",
            "title": record["name"],
            "category": record["category"],
            "file_hash": None,
            "line_count": None,
            "source": "ldraw_official",
            "import_status": "parsed",
            "parse_error": None,
        }
        for record in part_records
    ]

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
                    "title",
                    "category",
                    "source",
                    "import_status",
                    "parse_error",
                ),
            )
        )


def _upsert_parts(session, part_records: list[dict]) -> None:
    relative_paths = [record["relative_path"] for record in part_records]
    file_ids_by_path = {}
    for batch in _chunks(relative_paths, UPSERT_BATCH_SIZE):
        file_rows = session.execute(
            select(LDrawFile.id, LDrawFile.relative_path).where(
                LDrawFile.relative_path.in_(batch)
            )
        ).all()
        file_ids_by_path.update(
            {relative_path: file_id for file_id, relative_path in file_rows}
        )

    rows = []
    for record in part_records:
        rows.append(
            {
                "ldraw_part_num": record["ldraw_part_num"],
                "file_id": file_ids_by_path[record["relative_path"]],
                "name": record["name"],
                "category": record["category"],
                "relative_path": record["relative_path"],
                "file_hash": None,
                "source": "ldraw_official",
                "import_status": "parsed",
                "parse_error": None,
            }
        )

    for batch in _chunks(rows, UPSERT_BATCH_SIZE):
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
                    "source",
                    "import_status",
                    "parse_error",
                ),
            )
        )


def import_ldraw_parts(ldraw_root: str = DEFAULT_LDRAW_ROOT) -> None:
    create_ldraw_tables()

    root = Path(ldraw_root)
    if not root.exists():
        raise FileNotFoundError(f"LDraw 根目录不存在: {root}")

    part_records = _read_parts_list(root)

    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        _upsert_files(session, part_records)
        _upsert_parts(session, part_records)

    print(f"已导入 LDraw parts: {len(part_records)}")


if __name__ == "__main__":
    import_ldraw_parts(os.getenv("LDRAW_ROOT", DEFAULT_LDRAW_ROOT))
