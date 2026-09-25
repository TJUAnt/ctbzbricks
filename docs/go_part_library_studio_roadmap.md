# Studio Part Library 基准路线图与数据来源依据

> 状态：S1/S2/S5 与 active 切换已执行；S4 标准 Brick/Plate/Tile 基线已实现，S3、S4 扩展覆盖和最终数据清理待完成
> 日期：2026-08-15  
> 所属阶段：G8 后续 Part Library / Part preview 数据基准收口  
> 迁移原则：[go_backend_migration_principles.md](./go_backend_migration_principles.md)  
> 进度台账：[go_migration_progress.md](./go_migration_progress.md)

本文记录一个明确方向：后续 Part Library 不再以 legacy `public.ldraw_parts`
清单作为权威基准，而是以本机 BrickLink Studio 随附的 LDraw library
snapshot 作为几何和零件清单基准。legacy 数据仅作为名称、类别、历史 Rebrickable
映射等 catalog/enrichment 来源。

本文同时保留 roadmap 与已执行证据，不表示所有阶段已经完成。当前执行事实以
[进度台账](./go_migration_progress.md) 为准。任何真实数据库写入仍必须使用显式 Goose migration
或 data migration 脚本；API 和 Worker 启动不得执行 DDL、schema repair 或数据回填。

Component Repo 已确定 Go-only 目标。本路线图中的 manifest/import/enrichment/connectivity
工具和在线 Worker 新能力默认使用 Go；不得新增 Python 运行时或 Python task consumer。

## 1. 已确认方向

- Part 核心身份继续使用 `(partLibraryVersionId, ldrawPartNum)`。
- 一个 `partLibraryVersionId` 表示一次不可变 Part Library snapshot。
- Studio LDraw snapshot 成为新的 Part Library 基准来源。
- legacy `public.ldraw_parts` 不再决定新库包含哪些 Part；只参与 enrichment。
- BrickLink、LEGO design、LEGO element、Rebrickable 等外部编号写入
  `component_repo.part_external_ids`，不改核心 Part ID。
- LEGO element ID 是颜色/材质相关编号，不能作为无颜色 Part 的唯一身份。
- logical size 从几何派生，并通过 `logical_size_derivation_status` 记录可信度。
- Studio connectivity/collider 是关系能力的独立来源，不混入 Part preview 几何基准。
- `status=active` 只表示 library 生命周期；`preview_ready` 与 `relation_ready` 分别表示预览和
  关系检测能力，不允许从 `active` 隐式推断任一能力。

## 2. 本地 Studio 数据来源依据

本次只读核查使用本机安装目录：

```text
/Applications/Studio 2.0
```

重要输入：

| 来源 | 作用 | 已核查事实 |
|---|---|---|
| `/Applications/Studio 2.0/ldraw` | LDraw 几何、subpart、primitive、texture 根目录 | 全部 `.dat/.ldr/.mpd` 约 50,578 个 |
| `/Applications/Studio 2.0/ldraw/parts` | official top-level part 文件 | 与 `UnOfficial/parts` 合并后 distinct top-level part 约 24,426 个 |
| `/Applications/Studio 2.0/ldraw/UnOfficial/parts` | unofficial / BrickLink custom / printed / variant part 文件 | top-level `bl_` 前缀文件约 1,966 个 |
| `/Applications/Studio 2.0/data/ldraw_new.xml` | LDraw ↔ LEGO / assembly / decoration / material 映射 | `Transformation=5,272`，`Assembly=97`，`Decoration=43`，`Material=210` |
| `/Applications/Studio 2.0/data/designid.xml` | LEGO design alias 映射 | `Part=443`，alternate design IDs 共 533 个 |
| `/Applications/Studio 2.0/data/elementInfoList.json` | LEGO element、BrickLink item、BrickLink color、weight | 84,317 行，75,608 个 elementId，45,006 个 blItemNo，170 个 blColorCode |
| `/Applications/Studio 2.0/ldraw/connectivity` | Studio connector 数据 | 8,998 个 `.conn` 文件 |
| `/Applications/Studio 2.0/ldraw/collider` | Studio collider 数据 | 10,397 个 `.col` 文件 |

示例事实：

- `elementInfoList.json` 中 `blItemNo=3001` 对应 79 个 `elementId`，说明 LEGO
  element 是颜色/材质维度，而不是单一 Part 维度。
- `ldraw_new.xml` 中 `Decoration` 会把 printed LDraw part 映射到 base LEGO design
  和 decoration ID；这类关系不能强行记为 `exact`。
- `bl_*.dat` 文件名能提供 BrickLink custom/printed 编号线索，但必须记录来源和置信度。

## 3. 与 legacy 数据的边界

legacy 数据的已知问题：

- `public.ldraw_parts.file_hash` 在真实开发库中为空，不能作为几何源文件完整性依据。
- legacy Part 清单与 Studio LDraw snapshot 不一一对应。
- legacy 只对部分 Part 具有完整 logical size；大量 minifig、sticker、printed、electric、
  animal、wheel 等类别缺失 logical size。
- legacy `public.xref_part_numbers` 当前只有 Rebrickable 映射；BrickLink、LEGO design、
  LEGO element 为空。

legacy 后续只用于：

- 已有 Part 名称、类别、历史 catalog 字段补充；
- 已有 Rebrickable cross-reference 补充；
- 与旧数据覆盖率对比和迁移审计；
- 作为人工 review 线索，而不是新 Part Library membership 的权威来源。

## 4. 目标数据模型语义

### 4.1 Part Library Version

建议每次导入 Studio 基准时创建新的不可变 Part Library Version，并记录：

```text
source_system              bricklink_studio_ldraw
source_root                /Applications/Studio 2.0/ldraw（仅开发环境记录）
source_snapshot_label      Studio 2.0 local install snapshot / captured date
source_manifest_sha256     对 manifest 内容计算的 hash
importer_version           studio-part-library-importer-v4
connector_parser_version  studio-connectivity-v0-parser-v1
geometry_generator_version part-preview-ldraw-glb-v1 或后续版本
captured_at                timestamptz
metadata                   文件数量、目录摘要、输入文件版本等
```

生产或共享环境不应依赖开发机绝对路径作为可复现事实；应使用导出的 manifest、
source hash、对象存储归档或固定的只读 library bundle。

### 4.2 Part 与 geometry

`component_repo.parts`：

- membership 来自 Studio top-level part manifest；
- `ldrawPartNum` 使用规范化文件名，例如 `3001.dat`、`3005pe4.dat`、`bl_973pb5221c01.dat`；
- 名称/类别可由 Studio header、Studio category 文件和 legacy catalog enrichment
  逐步补齐。

`component_repo.part_geometries`：

- `source_relative_path` 指向 Studio snapshot 内相对路径；
- `source_sha256` 使用源文件内容 hash；
- `bbox`、`face_count`、GLB preview 输入均从 Studio LDraw 递归解析得到；
- logical size 不再是必填源字段，而是派生结果：
  - `derived_exact`：标准 brick/plate/tile 等可由几何和 connector/known rules 高置信推导；
  - `derived_approximate`：非标准形状只能给近似 bounding footprint；
  - `not_applicable`：minifig、sticker、cloth、decorative 等不适合 stud/plate 逻辑尺寸；
  - `failed`：解析失败或几何不足；
  - `legacy_imported`：仅用于当前 v9 前后的过渡数据。

### 4.3 External IDs

`component_repo.part_external_ids` 是外部编号唯一入口：

| id_system | 来源 | relation_type 建议 | 备注 |
|---|---|---|---|
| `ldraw` | Studio part filename | `exact` | 每个 Part 自带一条 self ID |
| `bricklink` | `elementInfoList.blItemNo`、`bl_*.dat` | `exact` / `print_variant` / `alias` / `unknown` | `bl_` 前缀不能无条件等同 exact |
| `lego_design` | `ldraw_new.xml` Transformation/Assembly/Decoration、`designid.xml` | `exact` / `alias` / `print_variant` / `shortcut` | decoration/assembly 需要保留 metadata |
| `lego_element` | `elementInfoList.elementId` | `color_variant` | 必须带 `blColorCode` metadata；未来可迁入颜色感知表 |
| `rebrickable` | legacy `public.xref_part_numbers` | `exact` / `alias` / `unknown` | 保留现有交接结果，后续可与 Rebrickable CSV 重建 |

外部编号导入必须保留：

```text
source
confidence
relation_type
metadata
captured_at / script version
```

不要用外部编号覆盖 `ldrawPartNum`，也不要假设一一对应。

## 5. Roadmap

### S0：数据来源与许可确认

目标：把输入来源、可复现方式和使用边界写清楚。

交付：

- 本文档；
- Studio source manifest 格式草案；
- 导入前的 license / redistribution review 记录；
- 明确开发机路径只作为发现来源，不作为长期生产依赖。

验收：

- 后续开发者能知道每个字段来自哪个文件；
- 不再把 legacy 覆盖率低的问题误判为 Studio 数据不足。

### S1：Studio manifest 生成器

目标：只读扫描 Studio snapshot，生成可审计 manifest，不写数据库。

当前实现：

- Go 离线工具：`backend-go/cmd/studio-manifest`。
- Makefile 入口：

  ```bash
  cd backend-go
  STUDIO_ROOT="/Applications/Studio 2.0" OUT_DIR=/tmp/ctbzbricks_studio_manifest_s1 make studio-manifest
  ```

- 输出：
  - `studio_manifest.json`：源文件 manifest、文件类型、相对路径、SHA-256、字节数、canonical top-level Part；
  - `studio_manifest_summary.json`：数量摘要、metadata source 摘要、manifest hash；
  - `studio_manifest_coverage.json`：仅在显式提供 `LEGACY_PARTS_FILE=/path/to/list` 时生成。
- 工具不连接数据库；coverage 输入必须是预先导出的 legacy part list 文件，避免工具隐式读取真实开发库。

交付：

- manifest 包含 top-level parts、subparts、primitives、textures、connectivity、collider；
- 每个源文件记录 `relative_path`、`sha256`、`size_bytes`、`file_kind`；
- 对 `parts/` 与 `UnOfficial/parts/` 的同名覆盖规则显式记录；
- 生成覆盖率报告：Studio-only、legacy-only、intersection。

验收：

- 同一输入重复生成 manifest hash 一致；
- 输出 counts 与核查基线同量级；
- 不读取或修改真实数据库。

2026-08-15 真实 Studio snapshot 运行结果：

```text
manifest path                 /tmp/ctbzbricks_studio_manifest_s1_v3/studio_manifest.json
summary path                  /tmp/ctbzbricks_studio_manifest_s1_v3/studio_manifest_summary.json
manifest sha256               524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
total manifest files          69,968
LDraw .dat/.ldr/.mpd files     50,578
canonical top-level parts      24,426
official top-level .dat        12,132
unofficial top-level .dat      23,216
duplicate part nums            10,922
top-level bl_ prefixed files    1,966
connectivity .conn files        8,998
collider .col files            10,386
textures                           6
ldraw_new.xml transformations   5,272
designid.xml parts                443
elementInfoList.json rows      84,317
distinct elementId             75,608
distinct blItemNo              45,005
blItemNo=3001 element rows         79
```

同一 snapshot 分别以 `/Applications/Studio 2.0` 与
`/Applications/Studio 2.0/ldraw` 作为输入重跑，manifest hash 一致。真实 coverage
未在本次运行生成，因为 S1 工具按设计不读取真实数据库，且本次未提供显式
`LEGACY_PARTS_FILE`。

### S2：Studio Part Library snapshot 导入

目标：创建新的 Studio-based Part Library Version。

当前实现：

- Go 离线工具：`backend-go/cmd/studio-import`。
- Makefile 入口：

  ```bash
  cd backend-go
  MANIFEST=/tmp/ctbzbricks_studio_manifest_s1_v3/studio_manifest.json STATUS=building make studio-import
  ```

- 默认 `status=building`，不会自动改变 runtime active library。
- `status=active` 或后续显式 SQL 才会切换 active Part Library。
- Library ID 默认由 `studio-part-library:<manifestSha256>` 确定性生成，便于重复导入同一 snapshot。
- importer 使用临时 staging table + `CopyFrom` 批量写入；API/Worker startup 不执行导入。
- importer 会递归解析 LDraw type 1/3/4，写入 bbox、face/vertex count、source hash 和
  `logical_size_derivation_status=derived_approximate`；失败文件写入 `geometry_status=failed`
  和稳定 error code/params。

Studio LDraw geometry 处理原则：

- Part preview 的第一阶段目标是稳定 mesh/bbox 与 logical size 派生，不承诺还原 printed
  texture；贴图/UV 数据后续若要进入视觉预览，必须作为单独纹理阶段设计。
- LDraw type 3/4 face 若包含 Studio 追加的 UV/texture 字段，解析器只读取标准几何坐标，
  忽略 trailing texture fields；这不是放宽业务校验，而是按当前 preview 目标选择几何子集。
- `PE_TEX_INFO` 等超长 texture metadata 属于 type 0 meta/comment，几何解析可跳过；parser
  不应因为单行 base64 texture 超过 scanner token 限制而把 part 标为 failed。
- `8/`、`48/` primitive 引用优先按原路径解析；如果 Studio snapshot 只有 plain
  `p/<name>.dat`，允许 fallback 到 plain primitive，以便几何可用。
- 缺失 subpart/primitive 不用空 mesh、零 bbox 或 guessed geometry 兜底；必须保留
  `geometry_status=failed`，并记录 `fromPath/reference/candidates` 以支持后续补源或审计。
- importer 与 `component.part_preview.materialize` Worker 必须保持同一套 LDraw 解析语义；
  不能出现数据库 geometry ready、Worker GLB materialize 却因同类语法失败的分叉。

交付：

- 显式 data migration 或离线 importer；
- 用 Studio top-level manifest 写入 `component_repo.parts`；
- 写入 `part_geometries` 源路径、hash、解析状态和 bbox/face_count；
- 为全部 Part 建立 `part_previews` 初始状态；
- legacy catalog enrichment 单独执行，并记录来源。

验收：

- 新版本 Part 数量以 Studio top-level manifest 为准；
- 不要求与 legacy `public.ldraw_parts` 一一对应；
- API/Worker startup 无 DDL/回填；
- 至少用 `3001.dat`、printed part、`bl_` part、unofficial part 做 preview smoke。

后续本机 Studio 更新使用保留脚本：

```bash
cd backend-go
./scripts/update-studio-part-library.sh
```

脚本要求输入其打印的精确数据库目标，依次生成新 manifest、完整 dry-run、执行 Goose up、导入并
原子切换 active library。新 snapshot 使用 manifest hash 派生新 Library ID；旧 active 在同一导入
事务内改为 retired，导入失败时不会切走旧版本。自动化环境可把脚本打印的值传给
`CONFIRM_DATABASE_TARGET`；只有已经单独验证过 snapshot 时才应设置 `SKIP_STUDIO_DRY_RUN=1`。

2026-08-15 真实开发库执行结果：

```text
partLibraryVersionId         c8176a73-eccb-4db3-ba72-30edf5f9fd23
source_name                  bricklink_studio_ldraw
source_hash                  524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
status after import          building
status after activation      active
legacy-based previous active retired
parts                        24,426
part_previews                24,426
geometry ready               22,569
geometry failed               1,857
external IDs                      0（S3 范围）
```

2026-08-15 parser hardening dry-run（未写入真实库）：

```text
input manifest hash          524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
parts                        24,426
geometry ready               24,373
geometry failed                  53
remaining failure reason     missing LDraw reference
```

2026-08-15 parser hardening 写入真实开发库后核对：

```text
partLibraryVersionId         c8176a73-eccb-4db3-ba72-30edf5f9fd23
status                       active
active libraries             1
parts                        24,426
part_previews                24,426
geometry ready               24,373
geometry failed                  53
```

本次 hardening 解释了原 1,857 个失败的大部分来源：Studio printed/textured part 会在
标准 type 3/4 face 后追加 UV/texture 字段，且部分文件包含超长 `PE_TEX_INFO`
metadata。对于当前 Part preview，解析这些文件的标准几何坐标即可得到 bbox/mesh；剩余
53 个失败经抽样检查属于当前 Studio snapshot 缺少被引用 subpart/primitive，不能继续猜测。

代表样例：

```text
3001.dat ready face_count=700 logical≈4 x 2 x 3.5
3020.dat ready face_count=700 logical≈4 x 2 x 1.5
3023.dat ready face_count=172 logical≈2 x 1 x 1.5
3062b.dat ready face_count=448 logical≈1 x 1 x 3.5
3710.dat ready face_count=364 logical≈4 x 1 x 1.5
bl_10202pb016.dat ready face_count=2444
```

历史说明：本节最初只完成 DB-level Part/geometry/preview metadata smoke；后续已经通过 Go
API/Worker + Storage 完成真实 GLB Artifact materialize。当前状态以本路线图后续章节和
[迁移进度台账](./go_migration_progress.md) 最新摘要为准。

### S3：外部编号补充

目标：从 Studio metadata 和 legacy xref 补齐外部编号。

交付：

- `ldraw` self ID 全量；
- BrickLink：`elementInfoList.blItemNo` 和 `bl_*.dat` 解析；
- LEGO design：`ldraw_new.xml` 与 `designid.xml`；
- LEGO element：`elementInfoList.elementId`，带 `blColorCode` metadata；
- Rebrickable：保留 legacy xref 或从更权威来源重建。

验收：

- 每条 external ID 都有 `source/confidence/relation_type`；
- LEGO element 不进入核心 Part ID；
- 同一 Part 可挂多个外部编号；
- 对 `3001.dat` 输出 ldraw、BrickLink、LEGO design、多个 LEGO element 示例。

### S4：logical size 派生

目标：把 logical size 从 legacy 字段改为可解释派生结果。

交付：

- 几何 bbox 到 stud/plate 的单位转换；
- 常规 brick/plate/tile 的 exact 规则；
- 非矩形/装饰/人仔/贴纸等 not-applicable 或 approximate 规则；
- `derivation_status`、`derivation_params`、`algorithm_version` 审计信息。

验收：

- `3001.dat`、`3023.dat`、tile、slope、minifig、sticker 等样例结果可解释；
- preview 不因 logical size 缺失而失败；
- 搜索/推荐如果使用 logical size，必须显式过滤 status 或降低 approximate 权重。

2026-09-24 按产品确认完成 S4 收口：importer v5 将 LDraw header 描述规范化；描述符合
`Brick/Plate/Tile W x D`、不含第三维，且 bbox 三个物理轴均在标称值 2mm 内时写入 `derived_exact`，其余 ready
Part 一律保留 bbox 并写为 `derived_approximate`。Part Search 同时接受两种来源，平面轴容差 ±0.25 stud、垂直轴
±0.625 plate，边界包含；sticker/decal 不再排除。规则版本 `ldraw-description-nominal-or-bbox-v2` 与 importer
version 共同参与确定性 Library ID。真实 v5 重导入审计为 3,067 exact、21,832 approximate、55 failed，
`3001/3023/3070b` 与 sticker fixture、恰好/超过 2mm 边界均有测试，因此不再为 slope/minifig 等类别建立枚举表。

### S5：connectivity 与 collider 接入

目标：把 Studio connector/collider 作为下一阶段独立能力接入。

状态：2026-08-22 已完成 Go importer、schema、关系 Worker、隔离 PostgreSQL E2E 与真实 Supabase
导入；真实库当前 Goose v11，active library 已 `preview_ready/relation_ready=true`。

交付：

- [x] Go `.conn` parser 覆盖 Studio Axle、Ball、Hole、Stud、Fixed、Hinge、Rail、Slider
  record，并展开 Stud/Hole cell matrix；坐标由 Studio 左手系稳定转换为 LDraw。
- [x] Go `.col` parser 覆盖已观测的 type `9/8192` box record；历史数据中的 signed
  half-extents 取绝对值规范化，原值保留在 `raw_params`，不把合法旧数据误报为失败。
- [x] connector 映射到版本化 `part_connector_definitions`；collider 写入
  `part_collider_definitions`，二者都绑定不可变 `part_library_version_id`。
- [x] Goose v10 为 Part Library 增加 `preview_ready/relation_ready`、connector/collider
  source hash、parser version 和 count。生命周期 `status` 与能力状态彻底分离。
- [x] `studio-import` v2 校验 sidecar manifest size/hash，使用 staging + `CopyFrom` 与显式
  transaction 批量替换同版本定义；`--dry-run` 不连接数据库。
- [x] Go Worker 注册 `component.relations.detect`，从 Candidate 冻结的 Part Library 读取
  connector/collider，原子物化 RelationCandidate、ConnectorAnalysis、external Interface 与
  Candidate/Draft interface signature。旧 Python relation worker/adapter/launcher 已删除。

验收：

- [x] connector/collider 失败不改变 `preview_ready`；关系调度仅接受
  `relation_ready=true` 的冻结 library。
- [x] 关系任务 input hash 覆盖 structure/geometry、snapshot schema/parser、
  `partLibraryVersionId`、library source hash、connector source hash/parser version 和 detector
  version。
- [x] 旧 ComponentVersion/Candidate 继续引用冻结 Part Library，不读取后来切换的 active
  library 重解释历史数据。
- [x] Go relation PostgreSQL E2E 验证 task schedule/claim/handle/complete、3 个 connector、
  1 个 relation 和 3 个 external interface 的原子结果。

2026-08-22 完整本机 Studio manifest dry-run（未写数据库）：

```text
manifest sha256              524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
parts                        24,426
geometry ready               24,373
geometry failed                  53（缺失 LDraw reference，沿用 S2 可审计失败）
connector files               8,881（canonical Part sidecar）
connector definitions       190,419
connector parse failed            0
connector source hash       0aab7080e5d1ba2f365037e22f09ee26518f507f7e4b70be394765221d2be7ac
collider files                10,295（canonical Part sidecar）
collider definitions parsed 1,876,415
collider source hash       1266cefe0db7cd1db7cca8b94e480bba106bb1e4e03845724a1fa070f821e5b6
collider parse failed              0
preview_ready                  true
relation_ready                 true
```

上面的 file count 是 canonical top-level Part 实际采用的 sidecar 数量，不等同于 manifest 中
官方/非官方目录合计的原始文件数。`.conn/.col` 属于本机只读导入输入；仓库不提交或分发 Studio
源数据及其导出数据集。真实 Supabase 默认使用 `colliderStorage=metadata-only`：完整解析并保存
1,876,415 的 count/hash/parser 证据，但不把 145 MB `.col` 源展开成 187 万 PostgreSQL 行。精确
collider clearance/raycast 算法不属于本次 S5：未来应把压缩 collider bundle 放对象存储并按 Part
读取，不能把“输入已验证”宣称为已经完成精确碰撞求解。

### S6：切换与清理

目标：将 active Part Library 切到 Studio-based version。原先保留旧版本审计的默认目标已被
2026-09-22 用户对非生产库的显式清理授权覆盖；这不是未来生产数据的默认保留策略。

交付：

- active Part Library discovery 指向新版本；
- 真实 Part preview smoke；
- Component BOM 与 Part viewer 使用新版本；
- 常规切换保留旧版本；本次非生产库的两份旧快照及其引用链在另一个受控事务中物理清理。

验收：

- 前端 Part viewer 可以预览 Studio 新版本中的代表 Part；
- 常规切换下 BOM 的冻结旧版本仍可解析；本次获批清理后旧 Version 页与相应 BOM 不再存在；
- 迁移台账记录新旧版本数量、hash、外部编号覆盖率和已知缺口。

## 6. 开发者实现注意事项

- 不要从 API 或 Worker 启动路径自动扫描 `/Applications/Studio 2.0`。
- 不要把开发机绝对路径暴露给公共 API、任务错误、日志中的用户可见字段或前端。
- 导入脚本应显式接收 source root / manifest path，并在运行前打印目标数据库和 Part Library
  Version。
- 任何真实库 destructive reset/reseed 仍需再次确认具体数据库。
- sqlc 生成文件不得手改；schema 变更走 Goose，数据导入走显式 data migration/importer。
- 官方 Part 文案继续遵守 reviewed translation 规则；机器编号、状态、JSON key、外部编号不翻译。
- 若后续需要分发 Studio-derived source 或 derived artifact，必须先完成许可与再分发边界确认。
- ComponentVersion preview 的用户价值是“整体组件 GLB”，不是单个 Part 的 GLB 清单。
  当前 Go Worker 使用 ComponentVersion 固定的 Part Library、SceneSnapshot、structure/geometry
  hash 和 Studio LDraw source path 按需生成整体 GLB；没有 structural cube fallback，也不读取
  当前 active library 重解释旧版本。
- 冻结库中 geometry 为 `failed/missing` 的 Part 保留在 BOM 并明确标注，ComponentVersion GLB
  跳过对应实例后继续生成；任务结果与 Artifact metadata 记录 omissions。geometry 已为 ready 时的
  source 缺失或 hash 漂移仍严格失败。
- 批量 materialize 每个 Part 的 GLB 是后续缓存/性能优化 TODO，不是当前 Component preview
  的前置条件。Part-level GLB 仍可按单个 Part preview API 逐个生成。

## 7. 当前未解决问题

- importer v5 和 Goose v26 已写入真实库，v5 成为唯一 active；真实 API 的标称、bbox、sticker 与 zh-CN fallback
  组合搜索及真实查询计划已验收；24,899 个 ready geometry 均有当前 generator ready/verified Preview。仅认证浏览器
  结果卡片、缩略图与交互式 3D 详情仍待收尾。
- Part Search 当前按 24,899 个 ready 候选保留页码。真实 PostgreSQL 17.6、`work_mem=2184kB` 的首屏约
  116.034ms/3.6MB external merge，最深页约 156.197ms/5.152MB external merge；按产品决定暂不做 100,000 候选排序/keyset 优化，单版本接近
  100,000、生产 temp file/延迟异常或产品批准改变交互时重新开启。
- 后续 Studio snapshot 更新仍必须由保留脚本确认精确数据库目标；同一 active/ready manifest
  默认 no-op，强制重建需显式设置 `FORCE_STUDIO_REIMPORT=1`。
- 精确 collider clearance/raycast 算法尚未实现；S5 只完成数据接入、版本冻结和可用性标记。
- Studio 文件版本号/发布日期应如何从本地安装稳定提取，仍需 importer spike 确认。
- `bl_*.dat` 到 BrickLink item 的 relation_type 需要抽样校验，不能全部假设 exact。
- `elementInfoList.json` 的 `blColorCode` 到系统颜色表尚未建立；LEGO element 暂只能作为带
  metadata 的 color_variant external ID。
- `.conn` / `.col` parser 已按本机 Studio snapshot 和公开社区资料完成兼容性验证；若要分发
  Studio 原始或派生数据集，许可与再分发边界仍需单独确认。
- legacy Part 名称/类别与 Studio part 的冲突解决规则尚未制定。
