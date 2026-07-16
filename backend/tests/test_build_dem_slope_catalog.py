"""Tests for DEM slope catalog candidate classification."""

import unittest

from src.config.app_settings import load_json_config
from src.tools.build_dem_slope_catalog import capability_eligible, part_flags


CATALOG_CONFIG = load_json_config(
    "dem_slope_catalog.json",
    ("classification",),
)


class BuildDemSlopeCatalogTest(unittest.TestCase):
    def flags(
        self,
        part_id: str,
        name: str,
        has_printed_relationship: bool = False,
    ) -> dict[str, bool]:
        return part_flags(
            part_id,
            name,
            has_printed_relationship,
            CATALOG_CONFIG,
        )

    def test_geometric_with_description_remains_eligible(self) -> None:
        flags = self.flags(
            "13548.dat",
            "Slope Brick 45 2 x 2 Double Convex with 45 Corner",
        )

        self.assertFalse(flags["printedVariant"])
        self.assertFalse(flags["stickerVariant"])
        self.assertFalse(flags["shortcutAssembly"])
        self.assertTrue(
            capability_eligible({"status": "profiled", "flags": flags})
        )

    def test_explicit_pattern_name_is_printed_variant(self) -> None:
        flags = self.flags(
            "13548pz1.dat",
            "Slope Brick with White Dots Pattern",
        )

        self.assertTrue(flags["printedVariant"])

    def test_decorated_part_id_is_sticker_variant_without_sticker_name(self) -> None:
        flags = self.flags(
            "4515d06.dat",
            'Slope Brick with Black "C 26" and Coast Guard Logo',
        )

        self.assertTrue(flags["stickerVariant"])

    def test_plain_mould_variant_suffix_is_not_sticker_variant(self) -> None:
        flags = self.flags(
            "3049d.dat",
            "Slope Brick Double with Bottom Stud Holder",
        )

        self.assertFalse(flags["stickerVariant"])

    def test_rebrickable_print_relationship_is_printed_variant(self) -> None:
        flags = self.flags(
            "test.dat",
            "Slope Brick with Graphic",
            has_printed_relationship=True,
        )

        self.assertTrue(flags["printedVariant"])

    def test_complete_shortcut_is_not_candidate_eligible(self) -> None:
        flags = self.flags(
            "3135c01.dat",
            "Slope Brick with Crane Arm and Hook (Complete)",
        )

        self.assertTrue(flags["shortcutAssembly"])
        self.assertFalse(
            capability_eligible({"status": "profiled", "flags": flags})
        )


if __name__ == "__main__":
    unittest.main()
