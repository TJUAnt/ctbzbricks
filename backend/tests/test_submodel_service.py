"""Unit tests for reusable LDraw submodels."""

import unittest

from sqlalchemy import create_engine

from src.config.submodel_config import REQUIRED_SUBMODEL_CONFIG_KEYS
from src.config.app_settings import load_json_config
from src.services.submodel_service import (
    create_submodel,
    ensure_submodel_tables,
    get_submodel,
    parse_ldraw_submodel_parts,
)


class SubmodelServiceTest(unittest.TestCase):
    def test_parse_ldraw_submodel_parts_extracts_type_one_lines(self) -> None:
        config = load_json_config("submodel.json", REQUIRED_SUBMODEL_CONFIG_KEYS)

        parts = parse_ldraw_submodel_parts(sample_ldraw_content(), config)

        self.assertEqual(len(parts), config["ldraw"]["minimum_part_count"])
        self.assertEqual(parts[0]["lineNo"], config["ldraw"]["line_number_start"])
        self.assertEqual(parts[0]["colorCode"], "16")
        self.assertEqual(parts[0]["ldrawPartNum"], "3023.dat")
        self.assertEqual(parts[1]["position"]["x"], 20.0)

    def test_create_submodel_persists_parts_color_percentages_and_connectors(self) -> None:
        config = load_json_config("submodel.json", REQUIRED_SUBMODEL_CONFIG_KEYS)
        engine = create_engine("sqlite:///:memory:")
        ensure_submodel_tables(engine)

        saved_submodel = create_submodel(engine, config, sample_payload())
        loaded_submodel = get_submodel(engine, saved_submodel["id"])

        self.assertEqual(saved_submodel["name"], "door module")
        self.assertEqual(saved_submodel["remarks"], "Reusable hinged detail")
        self.assertEqual(saved_submodel["colorPercentages"][0]["percentage"], 60)
        self.assertEqual(loaded_submodel["parts"][1]["ldrawPartNum"], "3024.dat")
        self.assertEqual(
            loaded_submodel["connectionPoints"][0]["normalizedConnectorType"],
            "stud",
        )

    def test_create_submodel_rejects_single_part_assembly(self) -> None:
        config = load_json_config("submodel.json", REQUIRED_SUBMODEL_CONFIG_KEYS)
        engine = create_engine("sqlite:///:memory:")
        ensure_submodel_tables(engine)
        payload = sample_payload()
        payload["ldrawContent"] = sample_ldraw_content().split(
            config["ldraw"]["line_separator"]
        )[0]

        with self.assertRaisesRegex(ValueError, config["errors"]["insufficient_parts"]):
            create_submodel(engine, config, payload)


def sample_ldraw_content() -> str:
    return "\n".join(
        [
            "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3023.dat",
            "1 4 20 0 0 1 0 0 0 1 0 0 0 1 3024.dat",
        ]
    )


def sample_payload() -> dict:
    return {
        "name": "door module",
        "ldrawContent": sample_ldraw_content(),
        "colorPercentages": [
            {"colorCode": "16", "percentage": 60},
            {"colorCode": "4", "percentage": 40},
        ],
        "remarks": "Reusable hinged detail",
        "connectionPoints": [
            {
                "partLineNo": 1,
                "connectorLabel": "top-stud",
                "connectorKind": "snap",
                "normalizedConnectorType": "stud",
                "connectorGender": "male",
                "position": {"x": 0, "y": 0, "z": 0},
                "orientation": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "metadata": {"usage": "attach roof"},
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
