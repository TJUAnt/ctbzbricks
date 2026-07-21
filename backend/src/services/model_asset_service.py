"""Model asset persistence and pagination."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, delete, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.i18n.messages import locale_catalog
from src.model.models import ModelAsset


def ensure_model_asset_table(engine: Engine) -> None:
    ModelAsset.__table__.create(bind=engine, checkfirst=True)
    ensure_model_asset_content_locale_column(engine)


def ensure_model_asset_content_locale_column(engine: Engine) -> None:
    """Upgrade legacy model_assets tables created before locale provenance."""
    columns = {
        column["name"]
        for column in inspect(engine).get_columns(ModelAsset.__tablename__)
    }
    if "content_locale" in columns:
        return
    default_locale = str(locale_catalog()["default_locale"])
    escaped_locale = default_locale.replace("'", "''")
    preparer = engine.dialect.identifier_preparer
    table_name = preparer.quote(ModelAsset.__tablename__)
    column_name = preparer.quote("content_locale")
    statement = (
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} "
        f"VARCHAR(16) NOT NULL DEFAULT '{escaped_locale}'"
    )
    with engine.begin() as connection:
        connection.execute(text(statement))


def save_dem_model_asset(
    engine: Engine,
    asset_config: dict[str, Any],
    terrain_config: dict[str, Any],
    asset: dict[str, Any],
    model: dict[str, Any],
    content_locale: str,
) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        model_asset = ModelAsset(
            id=model["modelId"],
            name=model["name"],
            content_locale=content_locale,
            model_type=asset_config["dem_model_type"],
            source_type=asset_config["dem_source_type"],
            source_name=model["source"],
            asset_path=str(Path(terrain_config["model_store_path"]) / f"{model['modelId']}{terrain_config['model_file_extension']}"),
            status=asset_config["complete_status"],
            columns=model["columns"],
            rows=model["rows"],
            min_elevation=model["minElevation"],
            max_elevation=model["maxElevation"],
            valid_sample_count=model["validSampleCount"],
            metadata_json={
                "bounds": asset["bounds"],
                "schema": asset["schema"],
                "renderOptions": asset["renderOptions"],
            },
            created_at=datetime.fromisoformat(model["createdAt"]),
        )
        session.merge(model_asset)
        session.commit()


def save_lego_heightmap_model_asset(
    engine: Engine,
    asset_config: dict[str, Any],
    terrain_config: dict[str, Any],
    asset: dict[str, Any],
    model: dict[str, Any],
    content_locale: str,
) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        model_asset = ModelAsset(
            id=model["modelId"],
            name=model["name"],
            content_locale=content_locale,
            model_type=asset_config["lego_heightmap_model_type"],
            source_type=asset_config["lego_heightmap_source_type"],
            source_name=model["source"],
            asset_path=str(Path(terrain_config["model_store_path"]) / f"{model['modelId']}{terrain_config['model_file_extension']}"),
            status=asset_config["complete_status"],
            columns=model["columns"],
            rows=model["rows"],
            min_elevation=None,
            max_elevation=model["maxHeightPlate"],
            valid_sample_count=model["validCellCount"],
            metadata_json={
                "bounds": asset["bounds"],
                "schema": asset["schema"],
                "scale": asset["scale"],
                "maxHeightPlate": model["maxHeightPlate"],
                "totalCellCount": model["totalCellCount"],
            },
            created_at=datetime.fromisoformat(model["createdAt"]),
        )
        session.merge(model_asset)
        session.commit()


def paginated_model_assets(
    engine: Engine,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        total = session.scalar(select(func.count()).select_from(ModelAsset))
        rows = session.scalars(
            select(ModelAsset)
            .order_by(ModelAsset.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "items": [model_asset_response(row) for row in rows],
    }


def delete_model_asset(engine: Engine, asset_id: str) -> str | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        model_asset = session.get(ModelAsset, asset_id)
        if not model_asset:
            return None
        asset_path = model_asset.asset_path
        session.execute(delete(ModelAsset).where(ModelAsset.id == asset_id))
        session.commit()
    return asset_path


def model_asset_response(model_asset: ModelAsset) -> dict[str, Any]:
    return {
        "id": model_asset.id,
        "name": model_asset.name,
        "contentLocale": model_asset.content_locale,
        "modelType": model_asset.model_type,
        "sourceType": model_asset.source_type,
        "sourceName": model_asset.source_name,
        "assetPath": model_asset.asset_path,
        "previewPath": model_asset.preview_path,
        "status": model_asset.status,
        "columns": model_asset.columns,
        "rows": model_asset.rows,
        "minElevation": model_asset.min_elevation,
        "maxElevation": model_asset.max_elevation,
        "validSampleCount": model_asset.valid_sample_count,
        "metadata": model_asset.metadata_json,
        "createdAt": model_asset.created_at.isoformat(),
    }


def bounded_page(value: int | None, default_value: int) -> int:
    if value is None:
        return default_value
    return max(default_value, value)


def bounded_page_size(value: int | None, default_value: int, max_value: int) -> int:
    if value is None:
        return default_value
    return min(max(default_value, value), max_value)
