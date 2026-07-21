"""API tests for independent DEM BaseH structure generation."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.api.errors import DomainError

from src.api.routes.dem_lego_design import create_dem_lego_design_router
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
from tests.test_dem_lego_design_service import CONFIG, PARTS


API_CONFIG = {
    **CONFIG,
    "routes": {
        "base_h_structure": "/api/dem-lego-design/base-h/structure",
        "part_surface_profile": "/api/dem-lego-design/parts/{part_id}/surface-profile",
        "surface_patch_candidates": "/api/dem-lego-design/surface-patch/candidates",
        "surface_plan": "/api/dem-lego-design/surface-plan",
        "final_design": "/api/dem-lego-design/final-design",
        "final_design_ldraw": "/api/dem-lego-design/final-design/ldraw",
        "final_design_report": "/api/dem-lego-design/final-design/report",
    },
    "http_status": {"bad_request": 400},
    "design_input": {"part_ids": ["3024.dat"]},
    "colored_replacement": {"strategy": "colored-region-replacement"},
    "final_design": {
        "strategies": {
            "surface_plan": "surface-plan",
            "colored_replacement": "colored-replacement",
        },
        "errors": {"strategy_invalid": "invalid strategy"},
    },
}

SURFACE_PROFILE = {
    "partId": "3040b.dat",
    "ldrawOriginToBaseLdu": 24,
    "ldrawCenterXLdu": 0,
    "ldrawCenterZLdu": 0,
    "widthStud": 1,
    "depthStud": 2,
    "samplesPerStudAxis": 1,
    "surfaceHeightPlate": [[1.0], [3.0]],
    "collisionIntervalsPlate": [[[[0.0, 1.0]]], [[[0.0, 3.0]]]],
    "bottomContact": [[True], [True]],
    "topConnectMask": [[False], [True]],
}

SURFACE_PATCH_CANDIDATES = {
    "widthStud": 2,
    "depthStud": 1,
    "samplesPerStudAxis": 1,
    "candidates": [],
}

SURFACE_PLAN = {
    "strategy": "connected-first-slope-replacement",
    "widthStud": 1,
    "depthStud": 1,
    "samplesPerStudAxis": 1,
    "candidateCount": 1,
    "placements": [],
    "replacementPhases": [],
    "baseH": [[0]],
    "maximumAbsoluteErrorPlate": 0,
    "totalAbsoluteErrorPlate": 0,
    "seamErrorPlate": 0,
    "partCount": 0,
    "validation": {
        "targetSlopeEdgeCount": 0,
        "solvedSlopeEdgeCount": 0,
        "unresolvedSlopeEdgeCount": 0,
        "coveredCellCount": 0,
        "overlapCellCount": 0,
        "unsupportedPlacementCount": 0,
        "baseHCollisionSampleCount": 0,
        "topConnectedPlacementCount": 0,
        "topFinishedPlacementCount": 0,
    },
}

FINAL_DESIGN = {
    "strategy": "surface-structure-validated",
    "surfacePlan": SURFACE_PLAN,
    "baseStructure": {
        "strategy": "solid-bottom-up",
        "widthStud": 1,
        "depthStud": 1,
        "baseH": [[0]],
        "placements": [],
        "bom": [],
        "validation": {
            "targetVolumeStudPlate": 0,
            "placedVolumeStudPlate": 0,
            "unsupportedPlacementCount": 0,
        },
    },
    "surfacePlacements": [],
    "bom": [],
    "steps": [],
    "replacementDiagnostics": None,
    "validation": {
        "rejectedBaseHCount": 0,
        "inventoryColorMappingCount": 0,
        "approximateGeometryPlacementCount": 0,
        "excludedColorCandidateCount": 0,
        "totalPlacementCount": 0,
        "stepPlacementCount": 0,
        "surfaceCollisionSampleCount": 0,
        "surfaceUnsupportedPlacementCount": 0,
        "structureUnsupportedPlacementCount": 0,
        "targetVolumeStudPlate": 0,
        "placedVolumeStudPlate": 0,
        "verticalContinuity": [],
    },
}


class DemLegoDesignApiTest(unittest.TestCase):
    def setUp(self) -> None:
        router = create_dem_lego_design_router(API_CONFIG)
        routes = {route.path: route for route in router.routes}
        route = routes[API_CONFIG["routes"]["base_h_structure"]]
        self.endpoint = route.endpoint
        profile_route = routes[API_CONFIG["routes"]["part_surface_profile"]]
        self.profile_endpoint = profile_route.endpoint
        candidates_route = routes[API_CONFIG["routes"]["surface_patch_candidates"]]
        self.candidates_endpoint = candidates_route.endpoint
        plan_route = routes[API_CONFIG["routes"]["surface_plan"]]
        self.plan_endpoint = plan_route.endpoint
        final_route = routes[API_CONFIG["routes"]["final_design"]]
        self.final_endpoint = final_route.endpoint
        self.request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    db_engine=object(),
                    terrain_config={"store": "terrain"},
                    lego_heightmap_config={"store": "heightmap"},
                )
            )
        )
        self.assertIs(route.response_model, DemBaseHStructureResponse)
        self.assertIs(profile_route.response_model, DemPartSurfaceProfileResponse)
        self.assertIs(candidates_route.response_model, DemSurfacePatchCandidatesResponse)
        self.assertIs(plan_route.response_model, DemSurfacePlanResponse)
        self.assertIs(final_route.response_model, DemFinalDesignResponse)

    @patch("src.api.routes.dem_lego_design.load_dem_structure_parts", return_value=PARTS)
    def test_create_base_h_structure(self, _load_parts) -> None:
        body = self.endpoint(
            DemBaseHStructureRequest(baseH=[[4, 4], [4, 4]]),
            self.request,
        )

        self.assertEqual(body["strategy"], CONFIG["structure"]["strategy"])
        self.assertEqual(body["validation"]["unsupportedPlacementCount"], 0)
        self.assertEqual(len(body["placements"]), 2)

    @patch("src.api.routes.dem_lego_design.load_dem_structure_parts", return_value=PARTS)
    def test_create_base_h_structure_rejects_negative_height(self, _load_parts) -> None:
        with self.assertRaises(DomainError) as raised:
            self.endpoint(DemBaseHStructureRequest(baseH=[[1, -1]]), self.request)

        self.assertEqual(raised.exception.http_status, API_CONFIG["http_status"]["bad_request"])
        self.assertEqual(raised.exception.code, "dem_lego_design.base_h_failed")

    @patch(
        "src.api.routes.dem_lego_design.load_part_surface_profile",
        return_value=SURFACE_PROFILE,
    )
    def test_get_part_surface_profile(self, load_profile) -> None:
        result = self.profile_endpoint("3040b.dat", self.request)

        load_profile.assert_called_once_with(
            "3040b.dat",
            self.request.app.state.db_engine,
            API_CONFIG,
        )
        self.assertEqual(result, SURFACE_PROFILE)

    @patch(
        "src.api.routes.dem_lego_design.load_surface_patch_candidates",
        return_value=SURFACE_PATCH_CANDIDATES,
    )
    def test_create_surface_patch_candidates(self, load_candidates) -> None:
        body = DemSurfacePatchCandidatesRequest(
            targetSurfacePlate=[[1.0, 2.0]],
            targetColorId=[[4, 4]],
            partIds=["3040b.dat"],
        )

        result = self.candidates_endpoint(body, self.request)

        load_candidates.assert_called_once_with(
            body.targetSurfacePlate,
            body.targetColorId,
            body.partIds,
            self.request.app.state.db_engine,
            API_CONFIG,
        )
        self.assertEqual(result, SURFACE_PATCH_CANDIDATES)

    @patch(
        "src.api.routes.dem_lego_design.load_surface_plan",
        return_value=SURFACE_PLAN,
    )
    def test_create_surface_plan(self, load_plan) -> None:
        body = DemSurfacePlanRequest(
            targetSurfacePlate=[[1.0]],
            targetHeightPlate=[[1]],
            targetColorId=[[4]],
            partIds=["3024.dat"],
        )

        result = self.plan_endpoint(body, self.request)

        load_plan.assert_called_once_with(
            body.targetSurfacePlate,
            body.targetHeightPlate,
            body.targetColorId,
            body.partIds,
            self.request.app.state.db_engine,
            API_CONFIG,
        )
        self.assertEqual(result, SURFACE_PLAN)

    @patch(
        "src.api.routes.dem_lego_design.load_final_dem_design",
        return_value=FINAL_DESIGN,
    )
    @patch(
        "src.api.routes.dem_lego_design.load_dem_design_targets",
        return_value={
            "targetSurfacePlate": [[1.0]],
            "targetHeightPlate": [[1]],
            "targetColorId": [[4]],
            "partIds": ["3024.dat"],
        },
    )
    @patch("src.api.routes.dem_lego_design.load_model_asset", return_value={"model": "asset"})
    def test_create_final_design(self, load_asset, load_targets, load_final_design) -> None:
        body = DemFinalDesignModelRequest(
            locale="en-US",
            timezone="UTC",
            modelId="model-id",
            strategy=API_CONFIG["final_design"]["strategies"]["surface_plan"],
            horizontalKmPerStud=20,
            verticalMetersPerPlate=500,
            aggregation="percentile",
            minCoverageRatio=0.25,
        )

        result = self.final_endpoint(body, self.request)

        load_asset.assert_called_once_with(
            self.request.app.state.terrain_config,
            body.modelId,
        )
        load_targets.assert_called_once_with(
            {"model": "asset"},
            {
                "horizontal_km_per_stud": body.horizontalKmPerStud,
                "vertical_meters_per_plate": body.verticalMetersPerPlate,
                "aggregation": body.aggregation,
                "minimum_coverage_ratio": body.minCoverageRatio,
            },
            self.request.app.state.db_engine,
            API_CONFIG["design_input"],
        )
        load_final_design.assert_called_once_with(
            [[1.0]],
            [[1]],
            [[4]],
            ["3024.dat"],
            self.request.app.state.db_engine,
            API_CONFIG,
        )
        self.assertEqual(result["modelId"], "model-id")
        self.assertEqual(result["exportContext"]["locale"], "en-US")
        self.assertIn("catalogVersion", result["exportContext"])
        self.assertEqual(result["strategy"], FINAL_DESIGN["strategy"])

    @patch(
        "src.api.routes.dem_lego_design.load_colored_replacement_final_dem_design",
        return_value={**FINAL_DESIGN, "strategy": "colored-replacement-final-design"},
    )
    @patch(
        "src.api.routes.dem_lego_design.create_colored_heightmap_asset",
        return_value={"modelId": "heightmap"},
    )
    @patch(
        "src.api.routes.dem_lego_design.load_dem_design_targets",
        return_value={
            "targetSurfacePlate": [[1.0]],
            "targetHeightPlate": [[1]],
            "targetColorId": [[4]],
            "partIds": ["3024.dat"],
        },
    )
    @patch("src.api.routes.dem_lego_design.load_model_asset", return_value={"model": "asset"})
    def test_create_colored_replacement_final_design(
        self,
        load_asset,
        load_targets,
        create_heightmap,
        load_replacement_final,
    ) -> None:
        body = DemFinalDesignModelRequest(
            locale="en-US",
            timezone="UTC",
            modelId="model-id",
            strategy=API_CONFIG["final_design"]["strategies"]["colored_replacement"],
            horizontalKmPerStud=20,
            verticalMetersPerPlate=500,
            aggregation="percentile",
            minCoverageRatio=0.25,
        )

        result = self.final_endpoint(body, self.request)

        load_asset.assert_called_once_with(
            self.request.app.state.terrain_config,
            body.modelId,
        )
        create_heightmap.assert_called_once_with(
            {"model": "asset"},
            body.modelId,
            {
                "horizontalKmPerStud": body.horizontalKmPerStud,
                "verticalMetersPerPlate": body.verticalMetersPerPlate,
                "aggregation": body.aggregation,
                "minCoverageRatio": body.minCoverageRatio,
            },
            self.request.app.state.terrain_config,
        )
        load_replacement_final.assert_called_once_with(
            {"modelId": "heightmap"},
            [[1.0]],
            [[1]],
            [[4]],
            ["3024.dat"],
            self.request.app.state.db_engine,
            API_CONFIG,
        )
        self.assertEqual(result["strategy"], "colored-replacement-final-design")


if __name__ == "__main__":
    unittest.main()
