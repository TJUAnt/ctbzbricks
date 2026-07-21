"""
递归解析 LDraw 几何并写入 ldraw_part_geometry。
"""
import argparse
import json
import math
import os
import re
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.db_config import get_db_url
from src.ldraw.mesh import LDrawMesh, collect_ldraw_mesh
from src.model.models import LDrawFile, LDrawPart, LDrawPartGeometry
from src.resource.db.upsert import upsert_statement


DEFAULT_LDRAW_ROOT = r"D:\Program Files\LDraw"
DEFAULT_LOG_DIR = "logs"
DEFAULT_PARTS = ["3001.dat", "3020.dat"]
UPSERT_BATCH_SIZE = 500
BUILD_BATCH_SIZE = 100
DEFAULT_WORKERS = max(1, min(4, (os.cpu_count() or 1) - 1))
LDU_TO_MM = 0.4
WORKER_FILE_PATHS_BY_RELATIVE_PATH: dict[str, Path] = {}
WORKER_MESH_CONFIG: dict = {}


GEOMETRY_RECORD_FIELDS = [
    "ldraw_part_id",
    "bbox_min_x",
    "bbox_min_y",
    "bbox_min_z",
    "bbox_max_x",
    "bbox_max_y",
    "bbox_max_z",
    "width_ldu",
    "height_ldu",
    "depth_ldu",
    "width_mm",
    "height_mm",
    "depth_mm",
    "logical_width_stud",
    "logical_depth_stud",
    "logical_height_plate",
    "vertex_count",
    "face_count",
    "geometry_status",
    "geometry_error_code",
    "geometry_error_params_json",
]


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _part_chunks(parts: list[dict], size: int):
    for start in range(0, len(parts), size):
        yield start, parts[start : start + size]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _create_run_log(log_dir: str) -> Path:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return path / f"ldraw_geometry_{timestamp}.jsonl"


def _write_log(log_path: Path, event: dict) -> None:
    payload = {"ts": _now_iso(), **event}
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _batch_status_counts(records: list[dict]) -> dict[str, int]:
    counts = {"parsed": 0, "partial": 0, "failed": 0, "skipped": 0}
    for record in records:
        status = record["geometry_status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def _problem_records(records: list[dict]) -> list[dict]:
    return [
        {
            "ldraw_part_num": record["ldraw_part_num"],
            "ldraw_part_id": record["ldraw_part_id"],
            "geometry_status": record["geometry_status"],
            "geometry_issue": (
                {
                    "code": record["geometry_error_code"],
                    "params": record["geometry_error_params_json"] or {},
                }
                if record["geometry_error_code"]
                else None
            ),
        }
        for record in records
        if record["geometry_status"] != "parsed"
    ]


def _is_skippable_empty_geometry(part: dict, result: LDrawMesh) -> bool:
    name = (part.get("name") or "").strip().lower()
    if name.startswith("~obsolete") or name == "~obsolete file":
        return True
    return not result.errors


def _number_value(raw_value: str) -> float:
    if "/" in raw_value:
        numerator, denominator = raw_value.split("/", 1)
        return float(numerator) / float(denominator)
    return float(raw_value)


def _infer_logical_size(name: str | None, category: str | None) -> tuple[float | None, float | None, float | None]:
    if not name:
        return None, None, None

    normalized_name = name.replace("  ", " ")
    pattern = re.compile(
        r"(?P<w>\d+(?:\.\d+)?(?:/\d+)?)\s*x\s*"
        r"(?P<d>\d+(?:\.\d+)?(?:/\d+)?)"
        r"(?:\s*x\s*(?P<h>\d+(?:\.\d+)?(?:/\d+)?))?",
        re.IGNORECASE,
    )
    match = pattern.search(normalized_name)
    if not match:
        return None, None, None

    width = _number_value(match.group("w"))
    depth = _number_value(match.group("d"))
    raw_height = match.group("h")
    category_name = (category or "").lower()
    name_lower = normalized_name.lower()

    if raw_height is not None:
        height = _number_value(raw_height)
        if category_name == "brick" or name_lower.startswith(("brick", "technic brick")):
            height *= 3.0
        return width, depth, height

    if category_name in {"plate", "tile"} or name_lower.startswith(("plate", "tile")):
        return width, depth, 1.0
    if category_name == "brick" or name_lower.startswith(("brick", "technic brick")):
        return width, depth, 3.0
    if name_lower.startswith("slope"):
        return width, depth, 3.0

    return width, depth, None


def _near_integer(value: float, tolerance: float = 0.05) -> float | None:
    rounded = round(value)
    if math.isclose(value, rounded, abs_tol=tolerance):
        return float(rounded)
    return None


def _infer_logical_size_from_bbox(
    width_ldu: float,
    height_ldu: float,
    depth_ldu: float,
) -> tuple[float | None, float | None, float | None]:
    width = _near_integer(width_ldu / 20.0)
    depth = _near_integer(depth_ldu / 20.0)
    if width is None or depth is None:
        return None, None, None

    if math.isclose(height_ldu, 12.0, abs_tol=0.5):
        return width, depth, 1.0
    if math.isclose(height_ldu, 28.0, abs_tol=0.5):
        return width, depth, 3.0

    return None, None, None


def _build_geometry_record(
    part: dict,
    file_paths_by_relative_path: dict[str, Path],
    mesh_config: dict,
) -> dict:
    result = collect_ldraw_mesh(
        part["relative_path"],
        file_paths_by_relative_path,
        mesh_config,
    )

    if not result.triangles:
        geometry_status = "skipped" if _is_skippable_empty_geometry(part, result) else "failed"
        geometry_error_code = (
            "ldraw.geometry.build_failed" if result.errors else "ldraw.geometry.empty"
        )
        record = {field: None for field in GEOMETRY_RECORD_FIELDS}
        record.update({
            "ldraw_part_id": part["id"],
            "geometry_status": geometry_status,
            "geometry_error_code": geometry_error_code,
            "geometry_error_params_json": {
                "partId": part["ldraw_part_num"],
                "errorCount": len(result.errors),
            },
        })
        record["ldraw_part_num"] = part["ldraw_part_num"]
        return record

    vertices = tuple(vertex for triangle in result.triangles for vertex in triangle.vertices)
    xs = [vertex.x for vertex in vertices]
    ys = [vertex.y for vertex in vertices]
    zs = [vertex.z for vertex in vertices]

    bbox_min_x = min(xs)
    bbox_min_y = min(ys)
    bbox_min_z = min(zs)
    bbox_max_x = max(xs)
    bbox_max_y = max(ys)
    bbox_max_z = max(zs)

    width_ldu = bbox_max_x - bbox_min_x
    height_ldu = bbox_max_y - bbox_min_y
    depth_ldu = bbox_max_z - bbox_min_z
    logical_width, logical_depth, logical_height = _infer_logical_size(
        part["name"],
        part["category"],
    )
    if logical_width is None or logical_depth is None or logical_height is None:
        logical_width, logical_depth, logical_height = _infer_logical_size_from_bbox(
            width_ldu,
            height_ldu,
            depth_ldu,
        )

    geometry_status = "partial" if result.errors else "parsed"
    geometry_error_code = "ldraw.geometry.build_partial" if result.errors else None

    record = {
        "ldraw_part_id": part["id"],
        "bbox_min_x": bbox_min_x,
        "bbox_min_y": bbox_min_y,
        "bbox_min_z": bbox_min_z,
        "bbox_max_x": bbox_max_x,
        "bbox_max_y": bbox_max_y,
        "bbox_max_z": bbox_max_z,
        "width_ldu": width_ldu,
        "height_ldu": height_ldu,
        "depth_ldu": depth_ldu,
        "width_mm": width_ldu * LDU_TO_MM,
        "height_mm": height_ldu * LDU_TO_MM,
        "depth_mm": depth_ldu * LDU_TO_MM,
        "logical_width_stud": logical_width,
        "logical_depth_stud": logical_depth,
        "logical_height_plate": logical_height,
        "vertex_count": result.source_vertex_count,
        "face_count": result.source_face_count,
        "geometry_status": geometry_status,
        "geometry_error_code": geometry_error_code,
        "geometry_error_params_json": (
            {"partId": part["ldraw_part_num"], "errorCount": len(result.errors)}
            if result.errors
            else None
        ),
    }
    normalized_record = {field: record.get(field) for field in GEOMETRY_RECORD_FIELDS}
    normalized_record["ldraw_part_num"] = part["ldraw_part_num"]
    return normalized_record


def _upsert_geometry(session, geometry_records: list[dict]) -> None:
    db_records = [
        {field: record[field] for field in GEOMETRY_RECORD_FIELDS}
        for record in geometry_records
    ]
    for batch in _chunks(db_records, UPSERT_BATCH_SIZE):
        session.execute(
            upsert_statement(
                session,
                LDrawPartGeometry,
                batch,
                conflict_columns=("ldraw_part_id",),
                update_columns=(
                    "bbox_min_x",
                    "bbox_min_y",
                    "bbox_min_z",
                    "bbox_max_x",
                    "bbox_max_y",
                    "bbox_max_z",
                    "width_ldu",
                    "height_ldu",
                    "depth_ldu",
                    "width_mm",
                    "height_mm",
                    "depth_mm",
                    "logical_width_stud",
                    "logical_depth_stud",
                    "logical_height_plate",
                    "vertex_count",
                    "face_count",
                    "geometry_status",
                    "geometry_error_code",
                    "geometry_error_params_json",
                ),
            )
        )


def _load_file_paths(session, ldraw_root: Path) -> dict[str, Path]:
    rows = session.execute(select(LDrawFile.relative_path)).all()
    return {
        relative_path: ldraw_root / Path(relative_path)
        for (relative_path,) in rows
    }


def _load_parts(
    session,
    part_nums: list[str] | None,
    offset: int = 0,
    limit: int | None = None,
) -> list[dict]:
    stmt = select(LDrawPart).order_by(LDrawPart.id)
    if part_nums is not None:
        stmt = stmt.where(LDrawPart.ldraw_part_num.in_(part_nums))
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [
        {
            "id": part.id,
            "ldraw_part_num": part.ldraw_part_num,
            "name": part.name,
            "category": part.category,
            "relative_path": part.relative_path,
        }
        for part in session.scalars(stmt).all()
    ]


def _init_worker(file_paths_by_relative_path: dict[str, Path], mesh_config: dict) -> None:
    global WORKER_FILE_PATHS_BY_RELATIVE_PATH, WORKER_MESH_CONFIG
    WORKER_FILE_PATHS_BY_RELATIVE_PATH = file_paths_by_relative_path
    WORKER_MESH_CONFIG = mesh_config


def _build_geometry_batch(part_batch: list[dict]) -> list[dict]:
    return [
        _build_geometry_record(part, WORKER_FILE_PATHS_BY_RELATIVE_PATH, WORKER_MESH_CONFIG)
        for part in part_batch
    ]


def build_ldraw_geometry(
    ldraw_root: str = DEFAULT_LDRAW_ROOT,
    part_nums: list[str] | None = None,
    build_batch_size: int = BUILD_BATCH_SIZE,
    offset: int = 0,
    limit: int | None = None,
    workers: int = DEFAULT_WORKERS,
    log_dir: str = DEFAULT_LOG_DIR,
) -> None:
    root = Path(ldraw_root)
    mesh_config = load_json_config(
        "dem_lego_design.json",
        ("surface_profile",),
    )["surface_profile"]["mesh"]
    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        file_paths_by_relative_path = _load_file_paths(session, root)
        parts = _load_parts(session, part_nums, offset=offset, limit=limit)

    log_path = _create_run_log(log_dir)
    _write_log(
        log_path,
        {
            "event": "run_start",
            "ldraw_root": str(root),
            "part_nums": part_nums,
            "offset": offset,
            "limit": limit,
            "build_batch_size": build_batch_size,
            "workers": workers,
            "total_parts": len(parts),
        },
    )

    parsed_count = 0
    partial_count = 0
    failed_count = 0
    skipped_count = 0
    processed_count = 0
    failed_batches = 0
    batches = list(_part_chunks(parts, build_batch_size))

    def commit_batch(batch_start: int, part_batch: list[dict], geometry_records: list[dict]) -> None:
        nonlocal parsed_count, partial_count, failed_count, skipped_count, processed_count
        with Session.begin() as session:
            _upsert_geometry(session, geometry_records)

        counts = _batch_status_counts(geometry_records)
        processed_count += len(geometry_records)
        parsed_count += counts.get("parsed", 0)
        partial_count += counts.get("partial", 0)
        failed_count += counts.get("failed", 0)
        skipped_count += counts.get("skipped", 0)

        first_part = part_batch[0]["ldraw_part_num"]
        last_part = part_batch[-1]["ldraw_part_num"]
        problem_records = _problem_records(geometry_records)
        _write_log(
            log_path,
            {
                "event": "batch_committed",
                "batch_start": batch_start,
                "batch_end": batch_start + len(part_batch),
                "total_parts": len(parts),
                "first_part": first_part,
                "last_part": last_part,
                "counts": counts,
                "problem_records": problem_records,
            },
        )
        print(
            f"batch {batch_start + 1}-{batch_start + len(part_batch)} / {len(parts)} "
            f"({first_part}..{last_part}) committed "
            f"parsed={counts.get('parsed', 0)} partial={counts.get('partial', 0)} "
            f"failed={counts.get('failed', 0)} skipped={counts.get('skipped', 0)}",
            flush=True,
        )

    if workers <= 1:
        for start, part_batch in batches:
            try:
                geometry_records = [
                    _build_geometry_record(part, file_paths_by_relative_path, mesh_config)
                    for part in part_batch
                ]
                commit_batch(start, part_batch, geometry_records)
            except Exception as exc:
                failed_batches += 1
                _write_log(
                    log_path,
                    {
                        "event": "batch_failed",
                        "batch_start": start,
                        "batch_end": start + len(part_batch),
                        "parts": [part["ldraw_part_num"] for part in part_batch],
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                print(f"batch {start + 1}-{start + len(part_batch)} failed: {exc}", flush=True)
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(file_paths_by_relative_path, mesh_config),
        ) as executor:
            future_to_batch = {
                executor.submit(_build_geometry_batch, part_batch): (start, part_batch)
                for start, part_batch in batches
            }
            for future in as_completed(future_to_batch):
                start, part_batch = future_to_batch[future]
                try:
                    geometry_records = future.result()
                    commit_batch(start, part_batch, geometry_records)
                except Exception as exc:
                    failed_batches += 1
                    _write_log(
                        log_path,
                        {
                            "event": "batch_failed",
                            "batch_start": start,
                            "batch_end": start + len(part_batch),
                            "parts": [part["ldraw_part_num"] for part in part_batch],
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                        },
                    )
                    print(
                        f"batch {start + 1}-{start + len(part_batch)} failed: {exc}",
                        flush=True,
                    )

    _write_log(
        log_path,
        {
            "event": "run_finished",
            "processed": processed_count,
            "parsed": parsed_count,
            "partial": partial_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "failed_batches": failed_batches,
        },
    )
    print(f"已计算几何零件: {processed_count}")
    print(f"parsed: {parsed_count}")
    print(f"partial: {partial_count}")
    print(f"failed: {failed_count}")
    print(f"skipped: {skipped_count}")
    print(f"failed_batches: {failed_batches}")
    print(f"log: {log_path}")


def _parse_args():
    parser = argparse.ArgumentParser(description="Build LDraw part geometry")
    parser.add_argument("--ldraw-root", default=os.getenv("LDRAW_ROOT", DEFAULT_LDRAW_ROOT))
    parser.add_argument(
        "--parts",
        default=",".join(DEFAULT_PARTS),
        help="逗号分隔的 ldraw_part_num；默认 3001.dat,3020.dat",
    )
    parser.add_argument("--all", action="store_true", help="计算全部 ldraw_parts")
    parser.add_argument("--batch-size", type=int, default=BUILD_BATCH_SIZE)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    selected_parts = None
    if not args.all:
        selected_parts = [
            part.strip().lower()
            for part in args.parts.split(",")
            if part.strip()
        ]
    build_ldraw_geometry(
        args.ldraw_root,
        selected_parts,
        build_batch_size=args.batch_size,
        offset=args.offset,
        limit=args.limit,
        workers=args.workers,
        log_dir=args.log_dir,
    )
