# 3D 模型拟合与零件召回路线图

## 目标

构建一套面向 3D 模型拟合的零件与 submodel 召回体系。核心目标是在每次拟合前，通过尺寸、形状、外观、连接点和复用组件信息缩小候选集合，减少枚举数量，同时保留足够好的拟合质量。

## 当前基础

项目已经具备第一阶段召回所需的核心数据：

- `ldraw_parts`：LDraw 零件编号、名称、类别、文件路径。
- `ldraw_part_geometry`：bbox、LDU/mm 尺寸、逻辑 stud 宽深高、顶点数、面数、解析状态。
- `ldraw_files` 与 `ldraw_file_references`：LDraw 文件和 type-1 引用关系，可继续支撑几何解析。
- `connector_instances`：连接点类型、方向、位置、性别、尺寸和置信度。
- `ldraw_submodels`、`ldraw_submodel_parts`、`ldraw_submodel_connectors`：可复用组件的 LDraw 描述、组成零件、颜色比例、备注和连接点。

当前不足：

- 零件外观信息尚未系统化，缺少形状类别、表面特征、孔洞、曲面、斜面、可见面等可召回字段。
- `PartSurfaceProfile` 已能表达表面高度、碰撞区间、接触面和顶部连接 mask，但主要是运行时计算，没有作为全量预处理索引落库。
- 只有 bbox 和逻辑尺寸无法区分外形相似但用途不同的零件，例如普通 plate、tile、round plate、modified plate。
- submodel 已有存储基础，但还没有形状轮廓、bbox、外观摘要和复用召回索引。

## 总体架构

### 1. 候选库层

统一把可参与拟合的对象分为两类：

- part：单个 LDraw 零件。
- submodel：由多个 part 拼接而成的可复用组件。

两类对象都需要形成统一的候选摘要，供拟合前召回：

- 对象类型：part 或 submodel。
- 对象 ID：LDraw part number 或 submodel ID。
- 尺寸摘要：bbox、逻辑 stud 尺寸、体素尺寸。
- 形状摘要：surface profile、collision profile、shape signature。
- 外观摘要：颜色比例、表面类型、特征标签。
- 拼接摘要：连接点数量、类型、方向、空间位置。
- 质量状态：解析状态、预处理状态、错误信息、来源 hash。

### 2. 预处理层

预处理负责把 LDraw 或 submodel 原始描述转成可快速召回的数据：

- 解析 LDraw mesh。
- 生成 bbox 与逻辑尺寸。
- 采样表面高度和碰撞区间。
- 生成体素占用网格。
- 生成方向归一化后的旋转变体。
- 提取连接点摘要。
- 生成外观标签和颜色比例。
- 生成 shape signature，用于快速相似召回。

### 3. 召回层

召回按从便宜到昂贵的顺序分阶段执行：

1. 尺寸过滤：bbox、逻辑尺寸、体素尺寸、类别。
2. 连接过滤：connector type、gender、方向、数量。
3. 外观过滤：颜色比例、表面类型、特征标签。
4. 形状过滤：surface profile、voxel signature、normal histogram。
5. 精排：实际局部拟合评分、碰撞检测、连接约束评分。

### 4. 拟合层

拟合层不直接枚举全量零件，而是对目标 3D 模型分块后，向召回层请求候选：

- 对目标模型生成局部块。
- 为每个块计算目标 bbox、体素、表面、颜色和连接需求。
- 调用召回 API 获取候选 part/submodel。
- 组合候选，做约束求解或启发式搜索。
- 输出 LDraw 组合方案、BOM、可复用 submodel 建议。

## 数据路线图

### 阶段 1：补齐可追踪候选摘要

目标：让 part 和 submodel 都能进入统一候选池。

任务：

- 建立 `fitting_candidate_profiles` 或等价表，存储统一候选摘要。
- 为 part 生成候选摘要，来源为 `ldraw_parts`、`ldraw_part_geometry`、`connector_instances`。
- 为 submodel 生成候选摘要，来源为 submodel parts、连接点和 LDraw 内容。
- 增加预处理状态字段：pending、ready、failed。
- 增加 source hash，避免重复处理未变化对象。

完成标准：

- 能按对象类型、尺寸、类别、连接类型查询候选。
- part 和 submodel 使用同一个召回入口。
- 对缺失或失败的 profile 有明确状态和错误信息。

### 阶段 2：持久化 shape profile

目标：避免每次拟合实时解析 mesh。

任务：

- 建立 `ldraw_part_shape_profiles`。
- 持久化 surface height profile。
- 持久化 collision intervals。
- 持久化 bottom contact mask。
- 持久化 top connection mask。
- 持久化 voxel occupancy。
- 持久化 normal histogram。
- 为常用旋转生成 rotation variants。

完成标准：

- 给定 part ID，可以直接从数据库读取 shape profile。
- DEM 和 3D fitting 不再重复解析同一零件 mesh。
- profile 生成脚本可增量运行。

### 阶段 3：外观与语义标签

目标：支持“按外观控制召回”。

任务：

- 从 LDraw 名称、类别、几何和连接点生成 appearance tags。
- 标记 flat、slope、curved、round、technic、clip、hinge、hole、transparent、printed、sticker、pattern、assembly 等特征。
- 为 submodel 保存颜色百分比和特征备注的结构化摘要。
- 建立标签质量检查脚本。

完成标准：

- 可以按外观标签召回或排除候选。
- printed/sticker/pattern 类零件不会默认污染普通结构件召回。
- submodel 的备注不只作为文本保存，也能转成可过滤标签。

### 阶段 4：目标 3D 模型分块与查询

目标：把任意 3D 模型转成可查询的局部拟合需求。

任务：

- 定义目标模型标准化坐标系。
- 将模型体素化或切成局部 block。
- 为每个 block 计算 bbox、surface profile、voxel occupancy、normal histogram、颜色比例。
- 生成 fitting query。
- 实现候选召回 API。

完成标准：

- 输入一个目标 block，能返回候选 part/submodel 列表。
- 返回结果带召回原因和排序分数。
- 查询耗时可被记录和比较。

### 阶段 5：拟合评分与组合搜索

目标：从候选召回进入可用的拼装方案。

任务：

- 定义单候选评分：尺寸误差、体素重叠、表面误差、颜色误差、连接匹配。
- 定义组合评分：覆盖率、碰撞、连接稳定性、零件数量、颜色一致性。
- 实现局部贪心或 beam search。
- 对 submodel 设置复用奖励，避免重复枚举相同结构。
- 输出 LDraw 和 BOM。

完成标准：

- 能对小型 3D 模型生成可检查的 LDraw 初版方案。
- 搜索过程可解释：每个候选为什么被选中或排除。
- 候选数量和耗时可追踪。

## 推荐表设计方向

### `ldraw_part_shape_profiles`

建议字段：

- `ldraw_part_id`
- `profile_status`
- `source_hash`
- `bbox_json`
- `logical_size_json`
- `surface_profile_json`
- `collision_profile_json`
- `voxel_profile_json`
- `normal_histogram_json`
- `connection_mask_json`
- `rotation_variants_json`
- `profile_error`

### `fitting_candidate_profiles`

建议字段：

- `candidate_type`
- `candidate_id`
- `profile_status`
- `bbox_json`
- `logical_size_json`
- `shape_signature`
- `appearance_tags_json`
- `color_summary_json`
- `connector_summary_json`
- `source_hash`
- `profile_error`

### `fitting_query_logs`

建议字段：

- `query_id`
- `target_profile_json`
- `filter_summary_json`
- `candidate_count_before`
- `candidate_count_after`
- `duration_ms`
- `selected_candidates_json`

## 召回策略

### 第一层：尺寸硬过滤

- category
- logical width/depth/height
- bbox width/height/depth
- 允许旋转后的 bbox 匹配
- 最小/最大体积

目的：把候选从全量零件压到较小集合。

### 第二层：连接硬过滤

- connector type
- connector gender
- connector direction group
- connector count
- top/bottom contact mask

目的：避免召回无法拼接的候选。

### 第三层：外观软过滤

- color ratio
- flat/slope/curved/round
- technic hole/clip/hinge
- printed/sticker/pattern 排除
- submodel remarks tags

目的：控制候选视觉和用途。

### 第四层：形状相似排序

- voxel IoU
- surface height error
- normal histogram distance
- collision interval compatibility
- bbox residual

目的：把“尺寸相近”排序成“形状更像”。

## 里程碑

### M1：候选摘要可查询

- part 与 submodel 进入统一候选池。
- 支持按尺寸、类别、连接点召回。
- 有基础测试和统计脚本。

### M2：shape profile 落库

- surface profile 不再只运行时计算。
- 常用零件 profile 可批量生成。
- 查询能直接使用 shape signature。

### M3：外观标签可用

- 支持按外观过滤。
- 支持排除 printed、sticker、pattern、assembly。
- submodel 颜色比例和备注进入召回摘要。

### M4：目标模型 block 查询

- 目标 3D 模型可被分块。
- 每个 block 可生成 fitting query。
- API 返回候选列表和召回原因。

### M5：初版自动拟合

- 小模型可生成 LDraw 方案。
- 输出 BOM。
- 能记录候选数量、耗时、评分和失败原因。

## 验证指标

每个阶段都要记录以下指标：

- 候选库总量。
- profile ready 数量。
- profile failed 数量。
- 单次查询候选数量。
- 单次查询耗时。
- 最终拟合覆盖率。
- 碰撞数量。
- 未连接或弱连接数量。
- 平均零件数。
- submodel 复用次数。

## 进度记录

### 2026-06-27：M1 数据覆盖率基线

已完成近期任务 1：统计当前 `ldraw_part_geometry`、`connector_instances` 的覆盖率和 NULL 率。

统计结果：

- `ldraw_parts`：24,214 个零件。
- `ldraw_part_geometry`：24,214 行，覆盖 24,214 个零件，零件几何覆盖率 100.00%。
- `ldraw_part_geometry.geometry_status`：`parsed` 24,210 行，`skipped` 4 行，解析成功率 99.98%。
- bbox 字段缺失：4 行，缺失率 0.02%。
- logical size 字段缺失：15,986 行，缺失率 66.02%；可直接用逻辑 stud 尺寸召回的零件为 8,228 个。
- `connector_instances`：29,853 个连接点实例。
- 有连接点的零件：3,828 个，占全部 LDraw 零件 15.81%。
- connector type、gender、direction 字段缺失：0 行。
- 连接点类型分布前几项：`anti_stud` 23,748，`cyl_unknown` 3,164，`technic_pin` 1,135，`technic_pin_hole` 896，`stud` 492，`axle_hole` 309，`axle` 109。

判断：

- 尺寸召回第一层可以直接使用 bbox，当前数据覆盖已经足够。
- 逻辑尺寸召回只能覆盖约三分之一零件，需要后续补齐或把 bbox 作为默认尺寸入口。
- 连接点字段质量较好，但覆盖零件数量有限；后续 fitting candidate profile 需要同时支持“有连接点强过滤”和“无连接点降级召回”。
- 下一步应进入任务 2：设计并实现 `ldraw_part_shape_profiles` 表，把运行时 `PartSurfaceProfile` 预处理结果持久化。

### 2026-06-27：M2 shape profile 表与样本持久化

已完成近期任务 2：设计并实现 `ldraw_part_shape_profiles` 表。

新增内容：

- 配置文件：`backend/config/part_shape_profile.json`。
- 配置入口：`backend/src/config/part_shape_profile_config.py`。
- 数据模型：`LDrawPartShapeProfile`，表名 `ldraw_part_shape_profiles`。
- 服务层：`backend/src/services/part_shape_profile_service.py`。
- 批处理入口：`backend/src/tools/build_part_shape_profiles.py`。
- 建表接入：`backend/src/tools/create_ldraw_tables.py`。
- 单元测试：`backend/tests/test_part_shape_profile_service.py`。

当前 profile 持久化内容：

- `profile_key`
- `samples_per_stud_axis`
- `profile_status`
- `source_hash`
- `bbox_json`
- `logical_size_json`
- `surface_profile_json`
- `collision_profile_json`
- `connection_mask_json`
- `profile_error`

验证结果：

- 单元测试通过：`python -m unittest tests.test_part_shape_profile_service tests.test_ldraw_surface_profile tests.test_submodel_service`。
- 编译检查通过：`python -m compileall src tests\test_part_shape_profile_service.py`。
- 真实数据库样本构建通过：`python src\tools\build_part_shape_profiles.py --part 3024.dat --part 3020.dat`。
- 样本构建结果：ready 2，failed 0，total 2。
- 当前 `ldraw_part_shape_profiles` 状态分布：`ready=2`。

判断：

- `PartSurfaceProfile` 已经可以从运行时对象持久化到数据库，任务 3 的技术链路已打通。
- 当前只做了 2 个样本零件验证，全量或分批生成还未执行。
- 下一步应把任务 3 扩展为可控批处理：先跑常用 Plate/Brick/Slope 小集合，再扩大到全量，并记录 ready/failed 覆盖率。

### 2026-06-27：M3 Plate/Brick/Slope pilot 批处理

已推进近期任务 3：把现有 `PartSurfaceProfile` 预处理结果持久化。

新增控制能力：

- `build_part_shape_profiles.py` 支持 `--category`，可按 LDraw category 分批。
- `build_part_shape_profiles.py` 支持 `--pilot-categories`，使用配置中的 `Plate`、`Brick`、`Slope` 小集合。
- `build_part_shape_profiles.py` 默认只处理尚未存在 shape profile 的零件。
- `build_part_shape_profiles.py` 支持 `--include-existing`，需要重建时才覆盖已有 profile。

本次 pilot：

- 命令：`python src\tools\build_part_shape_profiles.py --pilot-categories --limit 25`
- 处理数量：25。
- ready：24。
- failed：1。
- 当前累计状态：`ready=26`，`failed=1`。
- 失败样本：`60801.dat`，原因是 depth 未对齐 stud grid。

判断：

- 分批生成链路可用，失败 profile 能被持久化并保留原因。
- 默认 missing-only 行为可避免重复处理已完成 profile。
- 任务 3 仍在进行中；下一步应继续扩大 pilot 批次，并统计 Plate/Brick/Slope 的 ready/failed 覆盖率。

### 2026-06-27：M3 扩大 pilot 到 100 件

继续推进近期任务 3，扩大 `Plate`、`Brick`、`Slope` 的缺失 profile 批处理。

新增控制与追踪能力：

- 新增统计工具：`backend/src/tools/summarize_part_shape_profiles.py`。
- 统计工具输出 profile 状态分布、按 category 的 total/profiled/ready/failed/missing，以及失败样本。
- 为统计聚合补充单元测试，避免 ready/failed 覆盖率误报。

本次扩批：

- 命令：`python src\tools\build_part_shape_profiles.py --pilot-categories --limit 100`
- 处理数量：100。
- ready：89。
- failed：11。
- 当前累计状态：`ready=115`，`failed=12`。

Plate/Brick/Slope 覆盖率：

- `Brick`：total 1,320，profiled 78，ready 73，failed 5，missing 1,242。
- `Plate`：total 540，profiled 23，ready 17，failed 6，missing 517。
- `Slope`：total 862，profiled 26，ready 25，failed 1，missing 836。

失败类型：

- 当前失败主要来自非标准 stud 网格尺寸：width 或 depth 未对齐 stud grid。
- 代表样本包括 `3005d07.dat`、`60801.dat`、`17514.dat`、`47904.dat`。

验证结果：

- 单元测试通过：`python -m unittest tests.test_part_shape_profile_service tests.test_ldraw_surface_profile tests.test_submodel_service`。
- 编译检查通过：`python -m compileall src tests\test_part_shape_profile_service.py`。

判断：

- 分批生成和覆盖率追踪已经可用。
- 失败原因集中，后续需要决定非标准尺寸零件是降级 profile、单独标记，还是排除出初期 fitting candidate。
- 下一步可以继续扩大缺失 profile 批次，或先把 failed 原因分类写成结构化字段。

### 2026-06-27：M3 failed profile 结构化分类

已采纳策略：非标准 stud 网格尺寸零件不降级生成初期 shape profile，保持 `failed` 状态，并结构化标记为 `non_grid_dimension`。初期 fitting candidate 默认排除这类对象，后续如果需要支持特殊/装饰/非标准零件，再单独设计降级 profile。

新增内容：

- `ldraw_part_shape_profiles.profile_error_type` 字段。
- `part_shape_profile.json` 中新增 `profile_error_types` 配置。
- 当前错误类型：
  - `non_grid_dimension`：width 或 depth 未对齐 stud grid，初期候选策略为 `exclude`。
  - `mesh_parse_error`：LDraw 文件或引用解析失败，初期候选策略为 `exclude`。
  - `empty_mesh`：没有可用 mesh，初期候选策略为 `exclude`。
  - `unknown`：未匹配到已知类型，初期按失败对象处理。
- `part_shape_profile_service.py` 新增错误分类与回填逻辑。
- `summarize_part_shape_profiles.py` 新增 `errorTypes` 汇总与失败样本 `errorType` 输出。
- `create_ldraw_tables.py` 支持给已有表补 `profile_error_type` 列。

数据库更新：

- 已执行补列：`ldraw_part_shape_profiles.profile_error_type`。
- 已回填已有 failed profile：12 条。
- 当前状态：`ready=115`，`failed=12`。
- 当前错误类型分布：`non_grid_dimension=12`。

判断：

- 初期 fitting candidate 应只使用 `profile_status=ready` 的对象。
- `profile_status=failed` 且 `profile_error_type=non_grid_dimension` 的对象先排除，不参与第一版自动拟合。
- 下一步如果继续扩批，应持续观察 `errorTypes` 分布；如果 `non_grid_dimension` 占比过高，再决定是否新增 non-grid 降级 profile。

### 2026-06-27：M4 统一 fitting candidate profile 第一版

已完成近期任务 4：设计统一的 fitting candidate profile。并推进近期任务 5：为 part 生成第一版 candidate profile。

新增内容：

- 配置文件：`backend/config/fitting_candidate_profile.json`。
- 配置入口：`backend/src/config/fitting_candidate_profile_config.py`。
- 数据模型：`FittingCandidateProfile`，表名 `fitting_candidate_profiles`。
- 服务层：`backend/src/services/fitting_candidate_profile_service.py`。
- 批处理入口：`backend/src/tools/build_fitting_candidate_profiles.py`。
- 建表接入：`backend/src/tools/create_ldraw_tables.py`。
- 单元测试：`backend/tests/test_fitting_candidate_profile_service.py`。

第一版 candidate profile 内容：

- `candidate_type`
- `candidate_id`
- `profile_key`
- `profile_status`
- `source_hash`
- `shape_signature`
- `bbox_json`
- `logical_size_json`
- `shape_profile_json`
- `appearance_tags_json`
- `color_summary_json`
- `connector_summary_json`
- `source_metadata_json`
- `profile_error`

当前策略：

- 第一版只生成 part candidate。
- 只从 `LDrawPartShapeProfile.profile_status=ready` 的 shape profile 生成 candidate。
- `profile_status=failed`、`profile_error_type=non_grid_dimension` 的对象不会进入第一版 fitting candidate。
- connector 信息以摘要形式写入 `connector_summary_json`，支持有连接点强过滤，也允许无连接点对象以 `totalCount=0` 进入候选池。

真实数据库执行：

- 已创建 `fitting_candidate_profiles` 表。
- 已执行：`python src\tools\build_fitting_candidate_profiles.py --limit 50`。
- 生成结果：ready 50，failed 0，total 50。
- 当前 candidate 状态分布：`part ready 50`。

验证结果：

- 单元测试通过：`python -m unittest tests.test_fitting_candidate_profile_service tests.test_part_shape_profile_service tests.test_ldraw_surface_profile tests.test_submodel_service`。
- 编译检查通过：`python -m compileall src tests\test_fitting_candidate_profile_service.py tests\test_part_shape_profile_service.py`。

判断：

- part 侧的统一 candidate profile 已经可以生成。
- 下一步可以继续扩大 part candidate 批次，或进入任务 6：为 submodel 生成第一版 candidate profile。
- submodel candidate 需要先从 `ldraw_submodels`、`ldraw_submodel_parts`、`ldraw_submodel_connectors` 汇总 bbox、颜色比例、备注标签和连接点摘要。

### 2026-06-27：M4 submodel candidate profile 第一版

已完成近期任务 6：为 submodel 生成第一版 candidate profile。

新增内容：

- `fitting_candidate_profile.json` 增加 submodel signature、bbox 汇总参数、坐标轴、orientation 矩阵和 submodel JSON 字段配置。
- `fitting_candidate_profile_config.py` 要求 `geometry` 配置必须存在，缺失时启动阶段直接失败。
- `fitting_candidate_profile_service.py` 增加 `save_submodel_fitting_candidate_profile`，从 `ldraw_submodels`、`ldraw_submodel_parts`、`ldraw_submodel_connectors` 汇总候选摘要。
- `build_fitting_candidate_profiles.py` 增加 `--candidate-type submodel` 与 `--submodel` 参数，part 和 submodel 共用同一批处理入口。
- `test_fitting_candidate_profile_service.py` 增加 submodel candidate 生成测试与 missing-only loader 测试。

第一版 submodel candidate profile 内容：

- bbox：基于每个 submodel part 的 `ldraw_part_geometry` bbox，按 LDraw type-1 position 和 orientation 变换 8 个角点后求整体包围盒。
- logical size：由整体 bbox 换算 `widthStud`、`depthStud`、`heightPlate`。
- shape profile：保存组成零件行号、颜色、part 编号、局部位置、局部 orientation 和 part bbox。
- appearance tags：保存 submodel `name` 与 `remarks`。
- color summary：直接使用 submodel 的颜色百分比。
- connector summary：按 connector type/gender 聚合数量，并保留 submodel connector 的 part line、label、位置、orientation 和 metadata。
- source metadata：保存 partCount、connectorCount 和 submodel 更新时间。
- source hash：由 submodel LDraw 内容、颜色百分比、备注和组成零件摘要生成。

当前策略：

- submodel candidate 不做完整几何融合，只做召回阶段需要的整体 bbox、组成零件、颜色、备注和连接点摘要。
- 完整 mesh/voxel union 留到后续精排或拟合评分阶段，避免在召回预处理里引入高成本布尔几何和重复缓存。
- 若 submodel 引用的 part 缺少 `ldraw_part_geometry`，当前批次会明确失败，不生成降级 profile。

真实数据库执行：

- 已执行：`python src\tools\create_ldraw_tables.py`。
- 已执行：`python src\tools\build_fitting_candidate_profiles.py --candidate-type submodel --limit 50`。
- 生成结果：ready 0，failed 0，total 0。
- 判断：当前数据库没有待处理的 submodel 行，代码路径已可用，但需要先录入或导入真实 submodel 数据后才能生成真实 submodel candidate。

验证结果：

- 单元测试通过：`python -m unittest tests.test_fitting_candidate_profile_service tests.test_part_shape_profile_service tests.test_ldraw_surface_profile tests.test_submodel_service`。
- 编译检查通过：`python -m compileall src tests\test_fitting_candidate_profile_service.py tests\test_part_shape_profile_service.py`。

### 2026-06-28：submodel candidate profile 失败追踪与组成摘要

继续完善 submodel candidate profile。

新增内容：

- submodel candidate 生成失败时写入 `fitting_candidate_profiles`，状态为 `failed`，并保留 `profile_error`。
- 当前失败覆盖：submodel 没有 parts、submodel 引用的 part 缺少 `ldraw_part_geometry`。
- failed submodel profile 保留 submodel name、remarks、颜色比例、连接点摘要、组成零件 placement 和 source metadata，便于后续排查与重试。
- ready submodel profile 的 `source_metadata_json` 增加 `partSummary`，包含 `byPart`、`byColor`、`byCategory` 三类聚合。
- `build_fitting_candidate_profiles.py` 改为按返回的 `profileStatus` 统计 ready/failed，不再把所有未抛错的 submodel profile 都算作 ready。
- submodel 坐标、position 字段、bbox model 字段、bbox 维度映射继续收敛到 `fitting_candidate_profile.json`。

当前策略：

- ready submodel 用整体 bbox、logical size、part summary、color summary 和 connector summary 参与召回。
- failed submodel 不参与第一版召回，但会留在同一张 candidate profile 表里追踪失败原因。
- 如果后续补齐缺失零件几何，需要用 `--include-existing` 重建对应 submodel candidate。

真实数据库执行：

- 已执行：`python src\tools\create_ldraw_tables.py`。
- 已执行：`python src\tools\build_fitting_candidate_profiles.py --candidate-type submodel --limit 50`。
- 生成结果：ready 0，failed 0，total 0。
- 判断：当前真实数据库仍没有待处理的 submodel 行。

验证结果：

- 单元测试通过：`python -m unittest tests.test_fitting_candidate_profile_service tests.test_part_shape_profile_service tests.test_ldraw_surface_profile tests.test_submodel_service`。
- 编译检查通过：`python -m compileall src tests\test_fitting_candidate_profile_service.py tests\test_part_shape_profile_service.py`。

### 2026-06-28：M4 fitting candidate 召回 API 第一版

已完成近期任务 7 的第一版：实现按尺寸、连接点、类别、颜色和不规则零件降级策略的候选召回 API。

新增内容：

- 新增配置：`backend/config/fitting_candidate_recall.json`。
- 新增配置入口：`backend/src/config/fitting_candidate_recall_config.py`。
- 新增 schema：`backend/src/api/schemas/fitting_candidate_recall.py`。
- 新增 route：`backend/src/api/routes/fitting_candidate_recall.py`。
- 新增 service：`backend/src/services/fitting_candidate_recall_service.py`。
- `main.py` 接入 `/api/fitting/candidates/recall`，并在应用启动时确保 shape profile 与 candidate profile 表存在。
- 新增测试：`backend/tests/test_fitting_candidate_recall_service.py`。

第一版请求能力：

- `candidateTypes`：限制 `part` 或 `submodel`。
- `profileStatuses`：限制 `ready` 或 `failed`。
- `bbox`：按 `widthLdu`、`heightLdu`、`depthLdu` 和 `toleranceLdu` 过滤。
- `logicalSize`：按 `widthStud`、`depthStud`、`heightPlate` 和 `tolerance` 过滤。
- `connectors`：按 connector type、gender、minCount 过滤。
- `categories`：part 使用 `appearance_tags_json.category`，submodel 使用 `source_metadata_json.partSummary.byCategory`。
- `colorCodes`：使用 submodel 的 `color_summary_json`。
- `includeIrregular`：是否加入 failed shape profile 的不规则零件降级召回。
- `limit`：限制返回数量。

不规则零件策略：

- 不把 failed shape profile 直接升级为 ready candidate。
- 默认不召回 failed profile，避免污染正常拟合候选。
- 请求 `includeIrregular=true` 时，从 `ldraw_part_shape_profiles` 中读取 `profile_status=failed` 且 `profile_error_type=non_grid_dimension` 的零件。
- 不规则零件使用 `ldraw_part_geometry` 的 bbox、logical size 和 category 做宽松召回，返回时明确带 `profileError`、`profileErrorType` 和 `irregular_failed_shape_profile` 原因。
- 这类候选在评分上有 penalty，后续只适合进入人工检查、特殊装饰件、非标准形状补充或精排阶段单独处理。

真实数据库执行：

- 已验证 route 已注册：`/api/fitting/candidates/recall`。
- 已用真实数据库直连 service 调用尺寸召回，返回 `total=0`，说明当前已有 50 个真实 part candidate 中没有命中测试尺寸。
- TestClient 未执行，因为当前环境缺少 `httpx`；本次未为临时验证安装依赖。

验证结果：

- 单元测试通过：`python -m unittest tests.test_fitting_candidate_recall_service tests.test_fitting_candidate_profile_service tests.test_part_shape_profile_service tests.test_ldraw_surface_profile tests.test_submodel_service`。
- 编译检查通过：`python -m compileall src tests\test_fitting_candidate_recall_service.py tests\test_fitting_candidate_profile_service.py tests\test_part_shape_profile_service.py`。

## 风险与决策点

### 形状精度与速度

高精度 voxel 和 surface profile 会增加预处理成本。建议先从低分辨率 profile 开始，确认召回效果后再提高精度。

### part 与 submodel 的统一抽象

submodel 应进入候选池，但不要把 submodel 强行伪装成 part。统一候选摘要即可，原始对象仍保持不同表和不同来源。

### 外观标签质量

名称规则可以快速起步，但长期需要结合几何和连接点验证，否则 modified、decorated、assembly 类零件容易误召回。

### 数据库体积

voxel、surface、rotation variants 都可能较大。建议先用 JSON 落库验证，再根据查询瓶颈决定是否拆表或二进制压缩。

## 近期建议任务

1. 已完成：统计当前 `ldraw_part_geometry`、`connector_instances` 的覆盖率和 NULL 率。
2. 已完成：设计并实现 `ldraw_part_shape_profiles` 表。
3. 进行中：把现有 `PartSurfaceProfile` 预处理结果持久化；已完成服务、工具、2 个指定样本验证、Plate/Brick/Slope 的 25 件 pilot 批处理，以及 100 件扩批和覆盖率统计工具。
4. 已完成：设计统一的 fitting candidate profile。
5. 已完成第一版：为 part 生成 candidate profile；已完成表、服务、工具和 50 个真实 part candidate。
6. 已完成代码路径：为 submodel 生成第一版 candidate profile，并补充 failed profile 追踪与 part/category/color 组成摘要；当前真实数据库没有 submodel 行，等待录入或导入真实 submodel 数据。
7. 已完成第一版：实现按尺寸、连接点、类别、颜色和不规则零件降级策略的候选召回 API。
8. 增加 query log，记录候选数量和耗时。
