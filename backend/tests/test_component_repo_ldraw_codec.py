"""Golden tests for Component Repo LDraw deserializer and serializer."""

from pathlib import Path
import unittest

from src.component_repo.ldraw_deserializer import deserialize_ldraw_document
from src.component_repo.ldraw_serializer import serialize_ldraw_document
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class ComponentRepoLDrawCodecTest(unittest.TestCase):
    def test_deserialize_repo_components_roundtrips(self) -> None:
        config = component_repo_config()
        fixtures = repo_ldraw_fixture_paths()

        self.assertGreaterEqual(len(fixtures), 1)
        for path in fixtures:
            with self.subTest(path=str(path.relative_to(WORKSPACE_ROOT))):
                document = deserialize_ldraw_document(
                    path.read_text(encoding="utf-8"),
                    config,
                )
                serialized = serialize_ldraw_document(document, config)
                reparsed = deserialize_ldraw_document(serialized, config)

                self.assertGreaterEqual(len(document.models), 1)
                self.assertGreaterEqual(len(document.leaf_part_references()), 1)
                self.assertEqual(len(reparsed.models), len(document.models))
                self.assertEqual(
                    len(reparsed.leaf_part_references()),
                    len(document.leaf_part_references()),
                )
                self.assertEqual(
                    len(reparsed.submodel_references()),
                    len(document.submodel_references()),
                )
                self.assertEqual(reparsed.bom(), document.bom())

    def test_deserialize_wheel_shell_component2_preserves_mpd_structure(self) -> None:
        config = component_repo_config()
        document = deserialize_ldraw_document(
            fixture_path("repo/8cars/wheel_shell_component2.ldr").read_text(encoding="utf-8"),
            config,
        )

        self.assertEqual(document.parser_version, config["ldraw"]["parser_version"])
        self.assertEqual(document.root_model_id, "model_0001")
        self.assertEqual(len(document.models), 4)
        self.assertEqual([model.source_name for model in document.models], [
            "wheel_shell_component",
            "wheel_shell_component",
            "wheel 3 Copy 4",
            "SubModel Group 8",
        ])
        self.assertEqual(len(document.leaf_part_references()), 3)
        self.assertEqual(len(document.submodel_references()), 3)
        self.assertEqual(
            document.bom(),
            {
                "35789.dat": 1,
                "72206p01.dat": 1,
                "6232.dat": 1,
            },
        )
        self.assertEqual(
            document.models[0].references[0].target_model_id,
            "model_0002",
        )
        self.assertEqual(
            document.models[2].references[0].target_model_id,
            "model_0004",
        )
        first_leaf = document.leaf_part_references()[0]
        self.assertEqual(first_leaf.reference_name, "35789.dat")
        self.assertEqual(first_leaf.color_code, "15")
        self.assertEqual(first_leaf.transform.position, (-40.0, -48.0, 120.0))
        self.assertEqual(first_leaf.transform.matrix, (-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
        self.assertEqual(
            [issue.issue_type for issue in document.parse_issues],
            [config["ldraw"]["issues"]["duplicate_model_name"]],
        )

    def test_deserialize_records_studio_type11_as_parse_issue(self) -> None:
        config = component_repo_config()
        content = (
            "0 FILE sample\n"
            "11 16 123 False 0 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
            "0 NOFILE\n"
        )

        document = deserialize_ldraw_document(content, config)

        self.assertEqual(len(document.models), 1)
        self.assertEqual(len(document.leaf_part_references()), 0)
        self.assertEqual(len(document.parse_issues), 1)
        self.assertEqual(
            document.parse_issues[0].issue_type,
            config["ldraw"]["issues"]["unsupported_line_type"],
        )

    def test_serialize_then_deserialize_keeps_component_structure_counts(self) -> None:
        config = component_repo_config()
        document = deserialize_ldraw_document(
            fixture_path("repo/8cars/wheel_shell_component2.ldr").read_text(encoding="utf-8"),
            config,
        )

        serialized = serialize_ldraw_document(document, config)
        reparsed = deserialize_ldraw_document(serialized, config)

        self.assertIn("0 FILE wheel_shell_component", serialized)
        self.assertIn("1 15 -40.000000 -48.000000 120.000000", serialized)
        self.assertEqual(len(reparsed.models), len(document.models))
        self.assertEqual(len(reparsed.leaf_part_references()), len(document.leaf_part_references()))
        self.assertEqual(len(reparsed.submodel_references()), len(document.submodel_references()))
        self.assertEqual(reparsed.bom(), document.bom())


def component_repo_config() -> dict:
    return load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )


def fixture_path(relative_path: str) -> Path:
    return WORKSPACE_ROOT / relative_path


def repo_ldraw_fixture_paths() -> list[Path]:
    repo_root = WORKSPACE_ROOT / "repo"
    return sorted([*repo_root.rglob("*.ldr"), *repo_root.rglob("*.mpd")])
