"""Persistent model fitting jobs and editable solution shells."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import selectinload, sessionmaker

from src.api.schemas.fitting_candidate_recall import (
    FittingCandidateRecallBBoxRequest,
    FittingCandidateRecallRequest,
)
from src.mesh.glb_geometry import analyze_glb_geometry
from src.model.models import (
    ModelAsset,
    ModelFittingJob,
    ModelFittingSolution,
    ModelFittingSolutionEdit,
    ModelFittingSolutionPlacement,
    ModelFittingTargetBlock,
)
from src.services.fitting_candidate_recall_service import recall_fitting_candidates


def ensure_model_fitting_tables(engine: Engine) -> None:
    ModelFittingJob.__table__.create(bind=engine, checkfirst=True)
    ModelFittingTargetBlock.__table__.create(bind=engine, checkfirst=True)
    ModelFittingSolution.__table__.create(bind=engine, checkfirst=True)
    ModelFittingSolutionPlacement.__table__.create(bind=engine, checkfirst=True)
    ModelFittingSolutionEdit.__table__.create(bind=engine, checkfirst=True)


def create_model_fitting_job(
    engine: Engine,
    config: dict[str, Any],
    recall_config: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        model_asset = session.get(ModelAsset, payload["modelId"])
        if model_asset is None:
            raise ValueError(
                config["errors"]["model_not_found"].format(
                    model_id=payload["modelId"],
                )
            )
        validate_model_asset(config, model_asset)
        asset_path = Path(model_asset.asset_path)
        if not asset_path.exists():
            raise ValueError(
                config["errors"]["model_file_not_found"].format(
                    model_id=model_asset.id,
                )
            )
        file_bytes = asset_path.read_bytes()
        settings = job_settings(config, payload)
        target_analysis = model_target_analysis(
            config,
            model_asset,
            file_bytes,
            settings,
        )
        created_at = datetime.now(timezone.utc)
        job = ModelFittingJob(
            id=new_id(config),
            source_model_id=model_asset.id,
            name=payload["name"] or model_asset.name,
            schema=config["schema"]["job"],
            status=config["job_status"]["complete"],
            settings_json=settings,
            target_analysis_json=target_analysis,
            created_at=created_at,
            error_message=None,
        )
        blocks = target_blocks_for_job(
            config,
            recall_config,
            engine,
            job,
            target_analysis,
            created_at,
        )
        solution = draft_solution(config, job, created_at)
        session.add(job)
        for block in blocks:
            session.add(block)
        session.add(solution)
        session.commit()
        return model_fitting_job_response(load_job_row(session, job.id))


def get_model_fitting_job(
    engine: Engine,
    config: dict[str, Any],
    job_id: str,
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        job = load_job_row(session, job_id)
        if job is None:
            return None
        return model_fitting_job_response(job)


def get_model_fitting_blocks(
    engine: Engine,
    config: dict[str, Any],
    job_id: str,
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        job = session.scalar(
            select(ModelFittingJob)
            .options(selectinload(ModelFittingJob.target_blocks))
            .where(ModelFittingJob.id == job_id)
        )
        if job is None:
            return None
        return {
            "jobId": job.id,
            "blocks": [
                target_block_response(block)
                for block in sorted(job.target_blocks, key=lambda item: item.created_at)
            ],
        }


def get_model_fitting_solution(
    engine: Engine,
    solution_id: str,
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        solution = session.scalar(
            select(ModelFittingSolution)
            .options(selectinload(ModelFittingSolution.placements))
            .where(ModelFittingSolution.id == solution_id)
        )
        if solution is None:
            return None
        return solution_response(solution)


def validate_model_asset(config: dict[str, Any], model_asset: ModelAsset) -> None:
    if model_asset.model_type != config["model_asset"]["required_model_type"]:
        raise ValueError(
            config["errors"]["unsupported_model_type"].format(
                model_id=model_asset.id,
            )
        )


def job_settings(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    model_type_hint = payload["modelTypeHint"]
    if model_type_hint is None:
        model_type_hint = config["semantic"]["default_model_type_hint"]
    semantic_preset = payload["semanticPreset"]
    if semantic_preset is None:
        semantic_preset = default_semantic_preset(config, model_type_hint)
    target_width_stud = payload["targetWidthStud"]
    if target_width_stud is None and semantic_preset == config["semantic"]["vehicle_8_wide_preset"]:
        target_width_stud = config["semantic"]["default_target_width_stud"]
    return {
        config["json_keys"]["scale_to_ldu"]: payload["scaleToLdu"],
        config["json_keys"]["up_axis"]: config["normalization"]["up_axis"],
        config["json_keys"]["model_type_hint"]: model_type_hint,
        config["json_keys"]["semantic_preset"]: semantic_preset,
        config["json_keys"]["target_width_stud"]: target_width_stud,
    }


def default_semantic_preset(config: dict[str, Any], model_type_hint: str) -> str:
    if model_type_hint == config["semantic"]["vehicle_model_type"]:
        return config["semantic"]["vehicle_8_wide_preset"]
    return config["semantic"]["default_semantic_preset"]


def model_target_analysis(
    config: dict[str, Any],
    model_asset: ModelAsset,
    file_bytes: bytes,
    settings: dict[str, Any],
) -> dict[str, Any]:
    geometry_analysis = analyze_glb_geometry(config, file_bytes)
    target_bbox = geometry_analysis[config["json_keys"]["target_bbox"]]
    scale_to_ldu = normalized_scale_to_ldu(config, target_bbox, settings)
    settings[config["json_keys"]["scale_to_ldu"]] = scale_to_ldu
    return {
        config["json_keys"]["target_bbox"]: target_bbox,
        config["json_keys"]["normalized_bbox"]: normalized_bbox(
            config,
            target_bbox,
            scale_to_ldu,
        ),
        config["json_keys"]["mesh_stats"]: geometry_analysis[
            config["json_keys"]["mesh_stats"]
        ],
        config["json_keys"]["color_summary"]: (
            model_asset.metadata_json or {}
        ).get(config["json_keys"]["color_summary"]),
        config["json_keys"]["normalization"]: {
            config["json_keys"]["source_unit"]: config["normalization"]["source_unit"],
            config["json_keys"]["target_unit"]: config["normalization"]["unit"],
            config["json_keys"]["scale_to_ldu"]: scale_to_ldu,
            config["json_keys"]["up_axis"]: settings[config["json_keys"]["up_axis"]],
        },
    }


def normalized_scale_to_ldu(
    config: dict[str, Any],
    target_bbox: dict[str, Any],
    settings: dict[str, Any],
) -> float:
    scale_to_ldu = settings[config["json_keys"]["scale_to_ldu"]]
    if scale_to_ldu is not None:
        return scale_to_ldu
    target_width_stud = settings[config["json_keys"]["target_width_stud"]]
    if target_width_stud is None:
        return config["normalization"]["default_scale_to_ldu"]
    if target_width_stud <= 0:
        raise ValueError(config["errors"]["invalid_target_width"])
    source_width = target_bbox[config["json_keys"]["width"]]
    if source_width <= 0:
        raise ValueError(config["errors"]["invalid_source_width"])
    return (
        target_width_stud
        * config["semantic"]["ldu_per_stud"]
        / source_width
    )


def normalized_bbox(
    config: dict[str, Any],
    target_bbox: dict[str, Any],
    scale_to_ldu: float,
) -> dict[str, Any]:
    keys = config["json_keys"]
    return {
        key: target_bbox[key] * scale_to_ldu
        for key in (
            keys["min_x"],
            keys["min_y"],
            keys["min_z"],
            keys["max_x"],
            keys["max_y"],
            keys["max_z"],
            keys["width"],
            keys["height"],
            keys["depth"],
        )
    }


def target_blocks_for_job(
    config: dict[str, Any],
    recall_config: dict[str, Any],
    engine: Engine,
    job: ModelFittingJob,
    target_analysis: dict[str, Any],
    created_at: datetime,
) -> list[ModelFittingTargetBlock]:
    if job.settings_json[config["json_keys"]["semantic_preset"]] == config["semantic"]["vehicle_8_wide_preset"]:
        return vehicle_target_blocks(
            config,
            recall_config,
            engine,
            job,
            target_analysis,
            created_at,
        )
    return [
        whole_model_target_block(
            config,
            recall_config,
            engine,
            job,
            target_analysis,
            created_at,
        )
    ]


def whole_model_target_block(
    config: dict[str, Any],
    recall_config: dict[str, Any],
    engine: Engine,
    job: ModelFittingJob,
    target_analysis: dict[str, Any],
    created_at: datetime,
) -> ModelFittingTargetBlock:
    normalized = target_analysis[config["json_keys"]["normalized_bbox"]]
    recall_query = whole_model_recall_query(config, normalized)
    recall_result = recall_fitting_candidates(engine, recall_config, recall_query)
    return ModelFittingTargetBlock(
        id=new_id(config),
        job_id=job.id,
        schema=config["schema"]["target_block"],
        block_type=config["target_block"]["whole_model_type"],
        name=config["target_block"]["whole_model_name"],
        bbox_json=normalized,
        profile_json=target_analysis,
        recall_query_json=recall_query.model_dump(),
        candidate_summary_json=recall_result.model_dump(),
        created_at=created_at,
    )


def vehicle_target_blocks(
    config: dict[str, Any],
    recall_config: dict[str, Any],
    engine: Engine,
    job: ModelFittingJob,
    target_analysis: dict[str, Any],
    created_at: datetime,
) -> list[ModelFittingTargetBlock]:
    normalized = target_analysis[config["json_keys"]["normalized_bbox"]]
    return [
        vehicle_target_block(
            config,
            recall_config,
            engine,
            job,
            target_analysis,
            normalized,
            block_template,
            created_at,
        )
        for block_template in config["semantic"]["block_templates"]
    ]


def vehicle_target_block(
    config: dict[str, Any],
    recall_config: dict[str, Any],
    engine: Engine,
    job: ModelFittingJob,
    target_analysis: dict[str, Any],
    normalized_bbox_payload: dict[str, Any],
    block_template: dict[str, Any],
    created_at: datetime,
) -> ModelFittingTargetBlock:
    block_bbox = block_bbox_from_fraction(
        config,
        normalized_bbox_payload,
        block_template["bbox_fraction"],
    )
    recall_query = vehicle_block_recall_query(config, block_bbox, block_template)
    recall_result = recall_fitting_candidates(engine, recall_config, recall_query)
    return ModelFittingTargetBlock(
        id=new_id(config),
        job_id=job.id,
        schema=config["schema"]["target_block"],
        block_type=config["target_block"]["vehicle_region_type"],
        name=block_template["name"],
        bbox_json=block_bbox,
        profile_json=vehicle_block_profile(
            config,
            job,
            target_analysis,
            block_template,
        ),
        recall_query_json=recall_query.model_dump(),
        candidate_summary_json=recall_result.model_dump(),
        created_at=created_at,
    )


def block_bbox_from_fraction(
    config: dict[str, Any],
    bbox: dict[str, Any],
    bbox_fraction: dict[str, float],
) -> dict[str, Any]:
    keys = config["json_keys"]
    min_x = fraction_value(keys, bbox, bbox_fraction, keys["min_x"], keys["width"])
    max_x = fraction_value(keys, bbox, bbox_fraction, keys["max_x"], keys["width"])
    min_y = fraction_value(keys, bbox, bbox_fraction, keys["min_y"], keys["height"])
    max_y = fraction_value(keys, bbox, bbox_fraction, keys["max_y"], keys["height"])
    min_z = fraction_value(keys, bbox, bbox_fraction, keys["min_z"], keys["depth"])
    max_z = fraction_value(keys, bbox, bbox_fraction, keys["max_z"], keys["depth"])
    return {
        keys["min_x"]: min_x,
        keys["min_y"]: min_y,
        keys["min_z"]: min_z,
        keys["max_x"]: max_x,
        keys["max_y"]: max_y,
        keys["max_z"]: max_z,
        keys["width"]: max_x - min_x,
        keys["height"]: max_y - min_y,
        keys["depth"]: max_z - min_z,
    }


def fraction_value(
    keys: dict[str, str],
    bbox: dict[str, Any],
    bbox_fraction: dict[str, float],
    min_or_max_key: str,
    dimension_key: str,
) -> float:
    axis_min_key = axis_min_key_for_dimension(keys, dimension_key)
    return bbox[axis_min_key] + bbox[dimension_key] * bbox_fraction[min_or_max_key]


def axis_min_key_for_dimension(keys: dict[str, str], dimension_key: str) -> str:
    if dimension_key == keys["width"]:
        return keys["min_x"]
    if dimension_key == keys["height"]:
        return keys["min_y"]
    return keys["min_z"]


def vehicle_block_profile(
    config: dict[str, Any],
    job: ModelFittingJob,
    target_analysis: dict[str, Any],
    block_template: dict[str, Any],
) -> dict[str, Any]:
    return {
        "semanticType": block_template["semantic_type"],
        "semanticSource": config["semantic"]["source_vehicle_preset"],
        "semanticConfidence": config["semantic"]["confidence_vehicle_preset"],
        "semanticPreset": job.settings_json[config["json_keys"]["semantic_preset"]],
        "targetRole": block_template["target_role"],
        "shapeHints": block_template["shape_hints"],
        "reuseGroup": block_template["reuse_group"],
        "symmetryGroup": block_template["symmetry_group"],
        "colorSummary": target_analysis.get(config["json_keys"]["color_summary"]),
    }


def vehicle_block_recall_query(
    config: dict[str, Any],
    block_bbox: dict[str, Any],
    block_template: dict[str, Any],
) -> FittingCandidateRecallRequest:
    keys = config["json_keys"]
    return FittingCandidateRecallRequest(
        bbox=FittingCandidateRecallBBoxRequest(
            widthLdu=block_bbox[keys["width"]],
            heightLdu=block_bbox[keys["height"]],
            depthLdu=block_bbox[keys["depth"]],
            toleranceLdu=config["recall"]["bbox_tolerance_ldu"],
        ),
        categories=block_template["categories"],
        includeIrregular=block_template["include_irregular"],
        limit=config["recall"]["default_limit"],
    )


def whole_model_recall_query(
    config: dict[str, Any],
    normalized_bbox_payload: dict[str, Any],
) -> FittingCandidateRecallRequest:
    keys = config["json_keys"]
    return FittingCandidateRecallRequest(
        bbox=FittingCandidateRecallBBoxRequest(
            widthLdu=normalized_bbox_payload[keys["width"]],
            heightLdu=normalized_bbox_payload[keys["height"]],
            depthLdu=normalized_bbox_payload[keys["depth"]],
            toleranceLdu=config["recall"]["bbox_tolerance_ldu"],
        ),
        includeIrregular=config["recall"]["include_irregular"],
        limit=config["recall"]["default_limit"],
    )


def draft_solution(
    config: dict[str, Any],
    job: ModelFittingJob,
    created_at: datetime,
) -> ModelFittingSolution:
    return ModelFittingSolution(
        id=new_id(config),
        job_id=job.id,
        schema=config["schema"]["solution"],
        status=config["solution_status"]["draft"],
        version=1,
        metrics_json={},
        bom_json=[],
        ldraw_content="",
        created_at=created_at,
    )


def load_job_row(session: object, job_id: str) -> ModelFittingJob | None:
    return session.scalar(
        select(ModelFittingJob)
        .options(
            selectinload(ModelFittingJob.target_blocks),
            selectinload(ModelFittingJob.solutions).selectinload(
                ModelFittingSolution.placements
            ),
        )
        .where(ModelFittingJob.id == job_id)
    )


def model_fitting_job_response(job: ModelFittingJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "sourceModelId": job.source_model_id,
        "name": job.name,
        "schema": job.schema,
        "status": job.status,
        "settings": job.settings_json,
        "targetAnalysis": job.target_analysis_json,
        "errorMessage": job.error_message,
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
        "blocks": [
            target_block_response(block)
            for block in sorted(job.target_blocks, key=lambda item: item.created_at)
        ],
        "solutions": [
            solution_response(solution)
            for solution in sorted(job.solutions, key=lambda item: item.created_at)
        ],
    }


def target_block_response(block: ModelFittingTargetBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "jobId": block.job_id,
        "schema": block.schema,
        "blockType": block.block_type,
        "name": block.name,
        "bbox": block.bbox_json,
        "profile": block.profile_json,
        "recallQuery": block.recall_query_json,
        "candidateSummary": block.candidate_summary_json,
        "createdAt": block.created_at.isoformat(),
        "updatedAt": block.updated_at.isoformat() if block.updated_at else None,
    }


def solution_response(solution: ModelFittingSolution) -> dict[str, Any]:
    return {
        "id": solution.id,
        "jobId": solution.job_id,
        "schema": solution.schema,
        "status": solution.status,
        "version": solution.version,
        "metrics": solution.metrics_json,
        "bom": solution.bom_json,
        "ldrawContent": solution.ldraw_content,
        "placements": [
            placement_response(placement)
            for placement in sorted(solution.placements, key=lambda item: item.created_at)
        ],
        "createdAt": solution.created_at.isoformat(),
        "updatedAt": solution.updated_at.isoformat() if solution.updated_at else None,
    }


def placement_response(placement: ModelFittingSolutionPlacement) -> dict[str, Any]:
    return {
        "id": placement.id,
        "targetBlockId": placement.target_block_id,
        "candidateType": placement.candidate_type,
        "candidateId": placement.candidate_id,
        "colorCode": placement.color_code,
        "position": placement.position_json,
        "orientation": placement.orientation_json,
        "bbox": placement.bbox_json,
        "score": placement.score,
        "scoreReasons": placement.score_reasons_json,
        "locked": placement.locked,
        "source": placement.source,
        "createdAt": placement.created_at.isoformat(),
        "updatedAt": placement.updated_at.isoformat() if placement.updated_at else None,
    }


def new_id(config: dict[str, Any]) -> str:
    return uuid4().hex[: int(config["storage"]["id_hex_length"])]
