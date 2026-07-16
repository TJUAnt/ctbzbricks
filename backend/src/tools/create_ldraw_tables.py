"""Create LDraw and connector-related tables."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, inspect, text

from src.config.part_shape_profile_config import PART_SHAPE_PROFILE_DATABASE_CONFIG
from src.config.db_config import get_db_url
from src.model.models import (
    ConnectorInstance,
    FittingCandidateProfile,
    LDrawFile,
    LDrawFileReference,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
    LDrawShadowFile,
    LDrawShadowInclude,
    LDrawShadowMetaRaw,
    LDrawSubmodel,
    LDrawSubmodelConnector,
    LDrawSubmodelPart,
    ModelAsset,
    ModelFittingJob,
    ModelFittingSolution,
    ModelFittingSolutionEdit,
    ModelFittingSolutionPlacement,
    ModelFittingTargetBlock,
    XrefPartNumber,
)


def create_ldraw_tables():
    engine = create_engine(get_db_url(), echo=False)
    tables = [
        XrefPartNumber.__table__,
        LDrawFile.__table__,
        LDrawFileReference.__table__,
        LDrawPart.__table__,
        LDrawPartGeometry.__table__,
        LDrawPartShapeProfile.__table__,
        LDrawShadowFile.__table__,
        LDrawShadowMetaRaw.__table__,
        LDrawShadowInclude.__table__,
        ConnectorInstance.__table__,
        LDrawSubmodel.__table__,
        LDrawSubmodelPart.__table__,
        LDrawSubmodelConnector.__table__,
        FittingCandidateProfile.__table__,
        ModelAsset.__table__,
        ModelFittingJob.__table__,
        ModelFittingTargetBlock.__table__,
        ModelFittingSolution.__table__,
        ModelFittingSolutionPlacement.__table__,
        ModelFittingSolutionEdit.__table__,
    ]
    for table in tables:
        table.create(bind=engine, checkfirst=True)
        print(f"table exists: {table.name}")
    _ensure_connector_direction_columns(engine)
    _ensure_part_shape_profile_error_type_column(engine)


def _ensure_connector_direction_columns(engine):
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("connector_instances")
    }
    statements = {
        "direction_x": "ALTER TABLE connector_instances ADD COLUMN direction_x DOUBLE PRECISION NULL",
        "direction_y": "ALTER TABLE connector_instances ADD COLUMN direction_y DOUBLE PRECISION NULL",
        "direction_z": "ALTER TABLE connector_instances ADD COLUMN direction_z DOUBLE PRECISION NULL",
        "direction_label": "ALTER TABLE connector_instances ADD COLUMN direction_label VARCHAR(32) NULL",
        "direction_group": "ALTER TABLE connector_instances ADD COLUMN direction_group VARCHAR(32) NULL",
    }
    with engine.begin() as connection:
        for column_name, statement in statements.items():
            if column_name not in columns:
                connection.execute(text(statement))
                print(f"column exists: connector_instances.{column_name}")


def _ensure_part_shape_profile_error_type_column(engine):
    table_name = LDrawPartShapeProfile.__tablename__
    columns = {
        column["name"]
        for column in inspect(engine).get_columns(table_name)
    }
    column_name = "profile_error_type"
    if column_name in columns:
        return
    length = PART_SHAPE_PROFILE_DATABASE_CONFIG["string_lengths"]["profile_error_type"]
    statement = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR({length}) NULL"
    with engine.begin() as connection:
        connection.execute(text(statement))
        print(f"column exists: {table_name}.{column_name}")


if __name__ == "__main__":
    create_ldraw_tables()
