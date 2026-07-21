"""Pixel art database persistence."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from src.model.models import PixelArtProject
from src.i18n.domain_content import normalize_content_locale


def ensure_pixel_art_project_table(engine: Engine) -> None:
    PixelArtProject.__table__.create(bind=engine, checkfirst=True)


def save_pixel_art_project(
    engine: Engine,
    config: dict[str, Any],
    name: str,
    source_image_bytes: bytes,
    asset: dict[str, Any],
    content_locale: str,
) -> dict[str, Any]:
    content_locale = normalize_content_locale(content_locale)
    model_id = uuid4().hex[: int(config["storage"]["project_id_hex_length"])]
    created_at = datetime.now(timezone.utc)
    project = PixelArtProject(
        id=model_id,
        name=name,
        content_locale=content_locale,
        schema=asset["schema"],
        source_type=config["metadata"]["source_type"],
        source_name=asset["source"],
        source_content_type=asset["sourceContentType"],
        preview_content_type=config["image"]["preview_content_type"],
        preview_image=asset["previewBytes"],
        status=config["storage"]["complete_status"],
        grid_width=asset["gridWidth"],
        grid_height=asset["gridHeight"],
        color_count=asset["colorCount"],
        crop_json=asset["crop"],
        palette_json=asset["palette"],
        pixel_matrix_json=asset["pixels"],
        created_at=created_at,
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        session.add(project)
        session.commit()
    return pixel_art_project_response(config, project)


def load_pixel_art_project(
    engine: Engine,
    config: dict[str, Any],
    project_id: str,
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        project = session.get(PixelArtProject, project_id)
        if project is None:
            return None
        return pixel_art_project_response(config, project)


def paginated_pixel_art_projects(
    engine: Engine,
    config: dict[str, Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        total = session.scalar(select(func.count()).select_from(PixelArtProject))
        projects = session.scalars(
            select(PixelArtProject)
            .order_by(PixelArtProject.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "items": [pixel_art_project_summary(config, project) for project in projects],
    }


def update_pixel_art_project_pixels(
    engine: Engine,
    config: dict[str, Any],
    project_id: str,
    palette: list[dict[str, Any]],
    pixels: list[dict[str, Any]],
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        project = session.get(PixelArtProject, project_id)
        if project is None:
            return None
        project.palette_json = palette
        project.pixel_matrix_json = pixels
        session.commit()
        return pixel_art_project_response(config, project)


def pixel_art_project_response(config: dict[str, Any], project: PixelArtProject) -> dict[str, Any]:
    return {
        "modelId": project.id,
        "name": project.name,
        "contentLocale": project.content_locale,
        "source": project.source_name,
        "createdAt": project.created_at.isoformat(),
        "schema": project.schema,
        "gridWidth": project.grid_width,
        "gridHeight": project.grid_height,
        "colorCount": project.color_count,
        "palette": project.palette_json,
        "pixels": project.pixel_matrix_json,
        "previewImage": preview_data_url(config, project.preview_image),
    }


def pixel_art_project_summary(config: dict[str, Any], project: PixelArtProject) -> dict[str, Any]:
    return {
        "modelId": project.id,
        "name": project.name,
        "contentLocale": project.content_locale,
        "source": project.source_name,
        "createdAt": project.created_at.isoformat(),
        "gridWidth": project.grid_width,
        "gridHeight": project.grid_height,
        "colorCount": project.color_count,
        "previewImage": preview_data_url(config, project.preview_image),
    }


def bounded_page(value: int | None, default_value: int) -> int:
    if value is None:
        return default_value
    return max(default_value, value)


def bounded_page_size(value: int | None, default_value: int, max_value: int) -> int:
    if value is None:
        return default_value
    return min(max(default_value, value), max_value)


def preview_data_url(config: dict[str, Any], preview_image: bytes) -> str:
    encoded_preview = base64.b64encode(preview_image).decode(config["storage"]["text_encoding"])
    return f"data:{config['image']['preview_content_type']};base64,{encoded_preview}"
