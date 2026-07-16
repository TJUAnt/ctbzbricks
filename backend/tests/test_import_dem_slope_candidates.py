"""Tests for DEM slope catalog database row construction."""

import unittest

from src.config.app_settings import load_json_config
from src.tools.build_dem_slope_catalog import catalog_candidate_rows


CATALOG_CONFIG = load_json_config(
    "dem_slope_catalog.json",
    ("classification", "database", "recommendation"),
)


class ImportDemSlopeCandidatesTest(unittest.TestCase):
    def test_catalog_part_and_group_are_denormalized_into_candidate_row(self) -> None:
        part = {
            "partId": "13548.dat",
            "name": "Slope Brick 45 2 x 2 Double Convex",
            "status": "profiled",
            "groupId": "slope-test",
            "currentCandidate": False,
            "capabilityEligible": True,
            "flags": {
                "obsolete": False,
                "moved": False,
                "printedVariant": False,
                "stickerVariant": False,
                "shortcutAssembly": False,
            },
            "databaseGeometry": {
                "widthStud": 2,
                "depthStud": 2,
                "heightPlate": 3,
            },
        }
        capability = {
            "groupId": "slope-test",
            "family": "double_convex",
            "states": [],
        }

        rows = catalog_candidate_rows(
            {"parts": [part], "groups": [capability]},
            {"13548.dat": 13548},
            CATALOG_CONFIG,
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["candidate_enabled"])
        self.assertEqual(rows[0]["family"], capability["family"])
        self.assertEqual(rows[0]["capability_json"], capability)
        self.assertEqual(rows[0]["catalog_payload_json"], part)

    def test_missing_ldraw_part_fails_import(self) -> None:
        part = {
            "partId": "missing.dat",
            "status": "profiled",
            "currentCandidate": False,
            "capabilityEligible": False,
            "flags": {},
            "databaseGeometry": {},
        }

        with self.assertRaisesRegex(ValueError, "missing.dat"):
            catalog_candidate_rows(
                {"parts": [part], "groups": []},
                {},
                CATALOG_CONFIG,
            )

    def test_excluded_family_is_not_enabled_as_candidate(self) -> None:
        excluded_family = CATALOG_CONFIG["recommendation"]["excluded_families"][0]
        part = {
            "partId": "inverted.dat",
            "name": "Slope Brick 45 2 x 2 Inverted",
            "status": "profiled",
            "groupId": "slope-inverted",
            "currentCandidate": False,
            "capabilityEligible": True,
            "flags": {
                "obsolete": False,
                "moved": False,
                "printedVariant": False,
                "stickerVariant": False,
                "shortcutAssembly": False,
            },
            "databaseGeometry": {
                "widthStud": 2,
                "depthStud": 2,
                "heightPlate": 3,
            },
        }
        capability = {
            "groupId": "slope-inverted",
            "family": excluded_family,
            "states": [],
        }

        rows = catalog_candidate_rows(
            {"parts": [part], "groups": [capability]},
            {"inverted.dat": 1},
            CATALOG_CONFIG,
        )

        self.assertFalse(rows[0]["candidate_enabled"])

    def test_excluded_part_trait_is_not_enabled_in_allowed_group(self) -> None:
        part = {
            "partId": "13547.dat",
            "name": "Slope Brick Curved 4 x 1 Inverted",
            "status": "profiled",
            "groupId": "slope-curved",
            "currentCandidate": False,
            "capabilityEligible": True,
            "flags": {
                "obsolete": False,
                "moved": False,
                "printedVariant": False,
                "stickerVariant": False,
                "shortcutAssembly": False,
            },
            "databaseGeometry": {
                "widthStud": 4,
                "depthStud": 1,
                "heightPlate": 3,
            },
        }
        capability = {
            "groupId": "slope-curved",
            "family": "curved",
            "states": [],
        }

        rows = catalog_candidate_rows(
            {"parts": [part], "groups": [capability]},
            {"13547.dat": 13547},
            CATALOG_CONFIG,
        )

        self.assertFalse(rows[0]["candidate_enabled"])


if __name__ == "__main__":
    unittest.main()
