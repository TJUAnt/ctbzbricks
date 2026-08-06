"""
SQLAlchemy 模型定义
用于将CSV数据导入MySQL数据库
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import declarative_base, relationship

from src.config.dem_slope_candidate_config import (
    DEM_SLOPE_CANDIDATE_DATABASE_CONFIG,
)
from src.config.component_repo_config import COMPONENT_REPO_DATABASE_CONFIG
from src.config.fitting_candidate_profile_config import (
    FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG,
)
from src.config.model_fitting_config import MODEL_FITTING_DATABASE_CONFIG
from src.config.part_shape_profile_config import (
    PART_SHAPE_PROFILE_DATABASE_CONFIG,
)
from src.config.submodel_config import SUBMODEL_DATABASE_CONFIG

Base = declarative_base()


class Theme(Base):
    """主题表"""
    __tablename__ = 'rb_themes'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey('rb_themes.id'), nullable=True)

    children = relationship('Theme', backref='parent', remote_side=[id])
    sets = relationship('Set', back_populates='theme')


class Set(Base):
    """乐高套装表"""
    __tablename__ = 'rb_sets'

    set_num = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    year = Column(Integer)
    theme_id = Column(Integer, ForeignKey('rb_themes.id'))
    num_parts = Column(Integer)
    img_url = Column(String(500))

    theme = relationship('Theme', back_populates='sets')
    inventories = relationship(
        'Inventory',
        primaryjoin='Set.set_num == foreign(Inventory.set_num)',
        viewonly=True,
    )


class PartCategory(Base):
    """零件类别表"""
    __tablename__ = 'rb_part_categories'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)

    parts = relationship('Part', back_populates='category')


class Part(Base):
    """零件表"""
    __tablename__ = 'rb_parts'

    part_num = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    part_cat_id = Column(Integer, ForeignKey('rb_part_categories.id'))
    part_material = Column(String(100))

    category = relationship('PartCategory', back_populates='parts')
    inventory_parts = relationship('InventoryPart', back_populates='part')
    image = relationship('PartImage', back_populates='part', uselist=False)


class Color(Base):
    """颜色表"""
    __tablename__ = 'rb_colors'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    rgb = Column(String(10))
    is_trans = Column(Boolean)

    inventory_parts = relationship(
        'InventoryPart',
        primaryjoin='Color.id == foreign(InventoryPart.color_id)',
        viewonly=True,
    )


class Inventory(Base):
    """库存表"""
    __tablename__ = 'rb_inventories'

    id = Column(Integer, primary_key=True)
    version = Column(Integer, default=1)
    # Rebrickable inventories may belong to either a set or a minifigure.
    set_num = Column(String(50), index=True)

    set = relationship(
        'Set',
        primaryjoin='foreign(Inventory.set_num) == Set.set_num',
        viewonly=True,
    )
    inventory_parts = relationship('InventoryPart', back_populates='inventory')
    inventory_sets = relationship('InventorySet', back_populates='inventory')
    inventory_minifigs = relationship('InventoryMinifig', back_populates='inventory')


class InventoryPart(Base):
    """库存零件表"""
    __tablename__ = 'rb_inventory_parts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey('rb_inventories.id'))
    part_num = Column(String(50), ForeignKey('rb_parts.part_num'))
    # Rebrickable uses color_id=0 as an unknown/no-color sentinel.
    color_id = Column(Integer, index=True)
    quantity = Column(Integer)
    is_spare = Column(Boolean)

    inventory = relationship('Inventory', back_populates='inventory_parts')
    part = relationship('Part', back_populates='inventory_parts')
    color = relationship(
        'Color',
        primaryjoin='foreign(InventoryPart.color_id) == Color.id',
        viewonly=True,
    )


class PartImage(Base):
    """One representative image URL per Rebrickable part."""
    __tablename__ = 'rb_part_images'

    part_num = Column(String(50), ForeignKey('rb_parts.part_num'), primary_key=True)
    img_url = Column(String(500), nullable=False)

    part = relationship('Part', back_populates='image')


class InventorySet(Base):
    """库存套装表"""
    __tablename__ = 'rb_inventory_sets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey('rb_inventories.id'))
    set_num = Column(String(50), ForeignKey('rb_sets.set_num'))
    quantity = Column(Integer)

    inventory = relationship('Inventory', back_populates='inventory_sets')
    set = relationship('Set')


class Minifig(Base):
    """小人仔表"""
    __tablename__ = 'rb_minifigs'

    fig_num = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)

    inventory_minifigs = relationship('InventoryMinifig', back_populates='minifig')


class InventoryMinifig(Base):
    """库存小人仔表"""
    __tablename__ = 'rb_inventory_minifigs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey('rb_inventories.id'))
    figure_num = Column(String(50), ForeignKey('rb_minifigs.fig_num'))
    quantity = Column(Integer)

    inventory = relationship('Inventory', back_populates='inventory_minifigs')
    minifig = relationship('Minifig', back_populates='inventory_minifigs')


class PartRelationship(Base):
    """零件关系表"""
    __tablename__ = 'rb_part_relationships'

    id = Column(Integer, primary_key=True, autoincrement=True)
    part_num = Column(String(50), ForeignKey('rb_parts.part_num'))
    rel_type = Column(String(50))
    related_part_num = Column(String(50), ForeignKey('rb_parts.part_num'))

    part = relationship('Part', foreign_keys=[part_num])
    related_part = relationship('Part', foreign_keys=[related_part_num])


class XrefPartNumber(Base):
    """不同零件编号体系之间的映射表"""
    __tablename__ = 'xref_part_numbers'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    rebrickable_part_num = Column(String(64), nullable=True)
    ldraw_part_num = Column(String(128), nullable=True)
    bricklink_part_num = Column(String(64), nullable=True)
    lego_design_id = Column(String(64), nullable=True)
    relation_type = Column(String(32), default='unknown')
    source = Column(String(64), default='manual')
    confidence = Column(Numeric(5, 4), default=0.5000)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            'rebrickable_part_num',
            'ldraw_part_num',
            'relation_type',
            'source',
            name='uk_xref_rb_ldraw_relation_source',
        ),
        Index('idx_xref_ldraw', 'ldraw_part_num'),
        Index('idx_xref_bricklink', 'bricklink_part_num'),
        Index('idx_xref_design_id', 'lego_design_id'),
    )


class LDrawFile(Base):
    """LDraw 库中的 .dat 文件，包括 parts/ 与 p/"""
    __tablename__ = 'ldraw_files'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    relative_path = Column(String(512), nullable=False, unique=True)
    file_name = Column(String(128), nullable=False)
    library_section = Column(String(32), nullable=False)
    file_role = Column(String(32), default='unknown')
    title = Column(String(512), nullable=True)
    category = Column(String(128), nullable=True)
    file_hash = Column(String(64), nullable=True)
    line_count = Column(Integer, nullable=True)
    source = Column(String(64), default='ldraw_official')
    import_status = Column(String(32), default='pending')
    parse_error_code = Column(String(160), nullable=True)
    parse_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    part = relationship('LDrawPart', back_populates='file', uselist=False)
    outgoing_references = relationship(
        'LDrawFileReference',
        back_populates='from_file',
        foreign_keys='LDrawFileReference.from_file_id',
    )
    incoming_references = relationship(
        'LDrawFileReference',
        back_populates='to_file',
        foreign_keys='LDrawFileReference.to_file_id',
    )

    __table_args__ = (
        Index('idx_ldraw_file_section', 'library_section'),
        Index('idx_ldraw_file_role', 'file_role'),
        Index('idx_ldraw_file_name', 'file_name'),
        Index('idx_ldraw_file_status', 'import_status'),
    )


class LDrawFileReference(Base):
    """LDraw type-1 子文件引用关系，用于递归解析几何"""
    __tablename__ = 'ldraw_file_references'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    from_file_id = Column(BigInteger, ForeignKey('ldraw_files.id'), nullable=False)
    to_file_id = Column(BigInteger, ForeignKey('ldraw_files.id'), nullable=True)
    line_no = Column(Integer, nullable=False)
    color_code = Column(String(32), nullable=True)
    ref_name = Column(String(256), nullable=False)
    resolved_relative_path = Column(String(512), nullable=True)
    resolve_status = Column(String(32), default='pending')
    resolve_error_code = Column(String(160), nullable=True)
    resolve_error_params_json = Column(JSON, nullable=True)

    pos_x = Column(Float, nullable=False)
    pos_y = Column(Float, nullable=False)
    pos_z = Column(Float, nullable=False)

    ori_11 = Column(Float, nullable=False)
    ori_12 = Column(Float, nullable=False)
    ori_13 = Column(Float, nullable=False)
    ori_21 = Column(Float, nullable=False)
    ori_22 = Column(Float, nullable=False)
    ori_23 = Column(Float, nullable=False)
    ori_31 = Column(Float, nullable=False)
    ori_32 = Column(Float, nullable=False)
    ori_33 = Column(Float, nullable=False)

    created_at = Column(DateTime, server_default=func.now())

    from_file = relationship(
        'LDrawFile',
        back_populates='outgoing_references',
        foreign_keys=[from_file_id],
    )
    to_file = relationship(
        'LDrawFile',
        back_populates='incoming_references',
        foreign_keys=[to_file_id],
    )

    __table_args__ = (
        UniqueConstraint('from_file_id', 'line_no', name='uk_ldraw_ref_file_line'),
        Index('idx_ldraw_ref_to', 'to_file_id'),
        Index('idx_ldraw_ref_name', 'ref_name'),
        Index('idx_ldraw_ref_status', 'resolve_status'),
    )


class LDrawPart(Base):
    """LDraw 真实零件索引表"""
    __tablename__ = 'ldraw_parts'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ldraw_part_num = Column(String(128), nullable=False, unique=True)
    file_id = Column(BigInteger, ForeignKey('ldraw_files.id'), nullable=False, unique=True)
    name = Column(String(512), nullable=True)
    content_locale = Column(
        String(16),
        nullable=False,
        default='en-US',
        server_default='en-US',
    )
    category = Column(String(128), nullable=True)
    relative_path = Column(String(512), nullable=False)
    file_hash = Column(String(64), nullable=True)
    source = Column(String(64), default='ldraw_official')
    import_status = Column(String(32), default='pending')
    parse_error_code = Column(String(160), nullable=True)
    parse_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    file = relationship('LDrawFile', back_populates='part')
    geometry = relationship('LDrawPartGeometry', back_populates='part', uselist=False)
    shape_profiles = relationship(
        'LDrawPartShapeProfile',
        back_populates='part',
        cascade='all, delete-orphan',
    )
    translations = relationship(
        'PartTranslation',
        back_populates='part',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        Index('idx_ldraw_part_num', 'ldraw_part_num'),
        Index('idx_ldraw_category', 'category'),
        Index('idx_ldraw_status', 'import_status'),
    )


class PartTranslation(Base):
    """Reviewed localized content for one official LDraw part."""

    __tablename__ = 'part_translations'

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ldraw_part_id = Column(BigInteger, ForeignKey('ldraw_parts.id'), nullable=False)
    locale = Column(String(16), nullable=False)
    name = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    translation_status = Column(String(32), nullable=False)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    part = relationship('LDrawPart', back_populates='translations')

    __table_args__ = (
        UniqueConstraint('ldraw_part_id', 'locale', name='uq_part_translation_locale'),
        Index('idx_part_translations_locale', 'locale'),
        Index('idx_part_translations_status', 'translation_status'),
    )


class LDrawPartGeometry(Base):
    """LDraw 零件几何与逻辑尺寸结果表"""
    __tablename__ = 'ldraw_part_geometry'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ldraw_part_id = Column(BigInteger, ForeignKey('ldraw_parts.id'), nullable=False)

    bbox_min_x = Column(Float, nullable=True)
    bbox_min_y = Column(Float, nullable=True)
    bbox_min_z = Column(Float, nullable=True)
    bbox_max_x = Column(Float, nullable=True)
    bbox_max_y = Column(Float, nullable=True)
    bbox_max_z = Column(Float, nullable=True)

    width_ldu = Column(Float, nullable=True)
    height_ldu = Column(Float, nullable=True)
    depth_ldu = Column(Float, nullable=True)
    width_mm = Column(Float, nullable=True)
    height_mm = Column(Float, nullable=True)
    depth_mm = Column(Float, nullable=True)

    logical_width_stud = Column(Float, nullable=True)
    logical_depth_stud = Column(Float, nullable=True)
    logical_height_plate = Column(Float, nullable=True)

    vertex_count = Column(Integer, nullable=True)
    face_count = Column(Integer, nullable=True)
    geometry_status = Column(String(32), default='parsed')
    geometry_error_code = Column(String(160), nullable=True)
    geometry_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    part = relationship('LDrawPart', back_populates='geometry')

    __table_args__ = (
        UniqueConstraint('ldraw_part_id', name='uk_ldraw_geometry_part'),
        Index('idx_ldraw_geometry_size', 'width_ldu', 'height_ldu', 'depth_ldu'),
        Index(
            'idx_ldraw_logical_size',
            'logical_width_stud',
            'logical_depth_stud',
            'logical_height_plate',
        ),
    )


class LDrawPartShapeProfile(Base):
    """Persisted shape recall profile generated from one LDraw part mesh."""

    __tablename__ = PART_SHAPE_PROFILE_DATABASE_CONFIG["table"]

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    ldraw_part_id = Column(BigInteger, ForeignKey('ldraw_parts.id'), nullable=False)
    profile_key = Column(
        String(PART_SHAPE_PROFILE_DATABASE_CONFIG["string_lengths"]["profile_key"]),
        nullable=False,
    )
    samples_per_stud_axis = Column(Integer, nullable=False)
    profile_status = Column(
        String(PART_SHAPE_PROFILE_DATABASE_CONFIG["string_lengths"]["profile_status"]),
        nullable=False,
    )
    profile_error_type = Column(
        String(PART_SHAPE_PROFILE_DATABASE_CONFIG["string_lengths"]["profile_error_type"]),
        nullable=True,
    )
    source_hash = Column(
        String(PART_SHAPE_PROFILE_DATABASE_CONFIG["string_lengths"]["source_hash"]),
        nullable=False,
    )
    bbox_json = Column(JSON, nullable=True)
    logical_size_json = Column(JSON, nullable=True)
    surface_profile_json = Column(JSON, nullable=True)
    collision_profile_json = Column(JSON, nullable=True)
    connection_mask_json = Column(JSON, nullable=True)
    profile_error_code = Column(String(160), nullable=True)
    profile_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    part = relationship('LDrawPart', back_populates='shape_profiles')

    __table_args__ = (
        UniqueConstraint(
            'ldraw_part_id',
            'profile_key',
            name=PART_SHAPE_PROFILE_DATABASE_CONFIG["constraints"]["part_profile_unique"],
        ),
        Index(
            PART_SHAPE_PROFILE_DATABASE_CONFIG["indexes"]["part"],
            'ldraw_part_id',
        ),
        Index(
            PART_SHAPE_PROFILE_DATABASE_CONFIG["indexes"]["status"],
            'profile_status',
        ),
        Index(
            PART_SHAPE_PROFILE_DATABASE_CONFIG["indexes"]["profile_key"],
            'profile_key',
        ),
        Index(
            PART_SHAPE_PROFILE_DATABASE_CONFIG["indexes"]["samples"],
            'samples_per_stud_axis',
        ),
    )


class DemSlopeCandidate(Base):
    """Persisted DEM slope eligibility and catalog capability for one LDraw part."""

    __tablename__ = DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["candidate_table"]

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ldraw_part_id = Column(
        BigInteger,
        ForeignKey(f"{LDrawPart.__tablename__}.id"),
        nullable=False,
    )
    candidate_enabled = Column(Boolean, nullable=False)
    catalog_status = Column(
        String(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["string_lengths"]["catalog_status"]
        ),
        nullable=False,
    )
    current_candidate = Column(Boolean, nullable=False)
    capability_eligible = Column(Boolean, nullable=False)
    family = Column(
        String(DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["string_lengths"]["family"]),
        nullable=True,
    )
    group_id = Column(
        String(DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["string_lengths"]["group_id"]),
        nullable=True,
    )
    flags_json = Column(JSON, nullable=False)
    database_geometry_json = Column(JSON, nullable=False)
    capability_json = Column(JSON, nullable=True)
    catalog_payload_json = Column(JSON, nullable=False)
    source_hash = Column(
        String(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["string_lengths"]["source_hash"]
        ),
        nullable=False,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    part = relationship("LDrawPart")
    patterns = relationship(
        "DemSlopeCandidatePattern",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "ldraw_part_id",
            name=DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["constraints"][
                "candidate_part_unique"
            ],
        ),
        Index(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["indexes"]["candidate_enabled"],
            "candidate_enabled",
        ),
        Index(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["indexes"]["candidate_family"],
            "family",
        ),
        Index(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["indexes"]["candidate_group"],
            "group_id",
        ),
    )


class DemSlopeCandidatePattern(Base):
    """Ranked Heightmap pattern solved by one DEM slope candidate."""

    __tablename__ = DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["pattern_table"]

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id = Column(
        BigInteger,
        ForeignKey(
            f"{DEM_SLOPE_CANDIDATE_DATABASE_CONFIG['candidate_table']}.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    pattern_rank = Column(Integer, nullable=False)
    pattern_key = Column(
        String(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["string_lengths"]["pattern_key"]
        ),
        nullable=False,
    )
    heightmap_pattern_json = Column(JSON, nullable=False)
    match_metrics_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    candidate = relationship("DemSlopeCandidate", back_populates="patterns")

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "pattern_rank",
            name=DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["constraints"][
                "pattern_rank_unique"
            ],
        ),
        UniqueConstraint(
            "candidate_id",
            "pattern_key",
            name=DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["constraints"][
                "pattern_key_unique"
            ],
        ),
        CheckConstraint(
            "pattern_rank >= 1 AND pattern_rank <= "
            f"{DEM_SLOPE_CANDIDATE_DATABASE_CONFIG['maximum_patterns_per_candidate']}",
            name=DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["constraints"][
                "pattern_rank_check"
            ],
        ),
        Index(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["indexes"]["pattern_lookup"],
            "pattern_key",
            "pattern_rank",
        ),
        Index(
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["indexes"]["pattern_key"],
            "pattern_key",
        ),
    )


class LDrawShadowFile(Base):
    """LDCad Shadow Library file metadata."""
    __tablename__ = 'ldraw_shadow_files'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ldraw_part_num = Column(String(128), nullable=False)
    relative_path = Column(String(512), nullable=False)
    file_hash = Column(String(64), nullable=True)
    source_repo = Column(String(255), nullable=True)
    source_commit = Column(String(64), nullable=True)
    has_snap_meta = Column(Boolean, default=False)
    has_mirror_meta = Column(Boolean, default=False)
    import_status = Column(String(32), default='pending')
    parse_error_code = Column(String(160), nullable=True)
    parse_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    meta_rows = relationship('LDrawShadowMetaRaw', back_populates='shadow_file')

    __table_args__ = (
        UniqueConstraint(
            'ldraw_part_num',
            'relative_path',
            name='uk_shadow_file',
        ),
        Index('idx_shadow_part_num', 'ldraw_part_num'),
        Index('idx_shadow_status', 'import_status'),
    )


class LDrawShadowMetaRaw(Base):
    """Raw !LDCAD meta line from an LDCad Shadow Library file."""
    __tablename__ = 'ldraw_shadow_meta_raw'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    shadow_file_id = Column(
        BigInteger,
        ForeignKey('ldraw_shadow_files.id'),
        nullable=False,
    )
    line_no = Column(Integer, nullable=False)
    meta_type = Column(String(64), nullable=False)
    raw_line = Column(Text, nullable=False)
    parsed_json = Column(JSON, nullable=True)
    parse_status = Column(String(32), default='pending')
    parse_error_code = Column(String(160), nullable=True)
    parse_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    shadow_file = relationship('LDrawShadowFile', back_populates='meta_rows')
    includes = relationship('LDrawShadowInclude', back_populates='source_meta')

    __table_args__ = (
        UniqueConstraint(
            'shadow_file_id',
            'line_no',
            name='uk_shadow_meta_file_line',
        ),
        Index('idx_shadow_meta_file', 'shadow_file_id'),
        Index('idx_shadow_meta_type', 'meta_type'),
        Index('idx_shadow_meta_status', 'parse_status'),
    )


class LDrawShadowInclude(Base):
    """SNAP_INCL reference from one shadow file to another shadow definition."""
    __tablename__ = 'ldraw_shadow_includes'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    from_ldraw_part_num = Column(String(128), nullable=False)
    to_shadow_ref = Column(String(128), nullable=False)
    source_meta_id = Column(
        BigInteger,
        ForeignKey('ldraw_shadow_meta_raw.id'),
        nullable=False,
    )
    pos_x = Column(Float, nullable=True)
    pos_y = Column(Float, nullable=True)
    pos_z = Column(Float, nullable=True)
    ori_json = Column(JSON, nullable=True)
    grid_json = Column(JSON, nullable=True)
    raw_params = Column(JSON, nullable=True)
    expand_status = Column(String(32), default='pending')
    expand_error_code = Column(String(160), nullable=True)
    expand_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    source_meta = relationship('LDrawShadowMetaRaw', back_populates='includes')

    __table_args__ = (
        UniqueConstraint('source_meta_id', name='uk_shadow_include_meta'),
        Index('idx_shadow_include_from', 'from_ldraw_part_num'),
        Index('idx_shadow_include_to', 'to_shadow_ref'),
        Index('idx_shadow_include_status', 'expand_status'),
    )


class ConnectorInstance(Base):
    """Algorithm-usable connector point for an LDraw part."""
    __tablename__ = 'connector_instances'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ldraw_part_num = Column(String(128), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_meta_id = Column(
        BigInteger,
        ForeignKey('ldraw_shadow_meta_raw.id'),
        nullable=True,
    )
    connector_kind = Column(String(64), nullable=False)
    normalized_connector_type = Column(String(64), nullable=True)
    connector_group = Column(String(128), nullable=True)
    connector_gender = Column(String(16), nullable=True)

    pos_x = Column(Float, nullable=False)
    pos_y = Column(Float, nullable=False)
    pos_z = Column(Float, nullable=False)

    ori_11 = Column(Float, nullable=False)
    ori_12 = Column(Float, nullable=False)
    ori_13 = Column(Float, nullable=False)
    ori_21 = Column(Float, nullable=False)
    ori_22 = Column(Float, nullable=False)
    ori_23 = Column(Float, nullable=False)
    ori_31 = Column(Float, nullable=False)
    ori_32 = Column(Float, nullable=False)
    ori_33 = Column(Float, nullable=False)

    direction_x = Column(Float, nullable=True)
    direction_y = Column(Float, nullable=True)
    direction_z = Column(Float, nullable=True)
    direction_label = Column(String(32), nullable=True)
    direction_group = Column(String(32), nullable=True)

    radius = Column(Float, nullable=True)
    length = Column(Float, nullable=True)
    caps = Column(String(32), nullable=True)
    center_flag = Column(Boolean, default=False)
    slide_flag = Column(Boolean, default=False)
    confidence = Column(Numeric(5, 4), default=1.0000)
    raw_params = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    source_meta = relationship('LDrawShadowMetaRaw')

    __table_args__ = (
        Index('idx_conn_part', 'ldraw_part_num'),
        Index(
            'idx_conn_type_gender',
            'normalized_connector_type',
            'connector_gender',
        ),
        Index('idx_conn_kind', 'connector_kind'),
        Index('idx_conn_group', 'connector_group'),
        Index('idx_conn_direction', 'direction_group', 'direction_label'),
        Index('idx_conn_pos', 'pos_x', 'pos_y', 'pos_z'),
    )


class LDrawSubmodel(Base):
    """Reusable LDraw assembly composed from multiple part lines."""

    __tablename__ = SUBMODEL_DATABASE_CONFIG["submodel_table"]

    id = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    name = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["name"]),
        nullable=False,
    )
    ldraw_content = Column(Text, nullable=False)
    color_percentages_json = Column(JSON, nullable=False)
    remarks = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    parts = relationship(
        "LDrawSubmodelPart",
        back_populates="submodel",
        cascade="all, delete-orphan",
    )
    connectors = relationship(
        "LDrawSubmodelConnector",
        back_populates="submodel",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            SUBMODEL_DATABASE_CONFIG["indexes"]["submodel_created"],
            "created_at",
        ),
    )


class LDrawSubmodelPart(Base):
    """Parsed LDraw type-1 part placement inside a reusable submodel."""

    __tablename__ = SUBMODEL_DATABASE_CONFIG["part_table"]

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    submodel_id = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{SUBMODEL_DATABASE_CONFIG['submodel_table']}.id"),
        nullable=False,
    )
    line_no = Column(Integer, nullable=False)
    color_code = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["color_code"]),
        nullable=False,
    )
    ldraw_part_num = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["ldraw_part_num"]),
        nullable=False,
    )

    pos_x = Column(Float, nullable=False)
    pos_y = Column(Float, nullable=False)
    pos_z = Column(Float, nullable=False)

    ori_11 = Column(Float, nullable=False)
    ori_12 = Column(Float, nullable=False)
    ori_13 = Column(Float, nullable=False)
    ori_21 = Column(Float, nullable=False)
    ori_22 = Column(Float, nullable=False)
    ori_23 = Column(Float, nullable=False)
    ori_31 = Column(Float, nullable=False)
    ori_32 = Column(Float, nullable=False)
    ori_33 = Column(Float, nullable=False)

    submodel = relationship("LDrawSubmodel", back_populates="parts")

    __table_args__ = (
        UniqueConstraint(
            "submodel_id",
            "line_no",
            name=SUBMODEL_DATABASE_CONFIG["constraints"]["part_line_unique"],
        ),
        Index(
            SUBMODEL_DATABASE_CONFIG["indexes"]["part_submodel"],
            "submodel_id",
        ),
        Index(
            SUBMODEL_DATABASE_CONFIG["indexes"]["part_ldraw_num"],
            "ldraw_part_num",
        ),
    )


class LDrawSubmodelConnector(Base):
    """Reusable connection point exposed by a submodel."""

    __tablename__ = SUBMODEL_DATABASE_CONFIG["connector_table"]

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    submodel_id = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{SUBMODEL_DATABASE_CONFIG['submodel_table']}.id"),
        nullable=False,
    )
    part_line_no = Column(Integer, nullable=False)
    connector_label = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["connector_label"]),
        nullable=False,
    )
    connector_kind = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["connector_kind"]),
        nullable=False,
    )
    normalized_connector_type = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["connector_type"]),
        nullable=False,
    )
    connector_gender = Column(
        String(SUBMODEL_DATABASE_CONFIG["string_lengths"]["connector_gender"]),
        nullable=False,
    )

    pos_x = Column(Float, nullable=False)
    pos_y = Column(Float, nullable=False)
    pos_z = Column(Float, nullable=False)

    ori_11 = Column(Float, nullable=False)
    ori_12 = Column(Float, nullable=False)
    ori_13 = Column(Float, nullable=False)
    ori_21 = Column(Float, nullable=False)
    ori_22 = Column(Float, nullable=False)
    ori_23 = Column(Float, nullable=False)
    ori_31 = Column(Float, nullable=False)
    ori_32 = Column(Float, nullable=False)
    ori_33 = Column(Float, nullable=False)
    metadata_json = Column(JSON, nullable=False)

    submodel = relationship("LDrawSubmodel", back_populates="connectors")

    __table_args__ = (
        UniqueConstraint(
            "submodel_id",
            "connector_label",
            name=SUBMODEL_DATABASE_CONFIG["constraints"]["connector_label_unique"],
        ),
        Index(
            SUBMODEL_DATABASE_CONFIG["indexes"]["connector_submodel"],
            "submodel_id",
        ),
        Index(
            SUBMODEL_DATABASE_CONFIG["indexes"]["connector_type"],
            "normalized_connector_type",
            "connector_gender",
        ),
    )


class FittingCandidateProfile(Base):
    """Unified recall profile for fitting candidates."""

    __tablename__ = FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["table"]

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    candidate_type = Column(
        String(FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["string_lengths"]["candidate_type"]),
        nullable=False,
    )
    candidate_id = Column(
        String(FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["string_lengths"]["candidate_id"]),
        nullable=False,
    )
    profile_key = Column(
        String(FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["string_lengths"]["profile_key"]),
        nullable=False,
    )
    profile_status = Column(
        String(FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["string_lengths"]["profile_status"]),
        nullable=False,
    )
    source_hash = Column(
        String(FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["string_lengths"]["source_hash"]),
        nullable=False,
    )
    shape_signature = Column(
        String(FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["string_lengths"]["shape_signature"]),
        nullable=False,
    )
    bbox_json = Column(JSON, nullable=False)
    logical_size_json = Column(JSON, nullable=False)
    width_stud = Column(Float, nullable=True)
    depth_stud = Column(Float, nullable=True)
    height_plate = Column(Float, nullable=True)
    is_sticker = Column(Boolean, nullable=False, default=False, server_default=false())
    normalized_type = Column(String(64), nullable=True)
    shape_profile_json = Column(JSON, nullable=False)
    appearance_tags_json = Column(JSON, nullable=False)
    color_summary_json = Column(JSON, nullable=True)
    connector_summary_json = Column(JSON, nullable=False)
    source_metadata_json = Column(JSON, nullable=False)
    profile_error_code = Column(String(160), nullable=True)
    profile_error_params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            'candidate_type',
            'candidate_id',
            'profile_key',
            name=FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["constraints"][
                "candidate_profile_unique"
            ],
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["type"],
            'candidate_type',
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["status"],
            'profile_status',
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["profile_key"],
            'profile_key',
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["signature"],
            'shape_signature',
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["dimensions"],
            'candidate_type',
            'profile_status',
            'height_plate',
            'width_stud',
            'depth_stud',
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["sticker"],
            'candidate_type',
            'is_sticker',
        ),
        Index(
            FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["normalized_type"],
            'candidate_type',
            'profile_status',
            'normalized_type',
        ),
    )


class ModelAsset(Base):
    """Persisted 3D model asset metadata."""
    __tablename__ = 'model_assets'

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    content_locale = Column(String(16), nullable=False)
    model_type = Column(String(64), nullable=False)
    source_type = Column(String(64), nullable=False)
    source_name = Column(Text, nullable=False)
    asset_path = Column(String(1024), nullable=False)
    preview_path = Column(String(1024), nullable=True)
    status = Column(String(64), nullable=False)
    columns = Column(Integer, nullable=True)
    rows = Column(Integer, nullable=True)
    min_elevation = Column(Float, nullable=True)
    max_elevation = Column(Float, nullable=True)
    valid_sample_count = Column(Integer, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_model_assets_type', 'model_type'),
        Index('idx_model_assets_created', 'created_at'),
        Index('idx_model_assets_status', 'status'),
    )


class ComponentArtifact(Base):
    """Immutable source or exchange artifact for the Component Repo."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["artifact_table"]

    id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    artifact_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["artifact_type"]),
        nullable=False,
    )
    original_filename = Column(Text, nullable=False)
    storage_provider = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["provider"]),
        nullable=False,
    )
    storage_bucket = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["bucket"]),
        nullable=False,
    )
    storage_key = Column(Text, nullable=False)
    storage_uri = Column(Text, nullable=False)
    sha256 = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["sha256"]),
        nullable=False,
    )
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["mime_type"]),
        nullable=False,
    )
    immutable = Column(Boolean, nullable=False, default=True)
    uploaded_by = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        nullable=False,
    )
    uploaded_at = Column(DateTime, nullable=False)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["artifact_type"],
            "artifact_type",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["artifact_sha"],
            "sha256",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["artifact_uploaded"],
            "uploaded_at",
        ),
        UniqueConstraint(
            "storage_provider",
            "storage_bucket",
            "storage_key",
            name="uq_component_artifact_storage_object",
        ),
    )


class ComponentUploadSession(Base):
    """Pending direct-to-storage upload session for Component Repo artifacts."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["upload_session_table"]

    id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    owner_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        nullable=False,
    )
    status = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]),
        nullable=False,
    )
    expected_uploads_json = Column(JSON, nullable=False)
    created_by = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        nullable=False,
    )
    created_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    failure_code = Column(String(160), nullable=True)
    failure_params_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["upload_session_owner"],
            "owner_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["upload_session_status"],
            "status",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["upload_session_created"],
            "created_at",
        ),
    )


class ComponentImport(Base):
    """One Component Repo upload and parse task."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["import_table"]

    id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    source_artifact_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['artifact_table']}.id"),
        nullable=False,
    )
    exchange_artifact_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['artifact_table']}.id"),
        nullable=True,
    )
    target_component_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        nullable=True,
    )
    base_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        nullable=True,
    )
    status = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]),
        nullable=False,
    )
    parser_version = Column(String(64), nullable=True)
    part_library_version = Column(String(128), nullable=True)
    created_by = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        nullable=False,
    )
    created_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    failure_code = Column(String(160), nullable=True)
    failure_params_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    source_artifact = relationship("ComponentArtifact", foreign_keys=[source_artifact_id])
    exchange_artifact = relationship("ComponentArtifact", foreign_keys=[exchange_artifact_id])

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["import_status"],
            "status",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["import_created"],
            "created_at",
        ),
    )


class ComponentSceneSnapshot(Base):
    """Parsed LDraw scene snapshot for a ComponentImport."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["scene_snapshot_table"]

    id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    import_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['import_table']}.id"),
        nullable=False,
    )
    schema = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["schema"]),
        nullable=False,
    )
    parser_version = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["parser_version"]),
        nullable=False,
    )
    root_model_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        nullable=True,
    )
    document_json = Column(JSON, nullable=False)
    bom_json = Column(JSON, nullable=False)
    parse_issues_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)

    import_job = relationship("ComponentImport")

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["snapshot_import"],
            "import_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["snapshot_created"],
            "created_at",
        ),
    )


class ComponentCandidate(Base):
    """Reviewable parsed component candidate."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["candidate_table"]

    id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    import_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['import_table']}.id"),
        nullable=False,
    )
    scene_snapshot_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['scene_snapshot_table']}.id"),
        nullable=False,
    )
    status = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]),
        nullable=False,
    )
    summary_json = Column(JSON, nullable=False)
    review_decisions_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    import_job = relationship("ComponentImport")
    scene_snapshot = relationship("ComponentSceneSnapshot")

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["candidate_import"],
            "import_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["candidate_status"],
            "status",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["candidate_created"],
            "created_at",
        ),
    )


class Component(Base):
    """Logical Component Repo item across immutable versions."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    name = Column(String(255), nullable=False)
    content_kind = Column(String(16), nullable=False)
    content_locale = Column(String(16), nullable=False)
    category = Column(String(128), nullable=True)
    status = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    current_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        nullable=True,
    )
    logical_width_stud = Column(Float, nullable=True)
    logical_depth_stud = Column(Float, nullable=True)
    logical_height_plate = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    tags_json = Column(JSON, nullable=False)
    metadata_json = Column(JSON, nullable=False)
    created_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        nullable=True,
    )

    translations = relationship(
        "ComponentTranslation",
        back_populates="component",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_status"],
            "status",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_deleted"],
            "deleted_at",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_category"],
            "category",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_logical_size"],
            "status",
            "logical_height_plate",
            "logical_width_stud",
            "logical_depth_stud",
        ),
    )


class ComponentTranslation(Base):
    """Reviewed localized content for an official Component Repo item."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_translation_table"]

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    component_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['component_table']}.id"),
        nullable=False,
    )
    locale = Column(String(16), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tags_json = Column(JSON, nullable=False)
    translation_status = Column(String(32), nullable=False)
    reviewed_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    component = relationship("Component", back_populates="translations")

    __table_args__ = (
        UniqueConstraint("component_id", "locale", name="uq_component_translation_locale"),
        Index(COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_translation_locale"], "locale"),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_translation_status"],
            "translation_status",
        ),
    )


class ComponentGroup(Base):
    """One user-owned node in the Component library grouping tree."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_group_table"]

    id = Column(String(36), primary_key=True)
    owner_id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    parent_group_id = Column(
        String(36),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['component_group_table']}.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    group_type = Column(String(16), nullable=False)
    name = Column(String(100), nullable=True)
    normalized_name = Column(String(100), nullable=True)
    content_locale = Column(String(16), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "group_type IN ('root', 'custom')",
            name="ck_component_groups_type",
        ),
        UniqueConstraint(
            "owner_id",
            "parent_group_id",
            "normalized_name",
            name="uq_component_groups_sibling_name",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_group_owner_parent_sort"],
            "owner_id",
            "parent_group_id",
            "sort_order",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_group_root_owner"],
            "owner_id",
            unique=True,
            postgresql_where=(group_type == "root"),
            sqlite_where=(group_type == "root"),
        ),
    )


class ComponentGroupMembership(Base):
    """Direct Component membership in one custom user group."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_group_membership_table"]

    group_id = Column(
        String(36),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['component_group_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    component_id = Column(
        String(36),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['component_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    added_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    added_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_group_membership_component"],
            "component_id",
        ),
    )


class ComponentSubscription(Base):
    """A user's active subscription to another user's Component."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_subscription_table"]

    user_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        primary_key=True,
    )
    component_id = Column(
        String(36),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['component_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    subscribed_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_subscription_component"],
            "component_id",
        ),
    )


class ComponentVersion(Base):
    """Draft or immutable Component Repo version."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_version_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    component_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['component_table']}.id"),
        nullable=False,
    )
    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['candidate_table']}.id"),
        nullable=False,
    )
    version = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    source_artifact_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['artifact_table']}.id"),
        nullable=False,
    )
    exchange_artifact_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['artifact_table']}.id"),
        nullable=True,
    )
    scene_snapshot_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['scene_snapshot_table']}.id"),
        nullable=False,
    )
    parser_version = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["parser_version"]),
        nullable=False,
    )
    part_library_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['part_library_version_table']}.id"),
        nullable=True,
    )
    validation_report_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        nullable=True,
    )
    interface_signature = Column(String(64), nullable=False)
    structure_hash = Column(String(64), nullable=False)
    geometry_hash = Column(String(64), nullable=False)
    preview_artifact_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['artifact_table']}.id"),
        nullable=True,
    )
    preview_status = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    preview_generator_version = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["parser_version"]),
        nullable=True,
    )
    preview_failure_code = Column(String(160), nullable=True)
    preview_failure_params_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=False)
    created_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    created_at = Column(DateTime, nullable=False)
    published_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]),
        nullable=True,
    )

    component = relationship("Component")
    component_candidate = relationship("ComponentCandidate")
    source_artifact = relationship("ComponentArtifact", foreign_keys=[source_artifact_id])
    exchange_artifact = relationship("ComponentArtifact", foreign_keys=[exchange_artifact_id])
    preview_artifact = relationship("ComponentArtifact", foreign_keys=[preview_artifact_id])
    scene_snapshot = relationship("ComponentSceneSnapshot")
    part_library_version = relationship("PartLibraryVersion")

    __table_args__ = (
        UniqueConstraint(
            "component_id",
            "version",
            "revision",
            name="uq_component_version_revision",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_version_component"],
            "component_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_version_status"],
            "status",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_version_deleted"],
            "deleted_at",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_version_preview_artifact"],
            "preview_artifact_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_version_preview_status"],
            "preview_status",
        ),
    )


class ComponentInterface(Base):
    """Confirmed external connector/interface exposed by a candidate."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["component_interface_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['candidate_table']}.id"),
        nullable=False,
    )
    world_connector_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    exposure = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    default_behavior = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["joint_type"]), nullable=False)
    source_connector_json = Column(JSON, nullable=False)
    mechanical_roles_json = Column(JSON, nullable=False)
    business_roles_json = Column(JSON, nullable=False)
    requirements_json = Column(JSON, nullable=False)
    review_status = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    created_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    component_candidate = relationship("ComponentCandidate")

    __table_args__ = (
        UniqueConstraint(
            "component_candidate_id",
            "world_connector_id",
            name="uq_component_interface_candidate_connector",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_interface_candidate"],
            "component_candidate_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["component_interface_status"],
            "review_status",
        ),
    )


class ComponentValidationReport(Base):
    """Validation result for a candidate or version."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["validation_report_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['candidate_table']}.id"),
        nullable=True,
    )
    component_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['component_version_table']}.id"),
        nullable=True,
    )
    validation_level = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    passed = Column(Boolean, nullable=False)
    checks_json = Column(JSON, nullable=False)
    issues_json = Column(JSON, nullable=False)
    validator_version = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False)

    component_candidate = relationship("ComponentCandidate")
    component_version = relationship("ComponentVersion", foreign_keys=[component_version_id])

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["validation_report_candidate"],
            "component_candidate_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["validation_report_version"],
            "component_version_id",
        ),
    )


class PartLibraryVersion(Base):
    """Frozen connector library snapshot metadata."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["part_library_version_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    source_table = Column(String(128), nullable=False)
    source_hash = Column(String(64), nullable=False)
    connector_count = Column(Integer, nullable=False)
    status = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    metadata_json = Column(JSON, nullable=False)
    created_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["part_library_status"],
            "status",
        ),
    )


class PartConnectorDefinition(Base):
    """Frozen connector definition copied from connector_instances for one part library version."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["part_connector_definition_table"]

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    part_library_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['part_library_version_table']}.id"),
        nullable=False,
    )
    source_connector_id = Column(BigInteger, nullable=False)
    ldraw_part_num = Column(String(128), nullable=False)
    connector_kind = Column(String(64), nullable=False)
    normalized_connector_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["connector_type"]),
        nullable=True,
    )
    connector_group = Column(String(128), nullable=True)
    connector_gender = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["connector_gender"]),
        nullable=True,
    )
    pos_x = Column(Float, nullable=False)
    pos_y = Column(Float, nullable=False)
    pos_z = Column(Float, nullable=False)
    ori_11 = Column(Float, nullable=False)
    ori_12 = Column(Float, nullable=False)
    ori_13 = Column(Float, nullable=False)
    ori_21 = Column(Float, nullable=False)
    ori_22 = Column(Float, nullable=False)
    ori_23 = Column(Float, nullable=False)
    ori_31 = Column(Float, nullable=False)
    ori_32 = Column(Float, nullable=False)
    ori_33 = Column(Float, nullable=False)
    direction_x = Column(Float, nullable=True)
    direction_y = Column(Float, nullable=True)
    direction_z = Column(Float, nullable=True)
    direction_label = Column(String(32), nullable=True)
    direction_group = Column(String(32), nullable=True)
    radius = Column(Float, nullable=True)
    length = Column(Float, nullable=True)
    caps = Column(String(32), nullable=True)
    center_flag = Column(Boolean, default=False)
    slide_flag = Column(Boolean, default=False)
    confidence = Column(Numeric(5, 4), default=1.0000)
    raw_params = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)

    part_library_version = relationship("PartLibraryVersion")

    __table_args__ = (
        UniqueConstraint(
            "part_library_version_id",
            "source_connector_id",
            name="uq_part_connector_definition_source",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["part_connector_definition_version"],
            "part_library_version_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["part_connector_definition_part"],
            "part_library_version_id",
            "ldraw_part_num",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["part_connector_definition_type"],
            "normalized_connector_type",
            "connector_gender",
        ),
    )


class ComponentConnectorAnalysis(Base):
    """Materialized connector-classification metadata for one candidate."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["connector_analysis_table"]

    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['candidate_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    part_library_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['part_library_version_table']}.id"
        ),
        nullable=False,
    )
    recognition_method = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["method"]),
        nullable=False,
    )
    recognition_version = Column(String(64), nullable=False)
    calculated_at = Column(DateTime, nullable=False)


class ComponentConnectorAnalysisItem(Base):
    """One classified world-space connector, stored without JSON."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["connector_analysis_item_table"]

    id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['connector_analysis_table']}.component_candidate_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    part_connector_definition_id = Column(
        BigInteger,
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['part_connector_definition_table']}.id"
        ),
        nullable=False,
    )
    world_connector_id = Column(String(255), nullable=False)
    part_instance_id = Column(String(255), nullable=False)
    part_ref = Column(String(128), nullable=False)
    connector_type = Column(String(64), nullable=True)
    connector_kind = Column(String(64), nullable=True)
    connector_gender = Column(String(16), nullable=True)
    direction_label = Column(String(32), nullable=True)
    direction_group = Column(String(32), nullable=True)
    state = Column(String(32), nullable=False)
    position_x = Column(Float, nullable=False)
    position_y = Column(Float, nullable=False)
    position_z = Column(Float, nullable=False)
    axis_x = Column(Float, nullable=False)
    axis_y = Column(Float, nullable=False)
    axis_z = Column(Float, nullable=False)
    matrix_11 = Column(Float, nullable=False)
    matrix_12 = Column(Float, nullable=False)
    matrix_13 = Column(Float, nullable=False)
    matrix_21 = Column(Float, nullable=False)
    matrix_22 = Column(Float, nullable=False)
    matrix_23 = Column(Float, nullable=False)
    matrix_31 = Column(Float, nullable=False)
    matrix_32 = Column(Float, nullable=False)
    matrix_33 = Column(Float, nullable=False)
    access_axis_x = Column(Float, nullable=False)
    access_axis_y = Column(Float, nullable=False)
    access_axis_z = Column(Float, nullable=False)
    external_interface_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        nullable=True,
    )
    eligibility_unoccupied = Column(Boolean, nullable=False)
    eligibility_supported_type = Column(Boolean, nullable=False)
    eligibility_outward_facing = Column(Boolean, nullable=False)
    eligibility_clearance_data_available = Column(Boolean, nullable=False)
    eligibility_clearance_available = Column(Boolean, nullable=False)
    outward_score = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "component_candidate_id",
            "world_connector_id",
            name="uq_component_connector_analysis_item_world",
        ),
        CheckConstraint(
            "state IN ('internal', 'external', 'blocked', 'unsupported', 'unresolved')",
            name="ck_component_connector_analysis_item_state",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"][
                "connector_analysis_item_candidate_state"
            ],
            "component_candidate_id",
            "state",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"][
                "connector_analysis_item_candidate_part"
            ],
            "component_candidate_id",
            "part_instance_id",
        ),
    )


class ComponentConnectorAnalysisPathNode(Base):
    """Ordered instance-path node for one analyzed connector."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["connector_analysis_path_table"]

    analysis_item_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['connector_analysis_item_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    ordinal = Column(Integer, primary_key=True)
    instance_id = Column(String(255), nullable=False)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"][
                "connector_analysis_path_instance"
            ],
            "instance_id",
        ),
    )


class ComponentConnectorAnalysisBlocker(Base):
    """Part instance obstructing one connector's mating corridor."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["connector_analysis_blocker_table"]

    analysis_item_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['connector_analysis_item_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    blocker_part_instance_id = Column(String(255), primary_key=True)

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"][
                "connector_analysis_blocker_part"
            ],
            "blocker_part_instance_id",
        ),
    )


class ComponentConnectorAnalysisRelation(Base):
    """Confirmed relation consuming one analyzed connector."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["connector_analysis_relation_table"]

    analysis_item_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['connector_analysis_item_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    assembly_relation_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(
            f"{COMPONENT_REPO_DATABASE_CONFIG['assembly_relation_table']}.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"][
                "connector_analysis_relation_relation"
            ],
            "assembly_relation_id",
        ),
    )


class ComponentRelationCandidate(Base):
    """Automatically detected, reviewable connection relation candidate."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["relation_candidate_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['candidate_table']}.id"),
        nullable=False,
    )
    part_library_version_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['part_library_version_table']}.id"),
        nullable=False,
    )
    endpoint_a_json = Column(JSON, nullable=False)
    endpoint_b_json = Column(JSON, nullable=False)
    connection_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["connection_type"]),
        nullable=False,
    )
    joint_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["joint_type"]),
        nullable=False,
    )
    position_residual = Column(Float, nullable=False)
    rotation_residual = Column(Float, nullable=False)
    verified_by_tolerance = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["status"]), nullable=False)
    detection_method = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["method"]),
        nullable=False,
    )
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    component_candidate = relationship("ComponentCandidate")
    part_library_version = relationship("PartLibraryVersion")

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["relation_candidate_component"],
            "component_candidate_id",
        ),
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["relation_candidate_status"],
            "status",
        ),
    )


class ComponentAssemblyRelation(Base):
    """Human-confirmed internal assembly relation."""

    __tablename__ = COMPONENT_REPO_DATABASE_CONFIG["assembly_relation_table"]

    id = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]), primary_key=True)
    component_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['candidate_table']}.id"),
        nullable=False,
    )
    relation_candidate_id = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{COMPONENT_REPO_DATABASE_CONFIG['relation_candidate_table']}.id"),
        nullable=False,
    )
    endpoint_a_json = Column(JSON, nullable=False)
    endpoint_b_json = Column(JSON, nullable=False)
    connection_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["connection_type"]),
        nullable=False,
    )
    joint_type = Column(
        String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["joint_type"]),
        nullable=False,
    )
    placement_json = Column(JSON, nullable=False)
    confirmed_by = Column(String(COMPONENT_REPO_DATABASE_CONFIG["string_lengths"]["user"]), nullable=False)
    confirmed_at = Column(DateTime, nullable=False)

    component_candidate = relationship("ComponentCandidate")
    relation_candidate = relationship("ComponentRelationCandidate")

    __table_args__ = (
        Index(
            COMPONENT_REPO_DATABASE_CONFIG["indexes"]["assembly_relation_candidate"],
            "component_candidate_id",
        ),
        UniqueConstraint(
            "relation_candidate_id",
            name="uq_component_assembly_relation_candidate",
        ),
    )


class ModelFittingJob(Base):
    """Persistent fitting analysis job for one uploaded mesh model."""

    __tablename__ = MODEL_FITTING_DATABASE_CONFIG["job_table"]

    id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    source_model_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{ModelAsset.__tablename__}.id"),
        nullable=False,
    )
    name = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["name"]),
        nullable=False,
    )
    schema = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["schema"]),
        nullable=False,
    )
    status = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["status"]),
        nullable=False,
    )
    settings_json = Column(JSON, nullable=False)
    target_analysis_json = Column(JSON, nullable=False)
    locale = Column(String(16), nullable=False)
    timezone = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    error_code = Column(String(160), nullable=True)
    error_params_json = Column(JSON, nullable=True)

    source_model = relationship("ModelAsset")
    target_blocks = relationship(
        "ModelFittingTargetBlock",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    solutions = relationship(
        "ModelFittingSolution",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["job_model"],
            "source_model_id",
        ),
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["job_status"],
            "status",
        ),
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["job_created"],
            "created_at",
        ),
    )


class ModelFittingTargetBlock(Base):
    """Target component generated from a fitting job."""

    __tablename__ = MODEL_FITTING_DATABASE_CONFIG["target_block_table"]

    id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    job_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{MODEL_FITTING_DATABASE_CONFIG['job_table']}.id"),
        nullable=False,
    )
    schema = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["schema"]),
        nullable=False,
    )
    block_type = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["block_type"]),
        nullable=False,
    )
    name = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["name"]),
        nullable=False,
    )
    bbox_json = Column(JSON, nullable=False)
    profile_json = Column(JSON, nullable=False)
    recall_query_json = Column(JSON, nullable=False)
    candidate_summary_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    job = relationship("ModelFittingJob", back_populates="target_blocks")
    placements = relationship("ModelFittingSolutionPlacement", back_populates="target_block")

    __table_args__ = (
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["block_job"],
            "job_id",
        ),
    )


class ModelFittingSolution(Base):
    """Editable fitting solution for a job."""

    __tablename__ = MODEL_FITTING_DATABASE_CONFIG["solution_table"]

    id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    job_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{MODEL_FITTING_DATABASE_CONFIG['job_table']}.id"),
        nullable=False,
    )
    schema = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["schema"]),
        nullable=False,
    )
    status = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["status"]),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    metrics_json = Column(JSON, nullable=False)
    bom_json = Column(JSON, nullable=False)
    ldraw_content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    job = relationship("ModelFittingJob", back_populates="solutions")
    placements = relationship(
        "ModelFittingSolutionPlacement",
        back_populates="solution",
        cascade="all, delete-orphan",
    )
    edits = relationship(
        "ModelFittingSolutionEdit",
        back_populates="solution",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["solution_job"],
            "job_id",
        ),
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["solution_status"],
            "status",
        ),
    )


class ModelFittingSolutionPlacement(Base):
    """Editable part or submodel placement inside a fitting solution."""

    __tablename__ = MODEL_FITTING_DATABASE_CONFIG["placement_table"]

    id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    solution_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{MODEL_FITTING_DATABASE_CONFIG['solution_table']}.id"),
        nullable=False,
    )
    target_block_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{MODEL_FITTING_DATABASE_CONFIG['target_block_table']}.id"),
        nullable=False,
    )
    schema = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["schema"]),
        nullable=False,
    )
    candidate_type = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["candidate_type"]),
        nullable=False,
    )
    candidate_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["candidate_id"]),
        nullable=False,
    )
    color_code = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["color_code"]),
        nullable=True,
    )
    position_json = Column(JSON, nullable=False)
    orientation_json = Column(JSON, nullable=False)
    bbox_json = Column(JSON, nullable=False)
    score = Column(Float, nullable=False)
    score_reasons_json = Column(JSON, nullable=False)
    locked = Column(Boolean, nullable=False)
    source = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["source"]),
        nullable=False,
    )
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    solution = relationship("ModelFittingSolution", back_populates="placements")
    target_block = relationship("ModelFittingTargetBlock", back_populates="placements")

    __table_args__ = (
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["placement_solution"],
            "solution_id",
        ),
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["placement_block"],
            "target_block_id",
        ),
    )


class ModelFittingSolutionEdit(Base):
    """Audit entry for one editable solution change."""

    __tablename__ = MODEL_FITTING_DATABASE_CONFIG["edit_table"]

    id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        primary_key=True,
    )
    solution_id = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["id"]),
        ForeignKey(f"{MODEL_FITTING_DATABASE_CONFIG['solution_table']}.id"),
        nullable=False,
    )
    schema = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["schema"]),
        nullable=False,
    )
    edit_type = Column(
        String(MODEL_FITTING_DATABASE_CONFIG["string_lengths"]["edit_type"]),
        nullable=False,
    )
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)

    solution = relationship("ModelFittingSolution", back_populates="edits")

    __table_args__ = (
        Index(
            MODEL_FITTING_DATABASE_CONFIG["indexes"]["edit_solution"],
            "solution_id",
        ),
    )


class PixelArtProject(Base):
    """Persisted quantized pixel art project."""
    __tablename__ = 'pixel_art_projects'

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    content_locale = Column(String(16), nullable=False)
    schema = Column(String(64), nullable=False)
    source_type = Column(String(64), nullable=False)
    source_name = Column(String(255), nullable=False)
    source_content_type = Column(String(128), nullable=False)
    preview_content_type = Column(String(128), nullable=False)
    preview_image = Column(LargeBinary().with_variant(LONGBLOB, "mysql"), nullable=False)
    status = Column(String(64), nullable=False)
    grid_width = Column(Integer, nullable=False)
    grid_height = Column(Integer, nullable=False)
    color_count = Column(Integer, nullable=False)
    crop_json = Column(JSON, nullable=False)
    palette_json = Column(JSON, nullable=False)
    pixel_matrix_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_pixel_art_projects_created', 'created_at'),
        Index('idx_pixel_art_projects_status', 'status'),
    )
