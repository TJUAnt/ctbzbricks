"""Unit tests for part search request parsing."""
import unittest

from src.api.schemas.part_search import PartSearchRequest
from src.services.part_search_service import (
    logical_size_from_query,
    required_connectors_from_query,
    search_kwargs_from_request,
    search_kwargs_options_from_request,
)


SEARCH_CONFIG = {
    "default_limit": 24,
    "max_limit": 60,
    "ldraw_suffix": ".dat",
    "logical_size_pattern": "(\\d+(?:\\.\\d+)?)\\s*x\\s*(\\d+(?:\\.\\d+)?)(?:\\s*x\\s*(\\d+(?:\\.\\d+)?))?",
    "logical_size_match_groups": {
        "width": 1,
        "depth": 2,
        "height": 3,
    },
    "part_number_pattern": "^[a-zA-Z0-9_]+(?:[a-zA-Z0-9_]+)?$",
    "part_number_rejected_terms": [" ", "x"],
    "category_terms": [
        {
            "terms": ["plate", "板"],
            "category": "Plate",
            "default_height_plate": 1,
        },
        {
            "terms": ["brick", "砖"],
            "category": "Brick",
            "default_height_plate": 3,
        },
    ],
    "connector_terms": [
        {
            "terms": ["technic hole", "pin hole", "孔"],
            "type": "technic_pin_hole",
            "gender": "F",
        }
    ],
    "side_terms": ["side", "侧", "侧向"],
    "vertical_terms": ["vertical", "top", "bottom", "垂直", "顶部", "底部"],
    "direction_groups": {
        "side": "side",
        "vertical": "vertical",
    },
    "connector_requirement_fields": {
        "type": "type",
        "gender": "gender",
        "direction_group": "direction_group",
        "min_count": "min_count",
    },
    "default_connector_min_count": 1,
}


class PartSearchServiceTest(unittest.TestCase):
    def test_logical_size_uses_category_default_height(self) -> None:
        self.assertEqual(
            logical_size_from_query("2x4 plate", SEARCH_CONFIG),
            (2.0, 4.0, 1.0),
        )

    def test_connector_query_requires_side_group(self) -> None:
        self.assertEqual(
            required_connectors_from_query("side technic hole", SEARCH_CONFIG),
            [
                {
                    "type": "technic_pin_hole",
                    "gender": "F",
                    "min_count": 1,
                    "direction_group": "side",
                }
            ],
        )

    def test_part_number_query_uses_rebrickable_part_num(self) -> None:
        request = PartSearchRequest(
            query="3020",
            strict_bbox=True,
            include_substitutes=False,
        )
        self.assertEqual(
            search_kwargs_from_request(request, SEARCH_CONFIG)["rebrickable_part_num"],
            "3020",
        )

    def test_size_only_query_searches_configured_category_defaults(self) -> None:
        request = PartSearchRequest(
            query="2x4",
            strict_bbox=True,
            include_substitutes=False,
        )
        self.assertEqual(
            search_kwargs_options_from_request(request, SEARCH_CONFIG),
            [
                {
                    "strict_bbox": True,
                    "category": ["Plate"],
                    "include_substitutes": False,
                    "limit": None,
                    "logical_size": (2.0, 4.0, 1.0),
                },
                {
                    "strict_bbox": True,
                    "category": ["Brick"],
                    "include_substitutes": False,
                    "limit": None,
                    "logical_size": (2.0, 4.0, 3.0),
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
