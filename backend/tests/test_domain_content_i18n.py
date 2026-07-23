"""M4 contracts for localized official content and user-authored originals."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.i18n.domain_content import reset_translation_metrics, translation_metrics
from src.i18n.domain_content import TRANSLATION_STATUSES
from src.model.models import (
    Component,
    ComponentTranslation,
    LDrawFile,
    LDrawPart,
    PartTranslation,
)
from src.services.domain_content_service import (
    ensure_domain_translation_tables,
    localized_component_content,
    localized_part_content,
    upsert_component_translation,
    upsert_part_translation,
)


def test_legacy_ldraw_parts_receive_source_content_locale() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ldraw_parts ("
                "id INTEGER PRIMARY KEY, ldraw_part_num VARCHAR(128) NOT NULL, "
                "name VARCHAR(512), relative_path VARCHAR(512) NOT NULL, "
                "parse_error TEXT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ldraw_parts "
                "(id, ldraw_part_num, name, relative_path, parse_error) "
                "VALUES (1, '3001.dat', 'Brick 2 x 4', 'parts/3001.dat', "
                "'legacy parser failure')"
            )
        )

    ensure_domain_translation_tables(engine)

    columns = {
        column["name"] for column in inspect(engine).get_columns("ldraw_parts")
    }
    with engine.connect() as connection:
        content_locale, error_code, error_params = connection.execute(
            text(
                "SELECT content_locale, parse_error_code, parse_error_params_json "
                "FROM ldraw_parts WHERE id = 1"
            )
        ).one()
    assert "content_locale" in columns
    assert "parse_error_code" in columns
    assert "parse_error_params_json" in columns
    assert content_locale == "en-US"
    assert error_code == "ldraw_part.legacy_parse_failed"
    assert json.loads(error_params) == {"partNumber": "3001.dat"}


def test_reviewed_component_translation_is_selected_and_user_content_stays_original() -> None:
    engine = domain_content_engine()
    seed_component(engine, "official-component", "official", "English component", "en-US")
    seed_component(engine, "user-component", "user", "用户原文", "zh-CN")
    reset_translation_metrics()

    Session = sessionmaker(bind=engine)
    with Session() as session:
        official = session.get(Component, "official-component")
        fallback = localized_component_content(session, official, "zh-CN")
        user = session.get(Component, "user-component")
        user_content = localized_component_content(session, user, "en-US")

    assert fallback == {
        "name": "English component",
        "description": None,
        "tags": [],
        "contentLocale": "en-US",
        "translationStatus": "fallback",
    }
    assert user_content["name"] == "用户原文"
    assert user_content["contentLocale"] == "zh-CN"
    assert translation_metrics()["missingOfficialTranslationCount"] == 1

    draft = upsert_component_translation(
        engine,
        "official-component",
        "zh-CN",
        "组件草稿",
        None,
        ["技术"],
        "draft",
        "reviewer-1",
    )
    assert draft["translationStatus"] == "draft"
    with Session() as session:
        official = session.get(Component, "official-component")
        assert localized_component_content(session, official, "zh-CN")["translationStatus"] == "fallback"

    reviewed = upsert_component_translation(
        engine,
        "official-component",
        "zh-CN",
        "官方组件",
        "已审核描述",
        ["技术"],
        "reviewed",
        "reviewer-1",
    )
    assert reviewed["reviewedBy"] == "reviewer-1"
    with Session() as session:
        official = session.get(Component, "official-component")
        localized = localized_component_content(session, official, "zh-CN")
    assert localized == {
        "name": "官方组件",
        "description": "已审核描述",
        "tags": ["技术"],
        "contentLocale": "zh-CN",
        "translationStatus": "reviewed",
    }

    with pytest.raises(ValueError, match="component_repo.user_content_translation_forbidden"):
        upsert_component_translation(
            engine,
            "user-component",
            "en-US",
            "Translated user content",
            None,
            [],
            "reviewed",
            "reviewer-1",
        )


def test_part_translation_uses_reviewed_records_and_reports_fallbacks() -> None:
    engine = domain_content_engine()
    seed_part(engine)
    reset_translation_metrics()

    Session = sessionmaker(bind=engine)
    with Session() as session:
        part = session.scalar(select(LDrawPart).where(LDrawPart.ldraw_part_num == "3001.dat"))
        fallback = localized_part_content(session, part, "zh-CN")
    assert fallback["name"] == "Brick 2 x 4"
    assert fallback["contentLocale"] == "en-US"
    assert fallback["translationStatus"] == "fallback"

    translation = upsert_part_translation(
        engine,
        "3001.dat",
        "zh-CN",
        "2 x 4 积木砖",
        "经典积木砖",
        "reviewed",
        "reviewer-2",
    )
    assert translation["translationStatus"] == "reviewed"
    with Session() as session:
        part = session.scalar(select(LDrawPart).where(LDrawPart.ldraw_part_num == "3001.dat"))
        localized = localized_part_content(session, part, "zh-CN")
    assert localized["name"] == "2 x 4 积木砖"
    assert localized["description"] == "经典积木砖"
    assert localized["contentLocale"] == "zh-CN"


def test_glossary_and_runtime_use_the_same_translation_review_statuses() -> None:
    glossary_path = Path(__file__).resolve().parents[1] / "config" / "i18n_glossary.json"
    glossary = json.loads(glossary_path.read_text(encoding="utf-8"))

    assert glossary["translationStatuses"] == list(TRANSLATION_STATUSES)
    terms = [entry["term"] for entry in glossary["terms"]]
    assert len(terms) == len(set(terms))
    assert {"LEGO", "LDraw", "DEM", "Component", "Connector"}.issubset(terms)


def domain_content_engine():
    engine = create_engine("sqlite:///:memory:")
    LDrawFile.__table__.create(bind=engine)
    LDrawPart.__table__.create(bind=engine)
    PartTranslation.__table__.create(bind=engine)
    Component.__table__.create(bind=engine)
    ComponentTranslation.__table__.create(bind=engine)
    return engine


def seed_component(
    engine,
    component_id: str,
    content_kind: str,
    name: str,
    content_locale: str,
) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            Component(
                id=component_id,
                name=name,
                content_kind=content_kind,
                content_locale=content_locale,
                category="technic",
                status="active",
                current_version_id=None,
                description=None,
                tags_json=[],
                metadata_json={},
                created_by="system",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def seed_part(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        file = LDrawFile(
            id=1,
            relative_path="parts/3001.dat",
            file_name="3001.dat",
            library_section="parts",
        )
        session.add(file)
        session.flush()
        session.add(
            LDrawPart(
                id=1,
                ldraw_part_num="3001.dat",
                file_id=file.id,
                name="Brick 2 x 4",
                content_locale="en-US",
                category="Brick",
                relative_path="parts/3001.dat",
            )
        )
        session.commit()
