"""Independent DEM LEGO design API routes."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import Response

from src.api.errors import domain_error_from_exception
from src.api.schemas.dem_lego_design import (
    DemBaseHStructureRequest,
    DemBaseHStructureResponse,
    DemPartSurfaceProfileResponse,
    DemSurfacePatchCandidatesRequest,
    DemSurfacePatchCandidatesResponse,
    DemSurfacePlanRequest,
    DemSurfacePlanResponse,
    DemFinalDesignResponse,
    DemFinalDesignModelRequest,
)
from src.i18n.export_catalog import (
    content_disposition,
    create_export_context,
    dem_design_report,
    localized_filename,
    validate_export_context,
)
from src.services.dem_design_input_service import load_dem_design_targets
from src.services.dem_lego_design_service import (
    build_base_h_structure,
    load_dem_structure_parts,
    load_part_surface_profile,
)
from src.services.dem_surface_patch_service import load_surface_patch_candidates
from src.services.dem_surface_plan_service import load_surface_plan
from src.services.dem_final_design_service import (
    export_dem_final_design_ldraw,
    load_colored_replacement_final_dem_design,
    load_final_dem_design,
)
from src.services.lego_heightmap_generation_service import create_colored_heightmap_asset
from src.terrain.dem_asset_helper import load_model_asset


def create_dem_lego_design_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(
        config["routes"]["base_h_structure"],
        response_model=DemBaseHStructureResponse,
    )
    def create_base_h_structure(
        request_body: DemBaseHStructureRequest,
        request: Request,
    ) -> dict:
        try:
            parts = load_dem_structure_parts(request.app.state.db_engine, config)
            return build_base_h_structure(request_body.baseH, parts, config)
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "dem_lego_design.base_h_failed",
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.get(
        config["routes"]["part_surface_profile"],
        response_model=DemPartSurfaceProfileResponse,
    )
    def get_part_surface_profile(part_id: str, request: Request) -> dict:
        try:
            return load_part_surface_profile(
                part_id,
                request.app.state.db_engine,
                config,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "dem_lego_design.surface_profile_failed",
                params={"partId": part_id},
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.post(
        config["routes"]["surface_patch_candidates"],
        response_model=DemSurfacePatchCandidatesResponse,
    )
    def create_surface_patch_candidates(
        request_body: DemSurfacePatchCandidatesRequest,
        request: Request,
    ) -> dict:
        try:
            return load_surface_patch_candidates(
                request_body.targetSurfacePlate,
                request_body.targetColorId,
                request_body.partIds,
                request.app.state.db_engine,
                config,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "dem_lego_design.surface_patch_failed",
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.post(
        config["routes"]["surface_plan"],
        response_model=DemSurfacePlanResponse,
    )
    def create_surface_plan(
        request_body: DemSurfacePlanRequest,
        request: Request,
    ) -> dict:
        try:
            return load_surface_plan(
                request_body.targetSurfacePlate,
                request_body.targetHeightPlate,
                request_body.targetColorId,
                request_body.partIds,
                request.app.state.db_engine,
                config,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "dem_lego_design.surface_plan_failed",
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.post(
        config["routes"]["final_design"],
        response_model=DemFinalDesignResponse,
    )
    def create_final_design(
        request_body: DemFinalDesignModelRequest,
        request: Request,
    ) -> dict:
        try:
            final_config = config["final_design"]
            strategies = final_config["strategies"]
            if request_body.strategy not in strategies.values():
                raise ValueError(final_config["errors"]["strategy_invalid"])
            scale = {
                "horizontal_km_per_stud": request_body.horizontalKmPerStud,
                "vertical_meters_per_plate": request_body.verticalMetersPerPlate,
                "aggregation": request_body.aggregation,
                "minimum_coverage_ratio": request_body.minCoverageRatio,
            }
            heightmap_scale = {
                "horizontalKmPerStud": request_body.horizontalKmPerStud,
                "verticalMetersPerPlate": request_body.verticalMetersPerPlate,
                "aggregation": request_body.aggregation,
                "minCoverageRatio": request_body.minCoverageRatio,
            }
            dem_asset = load_model_asset(
                request.app.state.terrain_config,
                request_body.modelId,
            )
            targets = load_dem_design_targets(
                dem_asset,
                scale,
                request.app.state.db_engine,
                config["design_input"],
            )
            if request_body.strategy == strategies["colored_replacement"]:
                heightmap = create_colored_heightmap_asset(
                    dem_asset,
                    request_body.modelId,
                    heightmap_scale,
                    request.app.state.terrain_config,
                )
                design = load_colored_replacement_final_dem_design(
                    heightmap,
                    targets["targetSurfacePlate"],
                    targets["targetHeightPlate"],
                    targets["targetColorId"],
                    targets["partIds"],
                    request.app.state.db_engine,
                    config,
                )
            else:
                design = load_final_dem_design(
                    targets["targetSurfacePlate"],
                    targets["targetHeightPlate"],
                    targets["targetColorId"],
                    targets["partIds"],
                    request.app.state.db_engine,
                    config,
                )
            export_context = create_export_context(request_body.locale, request_body.timezone)
            return {
                "modelId": request_body.modelId,
                "exportContext": export_context,
                **design,
            }
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "dem_lego_design.final_design_failed",
                params={"modelId": request_body.modelId},
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.post(
        config["routes"]["final_design_ldraw"],
    )
    def export_final_design_ldraw(
        request_body: DemFinalDesignResponse,
    ) -> Response:
        try:
            content = export_dem_final_design_ldraw(
                request_body.model_dump(),
                config,
                request_body.exportContext.model_dump(),
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "dem_lego_design.export_failed",
                http_status=config["http_status"]["bad_request"],
            ) from error
        ldraw_config = config["dem_ldraw"]
        export_context = validate_export_context(request_body.exportContext.model_dump())
        filename = localized_filename(
            export_context, "demLdraw", modelId=request_body.modelId,
        )
        return Response(
            content=content,
            media_type=ldraw_config["content_type"],
            headers={
                ldraw_config["content_disposition_header"]: content_disposition(filename),
            },
        )

    @router.post(config["routes"]["final_design_report"])
    def export_final_design_report(
        request_body: DemFinalDesignResponse,
    ) -> Response:
        export_context = validate_export_context(request_body.exportContext.model_dump())
        report = dem_design_report(request_body.model_dump(), export_context)
        filename = localized_filename(
            export_context, "demReport", modelId=request_body.modelId,
        )
        return Response(
            content=json.dumps(report, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": content_disposition(filename)},
        )

    return router
