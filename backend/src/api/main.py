"""FastAPI application entrypoint."""
import logging
from threading import Lock

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from src.api.errors import ERROR_RESPONSES, install_error_handlers
from src.api.routes.auth import create_auth_router
from src.api.routes.dem_lego_design import create_dem_lego_design_router
from src.api.routes.domain_content import create_domain_content_router
from src.api.routes.fitting_candidate_recall import (
    create_fitting_candidate_recall_router,
)
from src.api.routes.lego_design import create_lego_design_router
from src.api.routes.mesh_models import create_mesh_model_router
from src.api.routes.model_fitting import create_model_fitting_router
from src.api.routes.pixel_art import create_pixel_art_router
from src.api.routes.model_assets import create_model_asset_router
from src.api.routes.lego_heightmap import create_lego_heightmap_router
from src.api.routes.part_search import create_part_search_router
from src.api.routes.submodels import create_submodel_router
from src.api.routes.terrain import create_terrain_router
from src.config.app_settings import BACKEND_ROOT, load_json_config
from src.config.db_config import get_db_engine_options, get_db_url
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.config.fitting_candidate_recall_config import (
    REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
)
from src.config.model_fitting_config import REQUIRED_MODEL_FITTING_CONFIG_KEYS
from src.config.submodel_config import REQUIRED_SUBMODEL_CONFIG_KEYS
from src.services.database_schema_service import validate_database_revision


logger = logging.getLogger(__name__)


REQUIRED_SEARCH_API_CONFIG_KEYS = (
    "app",
    "cors",
    "routes",
    "default_limit",
    "max_limit",
    "image_lookup_limit",
    "image_lookup_sql",
    "ldraw_suffix",
    "logical_size_pattern",
    "logical_size_match_groups",
    "part_number_pattern",
    "part_number_rejected_terms",
    "category_terms",
    "connector_terms",
    "side_terms",
    "vertical_terms",
    "direction_groups",
    "connector_requirement_fields",
    "default_connector_min_count",
    "image_part_candidates",
    "model_assets",
)

REQUIRED_TERRAIN_CONFIG_KEYS = (
    "geojson_path",
    "output_path",
    "text_encoding",
    "default_source_name",
    "source_name_dataset_separator",
    "dem_datasets",
    "latitude_meters_per_degree",
    "radians_per_degree",
    "coordinate_average_divisor",
    "sample_chunk_size",
    "mask_worker_count",
    "mask_rows_per_task",
    "coordinate_decimals",
    "elevation_decimals",
    "nodata_value",
    "worldcover",
    "asset_schema",
    "heightmap_asset_schema",
    "heightmap_generation",
    "render_options",
    "model_store_path",
    "lego_heightmap_model_store_path",
    "model_file_extension",
    "model_id_hex_length",
    "progress",
    "job_status",
    "http_status",
    "errors",
)

REQUIRED_PIXEL_ART_CONFIG_KEYS = (
    "asset_schema",
    "routes",
    "storage",
    "image",
    "quantization",
    "algorithms",
    "kmeans",
    "preprocessing",
    "feature_analysis",
    "metadata",
    "errors",
    "http_status",
)

REQUIRED_LEGO_DESIGN_CONFIG_KEYS = (
    "routes",
    "parts",
    "candidate_features",
    "colors",
    "algorithm",
    "heightmap_design",
    "ldraw",
    "plan_export",
    "job_status",
    "progress",
    "jobs",
    "errors",
    "http_status",
)

REQUIRED_DEM_LEGO_DESIGN_CONFIG_KEYS = (
    "routes",
    "parts",
    "structure",
    "design_input",
    "algorithm",
    "surface_profile",
    "surface_patch",
    "surface_plan",
    "colored_replacement",
    "support_base",
    "final_design",
    "dem_ldraw",
    "errors",
    "http_status",
)

REQUIRED_MESH_MODEL_CONFIG_KEYS = (
    "routes",
    "storage",
    "upload",
    "model_asset",
    "response",
    "color_summary",
    "glb",
    "json_keys",
    "metadata_keys",
    "errors",
    "http_status",
)


def resolve_terrain_paths(terrain_config: dict) -> dict:
    return {
        **terrain_config,
        "dem_datasets": {
            **terrain_config["dem_datasets"],
            "options": [
                {
                    **dataset,
                    "dataset_path": str(BACKEND_ROOT.parent / dataset["dataset_path"]),
                }
                for dataset in terrain_config["dem_datasets"]["options"]
            ],
        },
        "worldcover": {
            **terrain_config["worldcover"],
            "dataset_glob": str(BACKEND_ROOT.parent / terrain_config["worldcover"]["dataset_glob"]),
        },
        "model_store_path": str(BACKEND_ROOT.parent / terrain_config["model_store_path"]),
        "lego_heightmap_model_store_path": str(
            BACKEND_ROOT.parent / terrain_config["lego_heightmap_model_store_path"]
        ),
    }


def lego_heightmap_config(terrain_config: dict) -> dict:
    return {
        **terrain_config,
        "model_store_path": terrain_config["lego_heightmap_model_store_path"],
    }


def create_app() -> FastAPI:
    config = load_json_config("search_api.json", REQUIRED_SEARCH_API_CONFIG_KEYS)
    terrain_config = load_json_config("taiwan_dem_terrain.json", REQUIRED_TERRAIN_CONFIG_KEYS)
    pixel_art_config = load_json_config("pixel_art.json", REQUIRED_PIXEL_ART_CONFIG_KEYS)
    lego_design_config = load_json_config("lego_design.json", REQUIRED_LEGO_DESIGN_CONFIG_KEYS)
    dem_lego_design_config = load_json_config(
        "dem_lego_design.json",
        REQUIRED_DEM_LEGO_DESIGN_CONFIG_KEYS,
    )
    mesh_model_config = load_json_config("mesh_model_import.json", REQUIRED_MESH_MODEL_CONFIG_KEYS)
    submodel_config = load_json_config("submodel.json", REQUIRED_SUBMODEL_CONFIG_KEYS)
    model_fitting_config = load_json_config(
        "model_fitting.json",
        REQUIRED_MODEL_FITTING_CONFIG_KEYS,
    )
    fitting_candidate_recall_config = load_json_config(
        "fitting_candidate_recall.json",
        REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
    )
    component_repo_config = load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )
    terrain_config = resolve_terrain_paths(terrain_config)
    mesh_model_config = {
        **mesh_model_config,
        "storage": {
            **mesh_model_config["storage"],
            "model_store_path": str(BACKEND_ROOT.parent / mesh_model_config["storage"]["model_store_path"]),
        },
    }
    app = FastAPI(title=config["app"]["title"], responses=ERROR_RESPONSES)
    install_error_handlers(app)
    app.state.search_api_config = config
    app.state.model_asset_config = config["model_assets"]
    app.state.terrain_config = terrain_config
    app.state.lego_heightmap_config = lego_heightmap_config(terrain_config)
    app.state.pixel_art_config = pixel_art_config
    app.state.lego_design_config = lego_design_config
    app.state.dem_lego_design_config = dem_lego_design_config
    app.state.mesh_model_config = mesh_model_config
    app.state.submodel_config = submodel_config
    app.state.model_fitting_config = model_fitting_config
    app.state.fitting_candidate_recall_config = fitting_candidate_recall_config
    app.state.component_repo_config = component_repo_config
    app.state.lego_design_jobs = {}
    app.state.lego_design_jobs_lock = Lock()
    app.state.terrain_jobs = {}
    app.state.terrain_jobs_lock = Lock()
    db_engine_options = get_db_engine_options()
    app.state.db_engine = create_engine(
        get_db_url(),
        echo=False,
        poolclass=QueuePool,
        **db_engine_options,
    )
    logger.info(
        "Database connection pool configured poolSize=%s maxOverflow=%s "
        "poolTimeoutSeconds=%s poolRecycleSeconds=%s",
        db_engine_options["pool_size"],
        db_engine_options["max_overflow"],
        db_engine_options["pool_timeout"],
        db_engine_options["pool_recycle"],
    )
    validate_database_revision(app.state.db_engine)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config["cors"]["allow_origins"],
        allow_methods=config["cors"]["allow_methods"],
        allow_headers=config["cors"]["allow_headers"],
    )

    @app.get(config["routes"]["health"])
    def health() -> dict[str, str]:
        return {"status": config["app"]["health_status"]}

    app.include_router(create_auth_router())
    app.include_router(create_part_search_router(config))
    app.include_router(create_terrain_router(config, terrain_config))
    app.include_router(
        create_lego_heightmap_router(
            config,
            terrain_config,
            app.state.lego_heightmap_config,
        )
    )
    app.include_router(create_lego_design_router(lego_design_config))
    app.include_router(create_dem_lego_design_router(dem_lego_design_config))
    app.include_router(create_model_asset_router(config))
    app.include_router(create_mesh_model_router(mesh_model_config))
    app.include_router(create_pixel_art_router(pixel_art_config))
    app.include_router(create_submodel_router(submodel_config))
    app.include_router(
        create_fitting_candidate_recall_router(
            fitting_candidate_recall_config,
            component_repo_config,
        )
    )
    app.include_router(create_model_fitting_router(model_fitting_config))
    app.include_router(create_domain_content_router(component_repo_config))
    return app


app = create_app()
