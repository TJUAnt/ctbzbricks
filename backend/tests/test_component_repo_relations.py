"""Tests for Component Repo relation detection and review."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.component_repo.relation_service import (
    confirm_relation_candidate,
    detect_relation_candidates,
    ensure_part_library_version,
    list_free_connectors,
    list_relation_candidates,
    reject_relation_candidate,
)
from src.component_repo.component_service import (
    create_component_interface,
    ensure_component_candidate_draft,
    list_component_versions,
    list_components,
    publish_component_version,
    set_component_version_lifecycle_status,
    validate_component_candidate,
)
from src.component_repo.services import (
    create_component_artifact,
    create_component_import,
    ensure_component_repo_tables,
    parse_component_import,
)
from src.component_repo.storage import LocalArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.model.models import (
    Component,
    ComponentVersion,
    ConnectorInstance,
    FittingCandidateProfile,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
)


class ComponentRepoRelationTest(unittest.TestCase):
    def test_detect_confirm_and_free_connectors_for_pin_hole_pair(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "pin_pair.io",
                b"io",
            )
            exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "pin_pair.ldr",
                pin_pair_ldraw().encode("utf-8"),
            )
            import_row = create_component_import(engine, config, source["id"], exchange["id"])
            parse_result = parse_component_import(engine, config, storage, import_row["id"])
            candidate_id = parse_result["candidate"]["id"]

            part_library = ensure_part_library_version(engine, config)
            relations = detect_relation_candidates(engine, config, candidate_id)
            listed_relations = list_relation_candidates(engine, candidate_id)
            free_before = list_free_connectors(engine, candidate_id)
            assembly = confirm_relation_candidate(engine, config, relations[0]["id"])
            free_after = list_free_connectors(engine, candidate_id)

        self.assertEqual(part_library["id"], config["part_library"]["default_version_id"])
        self.assertEqual(part_library["connectorCount"], 2)
        self.assertEqual(len(relations), 1)
        self.assertEqual(listed_relations[0]["id"], relations[0]["id"])
        self.assertEqual(relations[0]["connectionType"], "pin_hole")
        self.assertEqual(relations[0]["jointType"], "revolute")
        self.assertTrue(relations[0]["verifiedByTolerance"])
        self.assertEqual(relations[0]["positionResidual"], 0.0)
        self.assertEqual(relations[0]["rotationResidual"], 0.0)
        self.assertEqual(len(free_before), 2)
        self.assertEqual(assembly["relationCandidateId"], relations[0]["id"])
        self.assertEqual(len(free_after), 0)

    def test_reject_relation_candidate_marks_candidate_rejected(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "pin_pair.io",
                b"io",
            )
            exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "pin_pair.ldr",
                pin_pair_ldraw().encode("utf-8"),
            )
            import_row = create_component_import(engine, config, source["id"], exchange["id"])
            parse_result = parse_component_import(engine, config, storage, import_row["id"])
            relations = detect_relation_candidates(engine, config, parse_result["candidate"]["id"])

            rejected = reject_relation_candidate(engine, config, relations[0]["id"])

        self.assertEqual(rejected["status"], config["relations"]["candidate_status"]["rejected"])

    def test_relation_detection_uses_frozen_connector_definitions(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "pin_pair.io",
                b"io",
            )
            exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "pin_pair.ldr",
                pin_pair_ldraw().encode("utf-8"),
            )
            import_row = create_component_import(engine, config, source["id"], exchange["id"])
            parse_result = parse_component_import(engine, config, storage, import_row["id"])
            ensure_part_library_version(engine, config)
            move_live_connector_instance(engine)

            relations = detect_relation_candidates(engine, config, parse_result["candidate"]["id"])

        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["positionResidual"], 0.0)

    def test_detect_relation_candidates_respects_position_tolerance(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "far_pair.io",
                b"io",
            )
            exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "far_pair.ldr",
                far_pair_ldraw().encode("utf-8"),
            )
            import_row = create_component_import(engine, config, source["id"], exchange["id"])
            parse_result = parse_component_import(engine, config, storage, import_row["id"])

            relations = detect_relation_candidates(engine, config, parse_result["candidate"]["id"])

        self.assertEqual(relations, [])

    def test_confirm_relation_candidate_is_candidate_scoped_and_idempotent(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            first = parsed_candidate(engine, config, storage, "first.ldr", pin_pair_ldraw())
            second = parsed_candidate(engine, config, storage, "second.ldr", pin_pair_ldraw())
            relations = detect_relation_candidates(engine, config, first)

            assembly = confirm_relation_candidate(
                engine,
                config,
                relations[0]["id"],
                component_candidate_id=first,
            )
            repeated = confirm_relation_candidate(
                engine,
                config,
                relations[0]["id"],
                component_candidate_id=first,
            )

            with self.assertRaises(ValueError):
                reject_relation_candidate(
                    engine,
                    config,
                    relations[0]["id"],
                    component_candidate_id=second,
                )

        self.assertEqual(repeated["id"], assembly["id"])

    def test_validation_requires_external_interface(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            candidate_id = parsed_candidate(engine, config, storage, "pin_pair.ldr", pin_pair_ldraw())

            report = validate_component_candidate(engine, config, candidate_id)

        self.assertFalse(report["passed"])
        self.assertIn(
            "component_repo.validation.interfaces_valid",
            {issue["code"] for issue in report["issues"]},
        )

    def test_parse_creates_editable_component_version_without_approval(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            candidate_id = parsed_candidate(engine, config, storage, "pin_pair.ldr", pin_pair_ldraw())
            detect_relation_candidates(engine, config, candidate_id)
            free_connectors = list_free_connectors(engine, candidate_id)

            interface = create_component_interface(
                engine,
                config,
                candidate_id,
                free_connectors[0]["worldConnectorId"],
                "mount_pin",
                mechanical_roles=["mount"],
                business_roles=["external_mount"],
            )
            report = validate_component_candidate(engine, config, candidate_id)
            draft = ensure_component_candidate_draft(
                engine,
                config,
                candidate_id,
            )

        self.assertEqual(interface["reviewStatus"], config["interfaces"]["status"]["confirmed"])
        self.assertTrue(report["passed"])
        self.assertEqual(draft["component"]["name"], "pin_pair")
        self.assertEqual(draft["version"]["status"], config["versions"]["status"]["draft"])
        self.assertEqual(draft["version"]["componentCandidateId"], candidate_id)

    def test_publish_component_version_makes_it_queryable_and_immutable(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            candidate_id = parsed_candidate(engine, config, storage, "pin_pair.ldr", pin_pair_ldraw())
            relations = detect_relation_candidates(engine, config, candidate_id)
            free_connectors = list_free_connectors(engine, candidate_id)
            create_component_interface(
                engine,
                config,
                candidate_id,
                free_connectors[0]["worldConnectorId"],
                "mount_pin",
            )
            draft = ensure_component_candidate_draft(
                engine,
                config,
                candidate_id,
            )

            unpublished_components = list_components(engine, config, "en-US")
            unpublished_versions = list_component_versions(
                engine,
                config,
                draft["component"]["id"],
            )
            published = publish_component_version(
                engine,
                config,
                draft["version"]["id"],
                release_note="first publish",
                name="Pin Pair Component",
                category="technic",
                content_locale="en-US",
            )
            published_components = list_components(engine, config, "en-US")
            published_versions = list_component_versions(
                engine,
                config,
                draft["component"]["id"],
            )
            Session = sessionmaker(bind=engine)
            with Session() as session:
                persisted_component = session.get(Component, draft["component"]["id"])
                persisted_profile = session.query(FittingCandidateProfile).filter_by(
                    candidate_type="component",
                    candidate_id=draft["component"]["id"],
                ).one()
                persisted_size = (
                    persisted_component.logical_width_stud,
                    persisted_component.logical_depth_stud,
                    persisted_component.logical_height_plate,
                )

            with self.assertRaises(ValueError):
                create_component_interface(
                    engine,
                    config,
                    candidate_id,
                    free_connectors[1]["worldConnectorId"],
                    "second_mount",
                )
            with self.assertRaises(ValueError):
                reject_relation_candidate(engine, config, relations[0]["id"])
            set_component_version_lifecycle_status(
                engine,
                config,
                draft["version"]["id"],
                config["versions"]["status"]["archived"],
            )
            with Session() as session:
                archived_component = session.get(Component, draft["component"]["id"])
                archived_profile = session.query(FittingCandidateProfile).filter_by(
                    candidate_type="component",
                    candidate_id=draft["component"]["id"],
                ).one_or_none()
                archived_size = (
                    archived_component.logical_width_stud,
                    archived_component.logical_depth_stud,
                    archived_component.logical_height_plate,
                )

        self.assertEqual(len(unpublished_components), 1)
        self.assertEqual(unpublished_components[0]["status"], config["components"]["status"]["draft"])
        self.assertEqual(len(unpublished_versions), 1)
        self.assertEqual(unpublished_versions[0]["status"], config["versions"]["status"]["draft"])
        self.assertEqual(published["status"], config["versions"]["status"]["published"])
        self.assertEqual(len(published_components), 1)
        self.assertEqual(len(published_versions), 1)
        self.assertEqual(persisted_size, (1.0, 1.0, 1.0))
        self.assertEqual(
            (
                persisted_profile.width_stud,
                persisted_profile.depth_stud,
                persisted_profile.height_plate,
            ),
            (1.0, 1.0, 1.0),
        )
        self.assertIsNone(archived_profile)
        self.assertEqual(archived_size, (None, None, None))

    def test_new_drawing_creates_history_and_replaces_the_single_published_version(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            first_candidate_id = parsed_candidate(
                engine,
                config,
                storage,
                "first.ldr",
                pin_pair_ldraw(),
            )
            detect_relation_candidates(engine, config, first_candidate_id)
            first_free = list_free_connectors(engine, first_candidate_id)
            create_component_interface(
                engine,
                config,
                first_candidate_id,
                first_free[0]["worldConnectorId"],
                "mount_pin",
            )
            first_draft = ensure_component_candidate_draft(
                engine,
                config,
                first_candidate_id,
            )
            first_published = publish_component_version(
                engine,
                config,
                first_draft["version"]["id"],
                name="Versioned Component",
                version_name="1.0.0",
                content_locale="en-US",
            )

            second_source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "second.io",
                b"second-io",
            )
            second_exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "second.ldr",
                pin_pair_ldraw().encode("utf-8"),
            )
            second_import = create_component_import(
                engine,
                config,
                second_source["id"],
                second_exchange["id"],
                target_component_id=first_draft["component"]["id"],
                base_version_id=first_published["id"],
                content_locale="en-US",
            )
            second_parse = parse_component_import(
                engine,
                config,
                storage,
                second_import["id"],
            )
            second_candidate_id = second_parse["candidate"]["id"]
            detect_relation_candidates(engine, config, second_candidate_id)
            second_free = list_free_connectors(engine, second_candidate_id)
            create_component_interface(
                engine,
                config,
                second_candidate_id,
                second_free[0]["worldConnectorId"],
                "mount_pin",
            )
            second_published = publish_component_version(
                engine,
                config,
                second_parse["version"]["id"],
                version_name="1.1.0",
            )
            versions = list_component_versions(
                engine,
                config,
                first_draft["component"]["id"],
            )
            components = list_components(engine, config, "en-US")

        self.assertEqual(second_parse["component"]["id"], first_draft["component"]["id"])
        self.assertEqual(len(versions), 2)
        self.assertEqual(
            [version["id"] for version in versions if version["status"] == "published"],
            [second_published["id"]],
        )
        self.assertEqual(
            next(version for version in versions if version["id"] == first_published["id"])["status"],
            config["versions"]["status"]["draft"],
        )
        self.assertEqual(components[0]["currentVersionId"], second_published["id"])

    def test_publish_rolls_back_when_basic_profile_upsert_fails(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            candidate_id = parsed_candidate(
                engine,
                config,
                storage,
                "pin_pair.ldr",
                pin_pair_ldraw(),
            )
            detect_relation_candidates(engine, config, candidate_id)
            free_connectors = list_free_connectors(engine, candidate_id)
            create_component_interface(
                engine,
                config,
                candidate_id,
                free_connectors[0]["worldConnectorId"],
                "mount_pin",
            )
            draft = ensure_component_candidate_draft(
                engine,
                config,
                candidate_id,
            )

            with patch(
                "src.component_repo.component_service."
                "upsert_component_fitting_candidate_profile",
                side_effect=RuntimeError("profile write failed"),
            ):
                with self.assertRaises(RuntimeError):
                    publish_component_version(
                        engine,
                        config,
                        draft["version"]["id"],
                    )

        Session = sessionmaker(bind=engine)
        with Session() as session:
            version = session.get(ComponentVersion, draft["version"]["id"])
            component = session.get(Component, draft["component"]["id"])
            profile = session.query(FittingCandidateProfile).filter_by(
                candidate_type="component",
                candidate_id=component.id,
            ).one_or_none()
            self.assertEqual(version.status, config["versions"]["status"]["draft"])
            self.assertEqual(component.status, config["components"]["status"]["draft"])
            self.assertIsNone(component.current_version_id)
            self.assertIsNone(profile)


def component_repo_config() -> dict:
    return load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )


def test_engine():
    engine = create_engine("sqlite:///:memory:")
    LDrawFile.__table__.create(bind=engine)
    LDrawPart.__table__.create(bind=engine)
    LDrawPartGeometry.__table__.create(bind=engine)
    ConnectorInstance.__table__.create(bind=engine)
    ensure_fitting_candidate_profile_table(engine)
    ensure_component_repo_tables(engine)
    return engine


def local_storage(config: dict, directory: str) -> LocalArtifactStorage:
    return LocalArtifactStorage(
        root_path=Path(directory),
        bucket=config["storage"]["bucket"],
        provider=config["storage"]["local_provider"],
    )


def parsed_candidate(
    engine,
    config: dict,
    storage: LocalArtifactStorage,
    filename: str,
    ldraw_text: str,
) -> str:
    source = create_component_artifact(
        engine,
        config,
        storage,
        config["artifacts"]["studio_io"],
        filename.replace(".ldr", ".io"),
        b"io",
    )
    exchange = create_component_artifact(
        engine,
        config,
        storage,
        config["artifacts"]["ldraw_ldr"],
        filename,
        ldraw_text.encode("utf-8"),
    )
    import_row = create_component_import(engine, config, source["id"], exchange["id"])
    parse_result = parse_component_import(engine, config, storage, import_row["id"])
    return parse_result["candidate"]["id"]


def seed_connector_pair(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        for row_id, part_num in ((1, "male.dat"), (2, "female.dat")):
            session.add(
                LDrawFile(
                    id=row_id,
                    relative_path=f"parts/{part_num}",
                    file_name=part_num,
                    library_section="parts",
                )
            )
            session.add(
                LDrawPart(
                    id=row_id,
                    ldraw_part_num=part_num,
                    file_id=row_id,
                    name=part_num,
                    category="Technic",
                    relative_path=f"parts/{part_num}",
                )
            )
            session.add(
                LDrawPartGeometry(
                    id=row_id,
                    ldraw_part_id=row_id,
                    bbox_min_x=0,
                    bbox_min_y=0,
                    bbox_min_z=0,
                    bbox_max_x=20,
                    bbox_max_y=8,
                    bbox_max_z=20,
                    width_ldu=20,
                    height_ldu=8,
                    depth_ldu=20,
                    logical_width_stud=1,
                    logical_depth_stud=1,
                    logical_height_plate=1,
                )
            )
        session.add(
            ConnectorInstance(
                id=1,
                ldraw_part_num="male.dat",
                source_type="test",
                connector_kind="cyl",
                normalized_connector_type="technic_pin",
                connector_group="pin",
                connector_gender="M",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
                direction_x=0,
                direction_y=1,
                direction_z=0,
                direction_label="top",
                direction_group="vertical",
                confidence=1,
                raw_params={},
            )
        )
        session.add(
            ConnectorInstance(
                id=2,
                ldraw_part_num="female.dat",
                source_type="test",
                connector_kind="cyl",
                normalized_connector_type="technic_pin_hole",
                connector_group="hole",
                connector_gender="F",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
                direction_x=0,
                direction_y=-1,
                direction_z=0,
                direction_label="bottom",
                direction_group="vertical",
                confidence=1,
                raw_params={},
            )
        )
        session.commit()


def move_live_connector_instance(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        connector = session.get(ConnectorInstance, 2)
        connector.pos_x = 20
        session.commit()


def pin_pair_ldraw() -> str:
    return (
        "0 FILE pin_pair\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 male.dat\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 female.dat\n"
        "0 NOFILE\n"
    )


def far_pair_ldraw() -> str:
    return (
        "0 FILE far_pair\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 male.dat\n"
        "1 16 20 0 0 1 0 0 0 1 0 0 0 1 female.dat\n"
        "0 NOFILE\n"
    )
