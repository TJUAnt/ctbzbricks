"""Unit tests for persisted LDraw part shape profiles."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.part_shape_profile_config import REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS
from src.ldraw.surface_profile import PartSurfaceProfile
from src.model.models import (
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
)
from src.services.part_shape_profile_service import (
    classify_profile_error,
    ensure_part_shape_profile_table,
    save_failed_part_shape_profile,
    save_part_surface_profile,
)
from src.tools.build_part_shape_profiles import load_parts
from src.tools.summarize_part_shape_profiles import (
    category_profile_counts,
    profile_error_type_counts,
    profile_failures,
    profile_status_counts,
)


class PartShapeProfileServiceTest(unittest.TestCase):
    def test_surface_profile_is_saved_for_part_recall(self) -> None:
        config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)

        profile = save_part_surface_profile(
            engine,
            config,
            "3024.dat",
            sample_profile(),
            "source-hash",
        )

        self.assertEqual(profile["partId"], "3024.dat")
        self.assertEqual(profile["profileStatus"], config["profile"]["ready_status"])
        self.assertEqual(profile["sourceHash"], "source-hash")
        self.assertEqual(profile["surfaceProfile"]["surfaceHeightPlate"], [[1.0]])
        self.assertEqual(profile["connectionMask"]["topConnectionMask"], [[True]])

    def test_failed_profile_records_error_for_retry_tracking(self) -> None:
        config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)

        profile = save_failed_part_shape_profile(
            engine,
            config,
            "3024.dat",
            "source-hash",
            "mesh failed",
        )

        self.assertEqual(profile["profileStatus"], config["profile"]["failed_status"])
        self.assertEqual(profile["profileErrorType"], "unknown")
        self.assertEqual(profile["profileError"], "mesh failed")
        self.assertIsNone(profile["surfaceProfile"])

    def test_profile_error_type_classifies_non_grid_dimensions(self) -> None:
        config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )

        error_type = classify_profile_error(
            config,
            "LDraw part 60801.dat depth is not aligned to the stud grid",
        )

        self.assertEqual(error_type, "non_grid_dimension")

    def test_load_parts_can_skip_existing_shape_profiles(self) -> None:
        config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        save_part_surface_profile(
            engine,
            config,
            "3024.dat",
            sample_profile(),
            "source-hash",
        )
        Session = sessionmaker(bind=engine)
        with Session() as session:
            missing_parts = load_parts(session, config, None, None, True, None, None)
            included_parts = load_parts(session, config, None, None, False, None, None)

        self.assertEqual(missing_parts, [])
        self.assertEqual(included_parts[0]["ldraw_part_num"], "3024.dat")

    def test_shape_profile_summary_counts_statuses_categories_and_failures(self) -> None:
        config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        seed_brick_part(engine)
        save_part_surface_profile(
            engine,
            config,
            "3024.dat",
            sample_profile(),
            "source-hash",
        )
        save_failed_part_shape_profile(
            engine,
            config,
            "3005.dat",
            "brick-hash",
            "brick failed",
        )
        Session = sessionmaker(bind=engine)
        with Session() as session:
            statuses = profile_status_counts(session)
            error_types = profile_error_type_counts(session)
            categories = category_profile_counts(session, config, ["Brick", "Plate"])
            failures = profile_failures(session, config["build"]["default_batch_size"])

        self.assertEqual(statuses[config["profile"]["ready_status"]], 1)
        self.assertEqual(statuses[config["profile"]["failed_status"]], 1)
        self.assertEqual(error_types[config["profile"]["profile_error_unknown"]], 1)
        self.assertEqual(categories[0]["category"], "Brick")
        self.assertEqual(categories[0]["failed"], 1)
        self.assertEqual(categories[1]["ready"], 1)
        self.assertEqual(failures[0]["partId"], "3005.dat")
        self.assertEqual(failures[0]["errorType"], config["profile"]["profile_error_unknown"])


def test_engine():
    engine = create_engine("sqlite:///:memory:")
    LDrawFile.__table__.create(bind=engine)
    LDrawPart.__table__.create(bind=engine)
    LDrawPartGeometry.__table__.create(bind=engine)
    ensure_part_shape_profile_table(engine)
    return engine


def seed_part(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawFile(
                id=1,
                relative_path="parts/3024.dat",
                file_name="3024.dat",
                library_section="parts",
                file_role="part",
            )
        )
        session.add(
            LDrawPart(
                id=1,
                ldraw_part_num="3024.dat",
                file_id=1,
                name="Plate 1 x 1",
                category="Plate",
                relative_path="parts/3024.dat",
                file_hash="source-hash",
            )
        )
        session.add(
            LDrawPartGeometry(
                id=1,
                ldraw_part_id=1,
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
                geometry_status="parsed",
            )
        )
        session.commit()


def seed_brick_part(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawFile(
                id=2,
                relative_path="parts/3005.dat",
                file_name="3005.dat",
                library_section="parts",
                file_role="part",
            )
        )
        session.add(
            LDrawPart(
                id=2,
                ldraw_part_num="3005.dat",
                file_id=2,
                name="Brick 1 x 1",
                category="Brick",
                relative_path="parts/3005.dat",
                file_hash="brick-hash",
            )
        )
        session.commit()


def sample_profile() -> PartSurfaceProfile:
    return PartSurfaceProfile(
        part_id="3024.dat",
        ldraw_origin_to_base_ldu=8,
        ldraw_center_x_ldu=10,
        ldraw_center_z_ldu=10,
        width_stud=1,
        depth_stud=1,
        samples_per_stud_axis=1,
        surface_height_plate=((1.0,),),
        collision_intervals_plate=((((0.0, 1.0),),),),
        bottom_contact=((True,),),
        top_connection_mask=((True,),),
    )


if __name__ == "__main__":
    unittest.main()
