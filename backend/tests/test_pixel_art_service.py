"""Unit tests for pixel art quantization and persistence."""

from io import BytesIO
import unittest

from PIL import Image
from sqlalchemy import create_engine

from src.api.schemas.pixel_art import PixelArtGenerateSettings
from src.pixel_art.quantization import create_pixel_art_asset
from src.services.pixel_art_service import (
    ensure_pixel_art_project_table,
    load_pixel_art_project,
    paginated_pixel_art_projects,
    save_pixel_art_project,
    update_pixel_art_project_pixels,
)


PIXEL_ART_CONFIG = {
    "asset_schema": "pixel-art-v1",
    "storage": {
        "project_id_hex_length": 32,
        "complete_status": "complete",
        "default_page": 1,
        "default_page_size": 12,
        "max_page_size": 48,
        "text_encoding": "utf-8",
    },
    "image": {
        "supported_content_types": ["image/png"],
        "alpha_modes": ["LA", "PA", "RGBA"],
        "rgba_mode": "RGBA",
        "alpha_background_rgba": [255, 255, 255, 255],
        "processing_mode": "RGB",
        "grayscale_mode": "L",
        "ycbcr_mode": "YCbCr",
        "luminance_channel_index": 0,
        "blue_difference_channel_index": 1,
        "red_difference_channel_index": 2,
        "preview_format": "PNG",
        "preview_content_type": "image/png",
    },
    "quantization": {
        "supported_color_counts": [2],
        "maximum_grid_width": 8,
        "maximum_grid_height": 8,
        "maximum_total_cells": 64,
        "minimum_dimension": 1,
        "maximum_channel_value": 255,
        "hex_color_format": "#{:02X}{:02X}{:02X}",
        "feature_score_precision": 4,
        "color_distance_power": 2,
    },
    "algorithms": {
        "default": "photo_illustration",
        "generators": {
            "photo_illustration": "photo_illustration",
            "logo_text": "logo_text",
            "side_mixed_plate_brick_pixel": "side_mixed_plate_brick_pixel",
        },
        "photo_illustration": {
            "id": "photo_illustration",
            "generator": "photo_illustration",
            "resample_method": "box",
            "feature_score": 0,
            "edge_strength": 0,
            "local_contrast": 0,
        },
        "logo_text": {
            "id": "logo_text",
            "generator": "logo_text",
            "feature_score": 0,
            "edge_strength": 0,
            "local_contrast": 0,
        },
        "side_mixed_plate_brick_pixel": {
            "id": "side_mixed_plate_brick_pixel",
            "generator": "side_mixed_plate_brick_pixel",
            "resample_method": "box",
            "feature_score": 0,
            "edge_strength": 0,
            "local_contrast": 0,
            "side_layout": {
                "pixel_width_plates": 1,
                "pixel_height_plates": 1,
                "brick_height_plates": 3,
                "horizontal_step": 1,
                "vertical_step": 1,
                "plate_part_type": "plate",
                "brick_part_type": "brick",
                "single_role": "single",
                "start_role": "start",
                "continue_role": "continue",
            },
        },
    },
    "kmeans": {
        "maximum_sample_pixels": 128,
        "maximum_iterations": 8,
        "convergence_distance": 0.5,
    },
    "preprocessing": {
        "brightness": {"minimum": 0.7, "maximum": 1.3},
        "contrast": {"minimum": 0.7, "maximum": 1.6},
        "saturation": {"minimum": 0.5, "maximum": 1.5},
        "sharpness": {"minimum": 0.7, "maximum": 1.8},
        "localContrast": {"minimum": 0, "maximum": 1},
        "local_contrast_blend_scale": 1,
    },
    "feature_analysis": {
        "edge_weight": 0.5,
        "local_contrast_weight": 0.3,
        "color_variance_weight": 0.2,
        "medium_feature_threshold": 0.2,
        "high_feature_threshold": 0.55,
        "light_feature_threshold": 0.05,
        "lightness_threshold": 0.75,
        "saturation_threshold": 0.25,
        "edge_weight_floor": 0.15,
        "luminance_red_weight": 0.2126,
        "luminance_green_weight": 0.7152,
        "luminance_blue_weight": 0.0722,
    },
    "metadata": {
        "source_type": "uploaded_image",
    },
    "errors": {
        "unsupported_image_type": "Unsupported image type",
        "invalid_settings": "Invalid pixel art settings",
        "invalid_crop": "Invalid crop area",
        "invalid_grid": "Invalid output grid",
        "invalid_color_count": "Invalid color count",
        "project_not_found": "Pixel art project not found",
    },
}


class PixelArtServiceTest(unittest.TestCase):
    def test_quantized_pixel_art_asset_has_expected_grid_and_palette(self) -> None:
        image_bytes = png_bytes()
        settings = generation_settings()

        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            image_bytes,
            "source.png",
            "image/png",
            settings,
        )

        self.assertEqual(asset["schema"], "pixel-art-v1")
        self.assertEqual(asset["gridWidth"], 2)
        self.assertEqual(asset["gridHeight"], 2)
        self.assertEqual(len(asset["pixels"]), 4)
        self.assertLessEqual(len(asset["palette"]), 2)
        self.assertIn("sourceColor", asset["pixels"][0])
        self.assertIn("featureScore", asset["pixels"][0])

    def test_photo_illustration_algorithm_maps_resized_pixels_to_kmeans_palette(self) -> None:
        settings = generation_settings()

        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            png_bytes(),
            "source.png",
            "image/png",
            settings,
        )

        self.assertEqual({color["rgb"] for color in asset["palette"]}, {"#FF0000", "#0000FF"})
        self.assertEqual({pixel["featureScore"] for pixel in asset["pixels"]}, {0})

    def test_logo_text_algorithm_uses_majority_vote_after_palette_mapping(self) -> None:
        settings = PixelArtGenerateSettings.model_validate(
            {
                "algorithm": "logo_text",
                "gridWidth": 2,
                "gridHeight": 2,
                "colorCount": 2,
                "crop": {"x": 0, "y": 0, "width": 4, "height": 4},
                "preprocessing": {
                    "brightness": 1,
                    "contrast": 1,
                    "saturation": 1,
                    "sharpness": 1,
                    "localContrast": 0,
                    "preserveLightDetails": True,
                },
            }
        )

        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            logo_text_png_bytes(),
            "source.png",
            "image/png",
            settings,
        )

        self.assertEqual(asset["pixels"][0]["rgb"], "#000000")
        self.assertEqual(asset["pixels"][1]["rgb"], "#FF0000")
        self.assertEqual(asset["pixels"][2]["rgb"], "#FF0000")
        self.assertEqual(asset["pixels"][3]["rgb"], "#FF0000")

    def test_side_mixed_plate_brick_pixel_marks_vertical_brick_and_plate_runs(self) -> None:
        settings = PixelArtGenerateSettings.model_validate(
            {
                "algorithm": "side_mixed_plate_brick_pixel",
                "gridWidth": 2,
                "gridHeight": 4,
                "colorCount": 2,
                "crop": {"x": 0, "y": 0, "width": 2, "height": 4},
                "preprocessing": {
                    "brightness": 1,
                    "contrast": 1,
                    "saturation": 1,
                    "sharpness": 1,
                    "localContrast": 0,
                    "preserveLightDetails": True,
                },
            }
        )

        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            side_mixed_png_bytes(),
            "source.png",
            "image/png",
            settings,
        )

        left_column = [pixel for pixel in asset["pixels"] if pixel["x"] == 0]
        self.assertEqual(left_column[0]["sidePartType"], "brick")
        self.assertEqual(left_column[0]["sidePartRole"], "start")
        self.assertEqual(left_column[0]["sidePartHeightPlates"], 3)
        self.assertEqual(left_column[1]["sidePartRole"], "continue")
        self.assertEqual(left_column[2]["sidePartRole"], "continue")
        self.assertEqual(left_column[3]["sidePartType"], "plate")
        self.assertEqual(left_column[3]["sidePartHeightPlates"], 1)
        self.assertEqual(left_column[3]["sidePixelWidthPlates"], 1)

    def test_saved_pixel_art_project_can_be_loaded_from_database(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ensure_pixel_art_project_table(engine)
        image_bytes = png_bytes()
        settings = generation_settings()
        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            image_bytes,
            "source.png",
            "image/png",
            settings,
        )

        saved = save_pixel_art_project(
            engine,
            PIXEL_ART_CONFIG,
            "pixel model",
            image_bytes,
            asset,
        )
        loaded = load_pixel_art_project(engine, PIXEL_ART_CONFIG, saved["modelId"])

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "pixel model")
        self.assertEqual(loaded["gridWidth"], 2)
        self.assertEqual(loaded["gridHeight"], 2)
        self.assertEqual(len(loaded["pixels"]), 4)
        self.assertTrue(loaded["previewImage"].startswith("data:image/png;base64,"))

    def test_pixel_art_project_pixels_can_be_updated(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ensure_pixel_art_project_table(engine)
        image_bytes = png_bytes()
        settings = generation_settings()
        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            image_bytes,
            "source.png",
            "image/png",
            settings,
        )
        saved = save_pixel_art_project(
            engine,
            PIXEL_ART_CONFIG,
            "pixel model",
            image_bytes,
            asset,
        )
        updated_pixels = [
            {**pixel, "rgb": "#00FF00", "colorIndex": 0}
            for pixel in asset["pixels"]
        ]
        updated_palette = [{"colorIndex": 0, "rgb": "#00FF00", "count": 4}]

        updated = update_pixel_art_project_pixels(
            engine,
            PIXEL_ART_CONFIG,
            saved["modelId"],
            updated_palette,
            updated_pixels,
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated["palette"], updated_palette)
        self.assertEqual(updated["pixels"], updated_pixels)

    def test_saved_pixel_art_projects_can_be_listed(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ensure_pixel_art_project_table(engine)
        image_bytes = png_bytes()
        settings = generation_settings()
        asset = create_pixel_art_asset(
            PIXEL_ART_CONFIG,
            image_bytes,
            "source.png",
            "image/png",
            settings,
        )
        save_pixel_art_project(engine, PIXEL_ART_CONFIG, "pixel model", image_bytes, asset)

        page = paginated_pixel_art_projects(engine, PIXEL_ART_CONFIG, 1, 12)

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["name"], "pixel model")
        self.assertEqual(page["items"][0]["gridWidth"], 2)
        self.assertTrue(page["items"][0]["previewImage"].startswith("data:image/png;base64,"))


def generation_settings() -> PixelArtGenerateSettings:
    return PixelArtGenerateSettings.model_validate(
        {
            "algorithm": "photo_illustration",
            "gridWidth": 2,
            "gridHeight": 2,
            "colorCount": 2,
            "crop": {"x": 0, "y": 0, "width": 4, "height": 4},
            "preprocessing": {
                "brightness": 1,
                "contrast": 1,
                "saturation": 1,
                "sharpness": 1,
                "localContrast": 0,
                "preserveLightDetails": True,
            },
        }
    )


def png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4))
    pixels = []
    for y in range(4):
        for x in range(4):
            pixels.append((255, 0, 0) if x < 2 else (0, 0, 255))
    image.putdata(pixels)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def logo_text_png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), (255, 0, 0))
    image.putpixel((0, 0), (0, 0, 0))
    image.putpixel((1, 0), (0, 0, 0))
    image.putpixel((0, 1), (0, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def side_mixed_png_bytes() -> bytes:
    image = Image.new("RGB", (2, 4))
    pixels = []
    for _ in range(4):
        pixels.extend([(255, 0, 0), (0, 0, 255)])
    image.putdata(pixels)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
