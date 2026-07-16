"""Step strategy for LEGO pixel-map design exports."""

from __future__ import annotations

from typing import Any


def create_lego_pixmap_steps(
    design: dict[str, Any],
    support: dict[str, list[dict[str, Any]]] | None,
    include_base: bool,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    steps = []
    if include_base and support is not None:
        steps.extend(
            create_lego_base_steps(
                design,
                support["whiteBase"],
                support["blackSupport"],
                config,
            )
        )
    steps.extend(create_top_design_steps(design, config, len(steps)))
    return steps


def create_lego_base_steps(
    design: dict[str, Any],
    white_placements: list[dict[str, Any]],
    black_placements: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    strategy_config = config["lego_pixmap_strategy"]
    ldraw_config = config["ldraw"]
    plan_config = config["plan_export"]
    algorithm_config = config["algorithm"]
    white_batches = placement_batches(
        sorted(white_placements, key=placement_sort_key),
        strategy_config["base_step_white_plate_limit"],
    )
    unassigned_black = sorted(black_placements, key=placement_sort_key)
    completed_white_keys = set()
    steps = []
    for batch in white_batches:
        batch_keys = placement_cell_keys(batch, algorithm_config)
        available_white_keys = completed_white_keys | batch_keys
        black_batch = []
        remaining_black = []
        for black_placement in unassigned_black:
            black_keys = placement_cell_keys([black_placement], algorithm_config)
            if black_keys & batch_keys and black_keys <= available_white_keys:
                black_batch.append(black_placement)
            else:
                remaining_black.append(black_placement)
        step_index = len(steps) + strategy_config["step_index_start"]
        steps.append(
            {
                "id": step_id(strategy_config["step_id_prefixes"]["base"], step_index, strategy_config),
                "name": strategy_config["step_names"]["base"].format(index=step_index),
                "order": step_index,
                "layer": strategy_config["layers"]["base"],
                "placements": (
                    step_placements(batch, plan_config["layer_ids"]["white_base"], ldraw_config["white_base_y_ldu"])
                    + step_placements(
                        black_batch,
                        plan_config["layer_ids"]["black_support"],
                        ldraw_config["black_support_y_ldu"],
                    )
                ),
            }
        )
        completed_white_keys = available_white_keys
        unassigned_black = remaining_black
    if unassigned_black and steps:
        steps[-1]["placements"].extend(
            step_placements(
                unassigned_black,
                plan_config["layer_ids"]["black_support"],
                ldraw_config["black_support_y_ldu"],
            )
        )
    return steps


def create_top_design_steps(
    design: dict[str, Any],
    config: dict[str, Any],
    existing_step_count: int,
) -> list[dict[str, Any]]:
    strategy_config = config["lego_pixmap_strategy"]
    ldraw_config = config["ldraw"]
    plan_config = config["plan_export"]
    row_count = strategy_config["top_design_step_row_count"]
    steps = []
    for start_y in range(0, design["height"], row_count):
        end_y = min(start_y + row_count, design["height"])
        placements = [
            placement for placement in design["placements"]
            if start_y <= placement["y"] < end_y
        ]
        if not placements:
            continue
        step_index = len(steps) + strategy_config["step_index_start"]
        steps.append(
            {
                "id": step_id(strategy_config["step_id_prefixes"]["top"], step_index, strategy_config),
                "name": strategy_config["step_names"]["top"].format(
                    start=start_y,
                    end=end_y - strategy_config["step_end_inclusive_offset"],
                ),
                "order": existing_step_count + step_index,
                "layer": strategy_config["layers"]["top"],
                "placements": step_placements(
                    sorted(placements, key=placement_sort_key),
                    plan_config["layer_ids"]["top_design"],
                    ldraw_config["top_design_y_ldu"],
                ),
            }
        )
    return steps


def placement_batches(
    placements: list[dict[str, Any]],
    batch_size: int,
) -> list[list[dict[str, Any]]]:
    return [
        placements[index:index + batch_size]
        for index in range(0, len(placements), batch_size)
    ]


def step_id(prefix: str, index: int, config: dict[str, Any]) -> str:
    return f"{prefix}{config['step_id_separator']}{index}"


def step_placements(
    placements: list[dict[str, Any]],
    layer_id: str,
    ldraw_y: int,
) -> list[dict[str, Any]]:
    return [
        {
            "layer": layer_id,
            "ldrawY": ldraw_y,
            "placement": placement,
        }
        for placement in placements
    ]


def placement_cell_keys(
    placements: list[dict[str, Any]],
    config: dict[str, Any],
) -> set[str]:
    keys = set()
    for placement in placements:
        for y in range(placement["y"], placement["y"] + placement["height"]):
            for x in range(placement["x"], placement["x"] + placement["width"]):
                keys.add(cell_key(x, y, config))
    return keys


def cell_key(x: int, y: int, config: dict[str, Any]) -> str:
    return f"{x}{config['cell_key_separator']}{y}"


def placement_sort_key(placement: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        placement["y"],
        placement["x"],
        -placement["area"] if "area" in placement else -(placement["width"] * placement["height"]),
        placement["partId"],
    )
