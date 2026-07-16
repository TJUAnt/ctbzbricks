"""Read models for LDraw search results."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LDrawPartCandidate:
    ldraw_part_num: str
    name: str | None
    category: str | None
    relative_path: str
    width_ldu: float | None
    height_ldu: float | None
    depth_ldu: float | None
    logical_width_stud: float | None
    logical_depth_stud: float | None
    logical_height_plate: float | None
    geometry_status: str
    score: float = 0.0
    score_reason: str | None = None


@dataclass(frozen=True)
class XrefPartMapping:
    rebrickable_part_num: str | None
    ldraw_part_num: str | None
    bricklink_part_num: str | None
    lego_design_id: str | None
    relation_type: str
    source: str
    confidence: float


@dataclass(frozen=True)
class ResolvedLDrawPartCandidate:
    mapping: XrefPartMapping
    geometry: LDrawPartCandidate


@dataclass(frozen=True)
class ConnectorInstanceCandidate:
    ldraw_part_num: str
    source_type: str
    source_meta_id: int | None
    connector_kind: str
    normalized_connector_type: str | None
    connector_group: str | None
    connector_gender: str | None
    pos_x: float
    pos_y: float
    pos_z: float
    ori_11: float
    ori_12: float
    ori_13: float
    ori_21: float
    ori_22: float
    ori_23: float
    ori_31: float
    ori_32: float
    ori_33: float
    direction_x: float | None
    direction_y: float | None
    direction_z: float | None
    direction_label: str | None
    direction_group: str | None
    radius: float | None
    length: float | None
    caps: str | None
    center_flag: bool
    slide_flag: bool
    confidence: float


@dataclass(frozen=True)
class PartSearchCandidate:
    geometry: LDrawPartCandidate
    mapping: XrefPartMapping | None
    connector_counts: dict[str, int]
    score: float
    score_reason: str
