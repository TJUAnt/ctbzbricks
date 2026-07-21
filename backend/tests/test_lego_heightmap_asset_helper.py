"""Unit tests for LEGO heightmap asset persistence."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from src.lego.heightmap_asset_helper import load_heightmap_asset, save_heightmap_asset
from src.services.model_asset_service import (
    ensure_model_asset_table,
    paginated_model_assets,
    save_lego_heightmap_model_asset,
)


class LegoHeightmapAssetHelperTest(unittest.TestCase):
    def test_saved_heightmap_asset_can_be_loaded_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = {
                "model_store_path": str(Path(directory)),
                "model_file_extension": ".json",
                "model_id_hex_length": 32,
                "text_encoding": "utf-8",
            }
            asset = {
                "schema": "lego-heightmap-v1",
                "source": "test.geojson",
                "bounds": {"west": 0, "south": 0, "east": 1, "north": 1},
                "scale": {"horizontalKmPerStud": 1, "verticalMetersPerPlate": 10},
                "metrics": {
                    "widthStud": 2,
                    "depthStud": 3,
                    "maxHeightPlate": 4,
                    "validCellCount": 5,
                    "totalCellCount": 6,
                },
                "cells": [],
            }

            metadata = save_heightmap_asset(config, asset, "lego model")
            loaded_asset = load_heightmap_asset(config, metadata["modelId"])

            self.assertEqual(metadata["name"], "lego model")
            self.assertEqual(metadata["source"], "test.geojson")
            self.assertEqual(metadata["columns"], 2)
            self.assertEqual(metadata["rows"], 3)
            self.assertEqual(metadata["maxHeightPlate"], 4)
            self.assertEqual(metadata["validCellCount"], 5)
            self.assertEqual(loaded_asset["modelId"], metadata["modelId"])
            self.assertEqual(loaded_asset["name"], "lego model")
            self.assertEqual(loaded_asset["metrics"], asset["metrics"])

    def test_saved_heightmap_metadata_is_persisted_to_model_assets(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ensure_model_asset_table(engine)
        with tempfile.TemporaryDirectory() as directory:
            terrain_config = {
                "model_store_path": str(Path(directory)),
                "model_file_extension": ".json",
                "model_id_hex_length": 32,
                "text_encoding": "utf-8",
            }
            asset_config = {
                "lego_heightmap_model_type": "lego_heightmap",
                "lego_heightmap_source_type": "dem_heightmap",
                "complete_status": "complete",
            }
            asset = {
                "schema": "lego-heightmap-v1",
                "source": "test.geojson",
                "bounds": {"west": 0, "south": 0, "east": 1, "north": 1},
                "scale": {"horizontalKmPerStud": 1, "verticalMetersPerPlate": 10},
                "metrics": {
                    "widthStud": 2,
                    "depthStud": 3,
                    "maxHeightPlate": 4,
                    "validCellCount": 5,
                    "totalCellCount": 6,
                },
                "cells": [],
            }
            model = save_heightmap_asset(terrain_config, asset, "lego model")

            save_lego_heightmap_model_asset(
                engine,
                asset_config,
                terrain_config,
                asset,
                model,
                "zh-CN",
            )
            page = paginated_model_assets(engine, 1, 10)

            self.assertEqual(page["total"], 1)
            self.assertEqual(page["items"][0]["modelType"], "lego_heightmap")
            self.assertEqual(page["items"][0]["sourceType"], "dem_heightmap")
            self.assertEqual(page["items"][0]["columns"], 2)
            self.assertEqual(page["items"][0]["rows"], 3)
            self.assertEqual(page["items"][0]["validSampleCount"], 5)
            self.assertEqual(page["items"][0]["contentLocale"], "zh-CN")


if __name__ == "__main__":
    unittest.main()
