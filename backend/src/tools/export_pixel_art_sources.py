"""Export legacy pixel-art source images before removing database blobs."""

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from src.config.db_config import get_db_url


def export_sources(output_dir: Path) -> int:
    engine = create_engine(get_db_url(), pool_pre_ping=True)
    columns = {column["name"] for column in inspect(engine).get_columns("pixel_art_projects")}
    if "source_image" not in columns:
        print("pixel_art_projects.source_image is already absent")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, name, source_name, source_content_type, source_image "
                "FROM pixel_art_projects ORDER BY id"
            )
        ).all()
        for project_id, name, source_name, content_type, image in rows:
            extension = mimetypes.guess_extension(content_type or "") or ".bin"
            file_name = f"{project_id}{extension}"
            payload = bytes(image)
            (output_dir / file_name).write_bytes(payload)
            manifest.append(
                {
                    "id": project_id,
                    "name": name,
                    "sourceName": source_name,
                    "contentType": content_type,
                    "file": file_name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    engine.dispose()
    print(f"exported={len(manifest)}")
    print(f"output={output_dir}")
    return len(manifest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    export_sources(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
