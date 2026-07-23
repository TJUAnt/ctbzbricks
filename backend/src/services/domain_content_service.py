"""Localized official-domain content persistence and locale fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Engine, String, column, inspect, select, table, text
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.i18n.domain_content import (
    OFFICIAL_CONTENT,
    TRANSLATION_REVIEWED,
    normalize_content_locale,
    record_translation_fallback,
    validate_translation_status,
)
from src.model.models import Component, ComponentTranslation, LDrawPart, PartTranslation


def ensure_domain_translation_tables(engine: Engine) -> None:
    ensure_ldraw_part_schema(engine)
    ComponentTranslation.__table__.create(bind=engine, checkfirst=True)
    PartTranslation.__table__.create(bind=engine, checkfirst=True)


def ensure_ldraw_part_schema(engine: Engine) -> None:
    table_name = LDrawPart.__tablename__
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    quoted_column = preparer.quote("content_locale")
    definitions = {
        "content_locale": "VARCHAR(16) NOT NULL DEFAULT 'en-US'",
        "parse_error_code": "VARCHAR(160) NULL",
        "parse_error_params_json": "JSON NULL",
    }
    for column_name, definition in definitions.items():
        if column_name in columns:
            continue
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {quoted_table} ADD COLUMN "
                    f"{preparer.quote(column_name)} {definition}"
                )
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {quoted_table} SET {quoted_column} = 'en-US' "
                f"WHERE {quoted_column} IS NULL OR TRIM({quoted_column}) = ''"
            )
        )
    if "parse_error" not in columns:
        return
    parts = table(
        table_name,
        column("id"),
        column("ldraw_part_num", String(length=128)),
        column("parse_error", String()),
        column("parse_error_code", String(length=160)),
        column("parse_error_params_json", JSON()),
    )
    with engine.begin() as connection:
        rows = connection.execute(
            select(parts.c.id, parts.c.ldraw_part_num).where(
                parts.c.parse_error.is_not(None),
                parts.c.parse_error_code.is_(None),
            )
        ).all()
        for part_id, part_number in rows:
            connection.execute(
                parts.update()
                .where(parts.c.id == part_id)
                .values(
                    parse_error_code="ldraw_part.legacy_parse_failed",
                    parse_error_params_json={"partNumber": part_number},
                )
            )


def localized_component_content(
    session: Session,
    component: Component,
    requested_locale: str,
) -> dict[str, Any]:
    requested_locale = normalize_content_locale(requested_locale)
    if component.content_kind != OFFICIAL_CONTENT or requested_locale == component.content_locale:
        return component_source_content(component)
    translation = next(
        (
            row
            for row in component.translations
            if row.locale == requested_locale
            and row.translation_status == TRANSLATION_REVIEWED
        ),
        None,
    )
    if translation is not None:
        return {
            "name": translation.name,
            "description": translation.description,
            "tags": translation.tags_json or [],
            "contentLocale": translation.locale,
            "translationStatus": translation.translation_status,
        }
    record_translation_fallback("component", requested_locale, component.content_locale)
    return {**component_source_content(component), "translationStatus": "fallback"}


def localized_part_content(
    session: Session,
    part: LDrawPart,
    requested_locale: str,
) -> dict[str, Any]:
    requested_locale = normalize_content_locale(requested_locale)
    if requested_locale == part.content_locale:
        return part_source_content(part)
    translation = next(
        (
            row
            for row in part.translations
            if row.locale == requested_locale
            and row.translation_status == TRANSLATION_REVIEWED
        ),
        None,
    )
    if translation is not None:
        return {
            "name": translation.name,
            "description": translation.description,
            "contentLocale": translation.locale,
            "translationStatus": translation.translation_status,
        }
    record_translation_fallback("part", requested_locale, part.content_locale)
    return {**part_source_content(part), "translationStatus": "fallback"}


def localized_part_content_by_number(
    engine: Engine,
    part_numbers: list[str],
    requested_locale: str,
) -> dict[str, dict[str, Any]]:
    if not part_numbers:
        return {}
    SessionFactory = sessionmaker(bind=engine)
    with SessionFactory() as session:
        parts = session.scalars(
            select(LDrawPart)
            .options(selectinload(LDrawPart.translations))
            .where(LDrawPart.ldraw_part_num.in_(part_numbers))
        ).all()
        return {
            part.ldraw_part_num: localized_part_content(session, part, requested_locale)
            for part in parts
        }


def upsert_component_translation(
    engine: Engine,
    component_id: str,
    locale: str,
    name: str,
    description: str | None,
    tags: list[str],
    translation_status: str,
    actor: str | None,
) -> dict[str, Any]:
    locale = normalize_content_locale(locale)
    translation_status = validate_translation_status(translation_status)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as session:
        component = session.get(Component, component_id)
        if component is None:
            raise ValueError("component_repo.component_not_found")
        if component.content_kind != OFFICIAL_CONTENT:
            raise ValueError("component_repo.user_content_translation_forbidden")
        row = session.scalar(
            select(ComponentTranslation).where(
                ComponentTranslation.component_id == component_id,
                ComponentTranslation.locale == locale,
            )
        )
        now = datetime.now(timezone.utc)
        if row is None:
            row = ComponentTranslation(
                component_id=component_id,
                locale=locale,
                created_at=now,
            )
            session.add(row)
        row.name = name
        row.description = description
        row.tags_json = tags
        row.translation_status = translation_status
        row.reviewed_by = actor if translation_status == TRANSLATION_REVIEWED else None
        row.reviewed_at = now if translation_status == TRANSLATION_REVIEWED else None
        session.commit()
        return component_translation_response(row)


def upsert_part_translation(
    engine: Engine,
    part_number: str,
    locale: str,
    name: str,
    description: str | None,
    translation_status: str,
    actor: str | None,
) -> dict[str, Any]:
    locale = normalize_content_locale(locale)
    translation_status = validate_translation_status(translation_status)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as session:
        part = session.scalar(select(LDrawPart).where(LDrawPart.ldraw_part_num == part_number))
        if part is None:
            raise ValueError("part_search.part_not_found")
        row = session.scalar(
            select(PartTranslation).where(
                PartTranslation.ldraw_part_id == part.id,
                PartTranslation.locale == locale,
            )
        )
        now = datetime.now(timezone.utc)
        if row is None:
            row = PartTranslation(
                ldraw_part_id=part.id,
                locale=locale,
                created_at=now,
            )
            session.add(row)
        row.name = name
        row.description = description
        row.translation_status = translation_status
        row.reviewed_by = actor if translation_status == TRANSLATION_REVIEWED else None
        row.reviewed_at = now if translation_status == TRANSLATION_REVIEWED else None
        session.commit()
        return part_translation_response(row, part_number)


def component_source_content(component: Component) -> dict[str, Any]:
    return {
        "name": component.name,
        "description": component.description,
        "tags": component.tags_json or [],
        "contentLocale": component.content_locale,
        "translationStatus": "source",
    }


def part_source_content(part: LDrawPart) -> dict[str, Any]:
    return {
        "name": part.name,
        "description": None,
        "contentLocale": part.content_locale,
        "translationStatus": "source",
    }


def component_translation_response(row: ComponentTranslation) -> dict[str, Any]:
    return {
        "componentId": row.component_id,
        "locale": row.locale,
        "name": row.name,
        "description": row.description,
        "tags": row.tags_json or [],
        "translationStatus": row.translation_status,
        "reviewedBy": row.reviewed_by,
        "reviewedAt": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def part_translation_response(row: PartTranslation, part_number: str) -> dict[str, Any]:
    return {
        "ldrawPartNum": part_number,
        "locale": row.locale,
        "name": row.name,
        "description": row.description,
        "translationStatus": row.translation_status,
        "reviewedBy": row.reviewed_by,
        "reviewedAt": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }
