"""Image quantization for pixel art projects."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
from math import sqrt
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from src.api.schemas.pixel_art import PixelArtGenerateSettings


RESAMPLE_METHODS = {
    "box": Image.Resampling.BOX,
}


def create_pixel_art_asset(
    config: dict[str, Any],
    image_bytes: bytes,
    source_file_name: str,
    content_type: str,
    settings: PixelArtGenerateSettings,
) -> dict[str, Any]:
    validate_content_type(config, content_type)
    validate_settings(config, settings)

    source_image = Image.open(BytesIO(image_bytes))
    image = normalized_source_image(config, source_image)
    validate_crop(config, image.size, settings)
    cropped_image = image.crop(crop_box(settings))
    mapped_image, cell_metadata = pixel_art_image(config, cropped_image, settings)
    pixels = pixel_cells(config, mapped_image, cell_metadata)
    palette = palette_summary(pixels)
    preview_bytes = preview_image_bytes(config, mapped_image)
    return {
        "schema": config["asset_schema"],
        "source": source_file_name,
        "sourceContentType": content_type,
        "algorithm": settings.algorithm,
        "gridWidth": settings.gridWidth,
        "gridHeight": settings.gridHeight,
        "colorCount": settings.colorCount,
        "crop": settings.crop.model_dump(),
        "palette": palette,
        "pixels": pixels,
        "previewBytes": preview_bytes,
    }


def validate_content_type(config: dict[str, Any], content_type: str) -> None:
    if content_type not in config["image"]["supported_content_types"]:
        raise ValueError(config["errors"]["unsupported_image_type"])


def validate_settings(config: dict[str, Any], settings: PixelArtGenerateSettings) -> None:
    quantization = config["quantization"]
    validate_algorithm(config, settings)
    if settings.colorCount not in quantization["supported_color_counts"]:
        raise ValueError(config["errors"]["invalid_color_count"])
    if (
        settings.gridWidth < quantization["minimum_dimension"]
        or settings.gridHeight < quantization["minimum_dimension"]
        or settings.gridWidth > quantization["maximum_grid_width"]
        or settings.gridHeight > quantization["maximum_grid_height"]
        or settings.gridWidth * settings.gridHeight > quantization["maximum_total_cells"]
    ):
        raise ValueError(config["errors"]["invalid_grid"])
    validate_preprocessing_settings(config, settings)


def validate_algorithm(config: dict[str, Any], settings: PixelArtGenerateSettings) -> None:
    supported_algorithms = {algorithm["id"] for algorithm in configured_algorithms(config)}
    if settings.algorithm not in supported_algorithms:
        raise ValueError(config["errors"]["invalid_settings"])


def configured_algorithms(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        algorithm
        for algorithm in config["algorithms"].values()
        if isinstance(algorithm, dict) and "id" in algorithm
    ]


def algorithm_config_for_settings(
    config: dict[str, Any],
    settings: PixelArtGenerateSettings,
) -> dict[str, Any]:
    for algorithm in configured_algorithms(config):
        if settings.algorithm == algorithm["id"]:
            return algorithm
    raise ValueError(config["errors"]["invalid_settings"])


def validate_preprocessing_settings(
    config: dict[str, Any],
    settings: PixelArtGenerateSettings,
) -> None:
    preprocessing = config["preprocessing"]
    for setting_name, setting_config in preprocessing.items():
        if not isinstance(setting_config, dict):
            continue
        setting_value = getattr(settings.preprocessing, setting_name)
        if setting_value < setting_config["minimum"] or setting_value > setting_config["maximum"]:
            raise ValueError(config["errors"]["invalid_settings"])


def validate_crop(
    config: dict[str, Any],
    image_size: tuple[int, int],
    settings: PixelArtGenerateSettings,
) -> None:
    image_width, image_height = image_size
    minimum_dimension = config["quantization"]["minimum_dimension"]
    coordinate_origin = minimum_dimension - minimum_dimension
    if (
        settings.crop.width < minimum_dimension
        or settings.crop.height < minimum_dimension
        or settings.crop.x < coordinate_origin
        or settings.crop.y < coordinate_origin
        or settings.crop.x + settings.crop.width > image_width
        or settings.crop.y + settings.crop.height > image_height
    ):
        raise ValueError(config["errors"]["invalid_crop"])


def crop_box(settings: PixelArtGenerateSettings) -> tuple[int, int, int, int]:
    return (
        settings.crop.x,
        settings.crop.y,
        settings.crop.x + settings.crop.width,
        settings.crop.y + settings.crop.height,
    )


def normalized_source_image(config: dict[str, Any], source_image: Image.Image) -> Image.Image:
    if source_image.mode in config["image"]["alpha_modes"]:
        alpha_image = source_image.convert(config["image"]["rgba_mode"])
        background = Image.new(
            config["image"]["rgba_mode"],
            source_image.size,
            tuple(config["image"]["alpha_background_rgba"]),
        )
        return Image.alpha_composite(background, alpha_image).convert(config["image"]["processing_mode"])
    return source_image.convert(config["image"]["processing_mode"])


def pixel_art_image(
    config: dict[str, Any],
    image: Image.Image,
    settings: PixelArtGenerateSettings,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    algorithm_config = algorithm_config_for_settings(config, settings)
    if algorithm_config["generator"] == config["algorithms"]["generators"]["logo_text"]:
        return logo_text_pixel_art_image(config, image, settings, algorithm_config)
    if algorithm_config["generator"] == config["algorithms"]["generators"]["side_mixed_plate_brick_pixel"]:
        return side_mixed_plate_brick_pixel_art_image(config, image, settings, algorithm_config)
    return photo_illustration_pixel_art_image(config, image, settings, algorithm_config)


def logo_text_pixel_art_image(
    config: dict[str, Any],
    image: Image.Image,
    settings: PixelArtGenerateSettings,
    algorithm_config: dict[str, Any],
) -> tuple[Image.Image, list[dict[str, Any]]]:
    palette = kmeans_mode_palette(config, list(image.getdata()), settings.colorCount)
    mapped_image = Image.new(
        config["image"]["processing_mode"],
        (settings.gridWidth, settings.gridHeight),
    )
    metadata = []
    for y in range(settings.gridHeight):
        for x in range(settings.gridWidth):
            block_pixels = list(image.crop(source_block_box(config, image.size, settings, x, y)).getdata())
            mapped_block_colors = [nearest_palette_color(config, pixel, palette) for pixel in block_pixels]
            source_color = most_common_color(mapped_block_colors)
            mapped_image.putpixel((x, y), source_color)
            metadata.append(static_cell_metadata(config, algorithm_config, source_color))
    return mapped_image, metadata


def photo_illustration_pixel_art_image(
    config: dict[str, Any],
    image: Image.Image,
    settings: PixelArtGenerateSettings,
    algorithm_config: dict[str, Any],
) -> tuple[Image.Image, list[dict[str, Any]]]:
    processed_image = preprocessed_image(config, image, settings)
    resized_image = processed_image.resize(
        (settings.gridWidth, settings.gridHeight),
        RESAMPLE_METHODS[algorithm_config["resample_method"]],
    )
    resized_pixels = list(resized_image.getdata())
    palette = kmeans_mode_palette(config, resized_pixels, settings.colorCount)
    mapped_image = Image.new(config["image"]["processing_mode"], resized_image.size)
    metadata = []
    for source_color in resized_pixels:
        mapped_color = nearest_palette_color(config, source_color, palette)
        mapped_image.putpixel(
            (
                len(metadata) % settings.gridWidth,
                len(metadata) // settings.gridWidth,
            ),
            mapped_color,
        )
        metadata.append(static_cell_metadata(config, algorithm_config, source_color))
    return mapped_image, metadata


def side_mixed_plate_brick_pixel_art_image(
    config: dict[str, Any],
    image: Image.Image,
    settings: PixelArtGenerateSettings,
    algorithm_config: dict[str, Any],
) -> tuple[Image.Image, list[dict[str, Any]]]:
    mapped_image, metadata = photo_illustration_pixel_art_image(
        config,
        image,
        settings,
        algorithm_config,
    )
    return mapped_image, side_mixed_cell_metadata(config, algorithm_config, mapped_image, metadata)


def side_mixed_cell_metadata(
    config: dict[str, Any],
    algorithm_config: dict[str, Any],
    mapped_image: Image.Image,
    metadata: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    side_layout = algorithm_config["side_layout"]
    colors = list(mapped_image.getdata())
    width, height = mapped_image.size
    mixed_metadata = [cell_metadata.copy() for cell_metadata in metadata]
    apply_side_horizontal_runs(config, side_layout, colors, width, height, mixed_metadata)
    apply_side_vertical_runs(config, side_layout, colors, width, height, mixed_metadata)
    return mixed_metadata


def apply_side_horizontal_runs(
    config: dict[str, Any],
    side_layout: dict[str, Any],
    colors: list[tuple[int, int, int]],
    width: int,
    height: int,
    metadata: list[dict[str, Any]],
) -> None:
    for y in range(height):
        x = config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]
        while x < width:
            run_length = same_color_run_length(
                config,
                colors,
                y * width + x,
                side_layout["horizontal_step"],
                width - x,
            )
            run_end = x + run_length
            run_width = (run_end - x) * side_layout["pixel_width_plates"]
            for run_x in range(x, run_end):
                metadata[y * width + run_x]["sidePixelWidthPlates"] = side_layout["pixel_width_plates"]
                metadata[y * width + run_x]["sidePixelHeightPlates"] = side_layout["pixel_height_plates"]
                metadata[y * width + run_x]["sidePartWidthPlates"] = run_width
            x = run_end


def apply_side_vertical_runs(
    config: dict[str, Any],
    side_layout: dict[str, Any],
    colors: list[tuple[int, int, int]],
    width: int,
    height: int,
    metadata: list[dict[str, Any]],
) -> None:
    for x in range(width):
        y = config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]
        while y < height:
            run_length = same_color_run_length(
                config,
                colors,
                y * width + x,
                side_layout["vertical_step"] * width,
                height - y,
            )
            run_end = y + run_length
            apply_side_vertical_run(config, side_layout, width, x, y, run_end, metadata)
            y = run_end


def apply_side_vertical_run(
    config: dict[str, Any],
    side_layout: dict[str, Any],
    width: int,
    x: int,
    run_start: int,
    run_end: int,
    metadata: list[dict[str, Any]],
) -> None:
    y = run_start
    while run_end - y >= side_layout["brick_height_plates"]:
        apply_side_vertical_part(
            side_layout,
            width,
            x,
            y,
            y + side_layout["brick_height_plates"],
            side_layout["brick_part_type"],
            side_layout["brick_height_plates"],
            metadata,
        )
        y += side_layout["brick_height_plates"]
    while y < run_end:
        apply_side_vertical_part(
            side_layout,
            width,
            x,
            y,
            y + config["quantization"]["minimum_dimension"],
            side_layout["plate_part_type"],
            side_layout["pixel_height_plates"],
            metadata,
        )
        y += config["quantization"]["minimum_dimension"]


def apply_side_vertical_part(
    side_layout: dict[str, Any],
    width: int,
    x: int,
    start_y: int,
    end_y: int,
    part_type: str,
    part_height_plates: int,
    metadata: list[dict[str, Any]],
) -> None:
    for y in range(start_y, end_y):
        cell_metadata = metadata[y * width + x]
        cell_metadata["sidePartType"] = part_type
        cell_metadata["sidePartHeightPlates"] = part_height_plates
        if end_y - start_y == side_layout["pixel_height_plates"]:
            cell_metadata["sidePartRole"] = side_layout["single_role"]
        elif y == start_y:
            cell_metadata["sidePartRole"] = side_layout["start_role"]
        else:
            cell_metadata["sidePartRole"] = side_layout["continue_role"]


def same_color_run_length(
    config: dict[str, Any],
    colors: list[tuple[int, int, int]],
    start_index: int,
    step: int,
    maximum_steps: int,
) -> int:
    run_length = config["quantization"]["minimum_dimension"]
    while (
        run_length < maximum_steps
        and colors[start_index + run_length * step] == colors[start_index]
    ):
        run_length += config["quantization"]["minimum_dimension"]
    return run_length


def preprocessed_image(
    config: dict[str, Any],
    image: Image.Image,
    settings: PixelArtGenerateSettings,
) -> Image.Image:
    result = ImageEnhance.Brightness(image).enhance(settings.preprocessing.brightness)
    result = ImageEnhance.Contrast(result).enhance(settings.preprocessing.contrast)
    result = ImageEnhance.Color(result).enhance(settings.preprocessing.saturation)
    result = ImageEnhance.Sharpness(result).enhance(settings.preprocessing.sharpness)
    if settings.preprocessing.localContrast > config["preprocessing"]["localContrast"]["minimum"]:
        result = local_contrast_image(config, result, settings.preprocessing.localContrast)
    return result


def local_contrast_image(config: dict[str, Any], image: Image.Image, amount: float) -> Image.Image:
    channels = image.convert(config["image"]["ycbcr_mode"]).split()
    enhanced_luminance = ImageOps.equalize(channels[config["image"]["luminance_channel_index"]])
    blended_luminance = Image.blend(
        channels[config["image"]["luminance_channel_index"]],
        enhanced_luminance,
        amount / config["preprocessing"]["local_contrast_blend_scale"],
    )
    return Image.merge(
        config["image"]["ycbcr_mode"],
        (
            blended_luminance,
            channels[config["image"]["blue_difference_channel_index"]],
            channels[config["image"]["red_difference_channel_index"]],
        ),
    ).convert(config["image"]["processing_mode"])


def kmeans_mode_palette(
    config: dict[str, Any],
    pixels: list[tuple[int, int, int]],
    color_count: int,
) -> list[tuple[int, int, int]]:
    sampled_pixels = sampled_kmeans_pixels(config, pixels)
    sampled_counts = Counter(sampled_pixels)
    source_counts = Counter(pixels)
    cluster_count = min(color_count, len(sampled_counts))
    centers = initial_kmeans_centers(config, sampled_counts, cluster_count)
    for _ in range(config["kmeans"]["maximum_iterations"]):
        clusters = weighted_clusters(config, sampled_counts, centers)
        next_centers = next_kmeans_centers(config, clusters, centers)
        if centers_converged(config, centers, next_centers):
            centers = next_centers
            break
        centers = next_centers
    return cluster_mode_palette(config, source_counts, centers)


def sampled_kmeans_pixels(
    config: dict[str, Any],
    pixels: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    maximum_sample_pixels = config["kmeans"]["maximum_sample_pixels"]
    if len(pixels) <= maximum_sample_pixels:
        return pixels
    step = (len(pixels) + maximum_sample_pixels - config["quantization"]["minimum_dimension"]) // maximum_sample_pixels
    return pixels[::step]


def initial_kmeans_centers(
    config: dict[str, Any],
    color_counts: Counter[tuple[int, int, int]],
    cluster_count: int,
) -> list[tuple[float, float, float]]:
    first_color = color_counts.most_common(config["quantization"]["minimum_dimension"])[
        config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]
    ][config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]]
    centers = [float_color(first_color)]
    while len(centers) < cluster_count:
        next_color = max(
            color_counts,
            key=lambda color: color_counts[color] * nearest_center_distance(config, color, centers),
        )
        centers.append(float_color(next_color))
    return centers


def weighted_clusters(
    config: dict[str, Any],
    color_counts: Counter[tuple[int, int, int]],
    centers: list[tuple[float, float, float]],
) -> list[list[tuple[tuple[int, int, int], int]]]:
    clusters: list[list[tuple[tuple[int, int, int], int]]] = []
    for _ in centers:
        clusters.append([])
    for color, count in color_counts.items():
        cluster_index = nearest_center_index(config, color, centers)
        clusters[cluster_index].append((color, count))
    return clusters


def next_kmeans_centers(
    config: dict[str, Any],
    clusters: list[list[tuple[tuple[int, int, int], int]]],
    centers: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    next_centers = []
    for index, cluster in enumerate(clusters):
        if not cluster:
            next_centers.append(centers[index])
            continue
        red_total = green_total = blue_total = weight_total = config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]
        for (red, green, blue), count in cluster:
            red_total += red * count
            green_total += green * count
            blue_total += blue * count
            weight_total += count
        next_centers.append(
            (
                red_total / weight_total,
                green_total / weight_total,
                blue_total / weight_total,
            )
        )
    return next_centers


def centers_converged(
    config: dict[str, Any],
    centers: list[tuple[float, float, float]],
    next_centers: list[tuple[float, float, float]],
) -> bool:
    movement = sum(
        sqrt(
            (red - next_red) ** config["quantization"]["color_distance_power"]
            + (green - next_green) ** config["quantization"]["color_distance_power"]
            + (blue - next_blue) ** config["quantization"]["color_distance_power"]
        )
        for (red, green, blue), (next_red, next_green, next_blue) in zip(centers, next_centers)
    )
    return movement <= config["kmeans"]["convergence_distance"]


def cluster_mode_palette(
    config: dict[str, Any],
    color_counts: Counter[tuple[int, int, int]],
    centers: list[tuple[float, float, float]],
) -> list[tuple[int, int, int]]:
    cluster_counters: list[Counter[tuple[int, int, int]]] = []
    for _ in centers:
        cluster_counters.append(Counter())
    for color, count in color_counts.items():
        cluster_counters[nearest_center_index(config, color, centers)][color] += count
    palette = []
    for cluster_counter in cluster_counters:
        if not cluster_counter:
            continue
        color = cluster_counter.most_common(config["quantization"]["minimum_dimension"])[
            config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]
        ][config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]]
        if color not in palette:
            palette.append(color)
    return palette


def nearest_palette_color(
    config: dict[str, Any],
    color: tuple[int, int, int],
    palette: list[tuple[int, int, int]],
) -> tuple[int, int, int]:
    return min(palette, key=lambda palette_color: color_distance(config, color, palette_color))


def nearest_center_index(
    config: dict[str, Any],
    color: tuple[int, int, int],
    centers: list[tuple[float, float, float]],
) -> int:
    distances = [color_distance(config, color, center) for center in centers]
    return distances.index(min(distances))


def nearest_center_distance(
    config: dict[str, Any],
    color: tuple[int, int, int],
    centers: list[tuple[float, float, float]],
) -> float:
    return min(color_distance(config, color, center) for center in centers)


def float_color(color: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = color
    return float(red), float(green), float(blue)


def most_common_color(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return Counter(colors).most_common(1)[0][0]


def static_cell_metadata(
    config: dict[str, Any],
    algorithm_config: dict[str, Any],
    source_color: tuple[int, int, int],
) -> dict[str, Any]:
    return {
        "sourceColor": hex_color(config, source_color),
        "featureScore": rounded_score(config, algorithm_config["feature_score"]),
        "edgeStrength": rounded_score(config, algorithm_config["edge_strength"]),
        "localContrast": rounded_score(config, algorithm_config["local_contrast"]),
    }


def source_block_box(
    config: dict[str, Any],
    image_size: tuple[int, int],
    settings: PixelArtGenerateSettings,
    x: int,
    y: int,
) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    minimum_dimension = config["quantization"]["minimum_dimension"]
    left = x * image_width // settings.gridWidth
    upper = y * image_height // settings.gridHeight
    right = (x + minimum_dimension) * image_width // settings.gridWidth
    lower = (y + minimum_dimension) * image_height // settings.gridHeight
    if right <= left:
        right = left + minimum_dimension
    if lower <= upper:
        lower = upper + minimum_dimension
    return (
        left,
        upper,
        min(right, image_width),
        min(lower, image_height),
    )


def color_distance(
    config: dict[str, Any],
    left_color: tuple[float, float, float] | tuple[int, int, int],
    right_color: tuple[float, float, float] | tuple[int, int, int],
) -> float:
    distance_total = config["quantization"]["minimum_dimension"] - config["quantization"]["minimum_dimension"]
    channel_count = len(left_color)
    for left_channel, right_channel in zip(left_color, right_color):
        distance_total += (left_channel - right_channel) ** config["quantization"]["color_distance_power"]
    return sqrt(distance_total / channel_count) / config["quantization"]["maximum_channel_value"]


def rounded_score(config: dict[str, Any], value: float) -> float:
    return round(value, config["quantization"]["feature_score_precision"])


def pixel_cells(
    config: dict[str, Any],
    image: Image.Image,
    cell_metadata: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    width, height = image.size
    colors = list(image.getdata())
    color_indexes = {color: index for index, color in enumerate(dict.fromkeys(colors))}
    cells = []
    for y in range(height):
        for x in range(width):
            cell_index = y * width + x
            red, green, blue = colors[cell_index]
            quantized_color = config["quantization"]["hex_color_format"].format(red, green, blue)
            cell = {
                "x": x,
                "y": y,
                "colorIndex": color_indexes[(red, green, blue)],
                "rgb": quantized_color,
                "quantizedColor": quantized_color,
                "modified": False,
                "locked": False,
            }
            cell.update(cell_metadata[cell_index])
            cells.append(cell)
    return cells


def palette_summary(pixels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(pixel["rgb"] for pixel in pixels)
    palette = []
    for index, rgb in enumerate(counts.keys()):
        palette.append({"colorIndex": index, "rgb": rgb, "count": counts[rgb]})
    return palette


def preview_image_bytes(config: dict[str, Any], image: Image.Image) -> bytes:
    preview_buffer = BytesIO()
    image.save(preview_buffer, format=config["image"]["preview_format"])
    return preview_buffer.getvalue()


def hex_color(config: dict[str, Any], color: tuple[int, int, int]) -> str:
    red, green, blue = color
    return config["quantization"]["hex_color_format"].format(red, green, blue)
