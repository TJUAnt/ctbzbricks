"""Calculate and persist normalized Heightmap patterns for DEM slope candidates."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from src.config.app_settings import load_json_config
from src.i18n.messages import message
from src.config.db_config import get_db_url
from src.model.models import (
    DemSlopeCandidate,
    DemSlopeCandidatePattern,
    LDrawPart,
)
from src.services.dem_lego_design_service import load_part_surface_profile_models
from src.services.dem_slope_catalog_service import profile_capability
from src.services.dem_slope_pattern_service import (
    build_candidate_heightmap_patterns,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser.parse_args()
def synchronize_patterns(
    session: Session,
    patterns_by_candidate: dict[int, tuple[dict[str, Any], ...]],
) -> int:
    session.execute(delete(DemSlopeCandidatePattern))
    inserted_count = 0
    for candidate_id, patterns in patterns_by_candidate.items():
        for pattern_rank, pattern in enumerate(patterns, start=1):
            session.add(
                DemSlopeCandidatePattern(
                    candidate_id=candidate_id,
                    pattern_rank=pattern_rank,
                    pattern_key=pattern["patternKey"],
                    heightmap_pattern_json=pattern["heightmapPattern"],
                    match_metrics_json=pattern["matchMetrics"],
                )
            )
            inserted_count += 1
    session.commit()
    return inserted_count


def calculate_patterns(
    session: Session,
    slope_config: dict[str, Any],
    dem_config: dict[str, Any],
) -> tuple[dict[int, tuple[dict[str, Any], ...]], list[dict[str, Any]]]:
    generation_config = slope_config["pattern_generation"]
    candidate_rows = session.execute(
        select(DemSlopeCandidate, LDrawPart)
        .join(LDrawPart, LDrawPart.id == DemSlopeCandidate.ldraw_part_id)
        .where(DemSlopeCandidate.candidate_enabled.is_(True))
        .where(DemSlopeCandidate.capability_eligible.is_(True))
        .order_by(LDrawPart.ldraw_part_num)
    ).all()
    maximum_patterns = int(slope_config["database"]["maximum_patterns_per_candidate"])
    rotations = tuple(int(rotation) for rotation in slope_config["classification"]["orientation_degrees"])
    patterns_by_candidate = {}
    failures = []
    progress_interval = int(generation_config["progress_interval"])
    for index, (candidate, part) in enumerate(candidate_rows, start=1):
        try:
            profile = load_part_surface_profile_models(
                (part.ldraw_part_num,),
                session.get_bind(),
                dem_config,
                dem_config["surface_profile"]["sampling"]["samples_per_stud_axis"],
            )[0]
            patterns = build_candidate_heightmap_patterns(
                profile_capability(profile, slope_config["classification"]),
                rotations,
                maximum_patterns,
                generation_config,
            )
        except ValueError:
            failures.append(
                {
                    "partId": part.ldraw_part_num,
                    "error": message(
                        "dem_slope_catalog.pattern_generation_failed",
                        {"partId": part.ldraw_part_num},
                    ),
                }
            )
        else:
            patterns_by_candidate[int(candidate.id)] = patterns
        if index % progress_interval == 0 or index == len(candidate_rows):
            print(
                json.dumps(
                    {
                        "processed": index,
                        "total": len(candidate_rows),
                        "patterns": sum(len(items) for items in patterns_by_candidate.values()),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    return patterns_by_candidate, failures


def main() -> None:
    arguments = parse_arguments()
    slope_config = load_json_config(
        arguments.config,
        ("source", "classification", "database", "pattern_generation", "output"),
    )
    dem_config = load_json_config(
        slope_config["source"]["dem_design_config_file"],
        ("surface_profile", "errors"),
    )
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        patterns_by_candidate, failures = calculate_patterns(
            session,
            slope_config,
            dem_config,
        )
        inserted_count = synchronize_patterns(session, patterns_by_candidate)
    print(
        json.dumps(
            {
                "candidateCount": len(patterns_by_candidate),
                "failureCount": len(failures),
                "failures": failures,
                "patternCount": inserted_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
