"""API tests for backend-owned colored heightmap generation."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.api.errors import DomainError
from src.api.routes.lego_heightmap import create_lego_heightmap_router
from src.api.schemas.lego_heightmap import LegoHeightmapFromDemRequest


API_CONFIG = {
    "routes": {
        "lego_heightmap_models": "/api/lego/heightmap/models",
        "lego_heightmap_from_dem": "/api/lego/heightmap/models/from-dem",
        "lego_heightmap_model": "/api/lego/heightmap/models/{model_id}",
    }
}
TERRAIN_CONFIG = {
    "http_status": {"bad_request": 400, "not_found": 404},
}
HEIGHTMAP_CONFIG = {"model_store_path": "heightmaps"}
SCALE = {
    "horizontalKmPerStud": 10,
    "verticalMetersPerPlate": 250,
    "aggregation": "percentile",
    "minCoverageRatio": 0.25,
}


class LegoHeightmapApiTest(unittest.TestCase):
    def setUp(self) -> None:
        router = create_lego_heightmap_router(API_CONFIG, TERRAIN_CONFIG, HEIGHTMAP_CONFIG)
        routes = {route.path: route for route in router.routes}
        self.endpoint = routes[API_CONFIG["routes"]["lego_heightmap_from_dem"]].endpoint
        self.request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    db_engine=object(),
                    model_asset_config={"model": "asset"},
                )
            )
        )
        self.body = LegoHeightmapFromDemRequest(
            name="colored heightmap",
            modelId="dem-model",
            contentLocale="zh-CN",
            scale=SCALE,
        )

    @patch("src.api.routes.lego_heightmap.save_lego_heightmap_model_asset")
    @patch(
        "src.api.routes.lego_heightmap.save_heightmap_asset",
        return_value={"modelId": "heightmap-model"},
    )
    @patch(
        "src.api.routes.lego_heightmap.create_colored_heightmap_asset",
        return_value={"source": "dem", "cells": []},
    )
    @patch("src.api.routes.lego_heightmap.load_model_asset", return_value={"source": "dem"})
    def test_generates_saves_and_registers_colored_heightmap(
        self,
        load_dem,
        generate_heightmap,
        save_heightmap,
        register_heightmap,
    ) -> None:
        result = self.endpoint(self.body, self.request)

        load_dem.assert_called_once_with(TERRAIN_CONFIG, "dem-model")
        generate_heightmap.assert_called_once_with(
            {"source": "dem"},
            "dem-model",
            SCALE,
            TERRAIN_CONFIG,
        )
        save_heightmap.assert_called_once_with(
            HEIGHTMAP_CONFIG,
            {"source": "dem", "cells": []},
            "colored heightmap",
        )
        register_heightmap.assert_called_once()
        self.assertEqual(result, {"modelId": "heightmap-model"})

    @patch(
        "src.api.routes.lego_heightmap.load_model_asset",
        side_effect=ValueError("DEM model not found"),
    )
    def test_missing_dem_returns_not_found(self, _load_dem) -> None:
        with self.assertRaises(DomainError) as raised:
            self.endpoint(self.body, self.request)

        self.assertEqual(raised.exception.http_status, TERRAIN_CONFIG["http_status"]["not_found"])
        self.assertEqual(raised.exception.code, "terrain.model_not_found")
        self.assertEqual(raised.exception.params, {"modelId": "dem-model"})


if __name__ == "__main__":
    unittest.main()
