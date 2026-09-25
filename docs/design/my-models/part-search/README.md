# Part Library 详细设计

> 状态：当前实现文档；G8 后续 Part Library / Part Search 数据与搜索契约已按 importer v5 收口
>
> 功能需求：[我的模型 / Part Search](../../../requirements/my-models/part-search/README.md) · [Part 详情](../../../requirements/my-models/part-search/part-detail/README.md)
>
> 路线与数据来源：[Studio Part Library 基准路线图](../../../go_part_library_studio_roadmap.md)
>
> 公共接口：[Component Repo API](../../../api.md)
>
> 迁移事实：[Go 后端迁移进度](../../../go_migration_progress.md)

## 1. 模块边界

Part Library 覆盖 `/part-search` 与 `/parts/:partLibraryVersionId/:ldrawPartNum`。它把 BrickLink Studio 随附的
LDraw snapshot 离线导入 PostgreSQL，并向 Go API 提供稳定 Part 身份、源描述、物理尺寸、几何状态、预览资产和
reviewed translation。API 与 Worker 启动不扫描 Studio、不执行 DDL，也不回填 snapshot。

核心身份是 `(partLibraryVersionId, ldrawPartNum)`。`ldrawPartNum` 是机器标识；展示名称来自顶层 LDraw 文件第一条
有效描述，当前 locale 存在 reviewed `part_translations.name` 时才覆盖源描述。缺少 reviewed 翻译时返回源内容及
`contentLocale`，不在线翻译。

## 2. 已修复偏移与产品决策

此前 `.dat` 文件名被当作唯一名称，描述与尺寸条件混在单个 query 中，approximate bbox 既不能被正确解释，也会在
部分路径中被当成精确标称尺寸。当前产品将搜索明确收敛为两组条件：

1. 名称索引：`description` 模糊包含匹配 Part 源描述及当前 locale 的 reviewed translation；`partNumber` 是独立的
   机器编号包含匹配。
2. 尺寸：标准 Brick/Plate/Tile 使用可信标称尺寸；其他 ready Part 使用 bbox。两类结果都允许每个物理轴 ±2mm，
   不再逐一维护 modified/slope/round/minifig/sticker 等类别枚举。

sticker/decal 不再排除。连接点、类别、颜色、混合 fitting score 与 100,000 候选排序优化不属于当前 Part Search。

## 3. 搜索与排序契约

`POST /api/v1/parts/search` 接受可选字段 `description`、`partNumber`、`widthStud`、`depthStud`、
`heightPlate`、`locale`、`page`、`pageSize`：

- 所有已填写字段按 AND 组合；description 按空格和中英文逗号切分、去重，各 token 全部命中。
- 宽/深是平面轴，两者同时填写时允许 90° 旋转；高度是独立垂直轴。
- 平面容差为包含边界的 `±0.25 stud`，高度为包含边界的 `±0.625 plate`，两者分别等于 2mm。
- `derived_exact` 与 `derived_approximate` 均可命中尺寸条件；UI 分别显示“标称尺寸”和“包围盒尺寸”。
- 只返回 `geometry_status=ready`；无尺寸条件时同样返回两种尺寸来源。
- 排序为描述完整匹配优先、源描述、唯一 `ldrawPartNum`；page size 最大 200。
- active version、exact total 与页面读取位于同一 `REPEATABLE READ READ ONLY` 快照，响应固定返回本次使用的
  `partLibraryVersionId`，详情链接不会随后来 active 切换漂移。

## 4. 尺寸派生与导入

importer v5 使用 `ldraw-description-nominal-or-bbox-v2`：

- 源描述以 `Brick W x D` 开头时标称高度为 3 plate；`Plate/Tile W x D` 为 1 plate。
- 描述带显式第三维，或 bbox 宽/深/高任一物理轴偏离标称值超过 2mm 时，不采用标称值。
- 通过上述校验的 Part 写为 `derived_exact`；其余 ready Part 统一把 LDraw bbox 换算为 stud/plate 并写为
  `derived_approximate`；geometry failed 保持空尺寸。
- importer version 与算法版本共同参与确定性 Library ID，保证同一 manifest 的算法升级产生新不可变 snapshot。
- 单事务写入 Part、geometry、connector；真实更新先导入 `building`，预览门禁通过后才切 active。

当前真实 active Library 为 `a33262fd-c702-4bd5-84c6-8966761ca88d`，source manifest SHA-256 为
`c8df4312df4b0e2a6e8d9e7c6740ca927da51c1146aa8da3bab1fd68325934d2`。共 24,954 Part，其中 24,899
geometry ready、55 failed；3,067 个标称尺寸、21,832 个 bbox，192,202 connector。此前 importer v4 snapshot
已按非生产库清理授权删除。

## 5. 前端、HTTP 与 i18n

- 页面把描述、编号、宽、深、高拆成独立输入；首次进入加载第一页，搜索与翻页复用 authenticated client。
- 卡片展示名称、机器编号、尺寸来源与 GLB 缩略图；单个签名或缩略图失败只回退占位图。
- 搜索缩略图与 Part 详情共用 `part-neutral` 摄影棚档位：把 Part 的无色几何统一显示为中等明度冷灰塑料，固定
  `metalness=0`、`roughness=0.56`，并降低环境光与补光以保留孔洞、折角和曲面明暗。Component 详情和候选工作台
  继续使用 `viewer` 档位以保留原始颜色；该档位不增加纹理、几何、阴影贴图或额外 render pass。搜索缩略图仍由
  单个 256px WebGL context 串行渲染一帧并缓存为 WebP，Part 详情保留既有交互、地面与柔和阴影。
- 缩略图缓存版本为 `glb-thumbnail-v3`；材质或灯光档位变化通过版本键自然失效，不要求重新生成或改写后端
  verified GLB Artifact。
- Part Viewer 读取不可变版本的 geometry/Preview，展示相同尺寸来源；GET 不创建任务，未 ready 时由显式 POST
  materialize 调度持久任务。
- 页面文案使用 typed semantic key。此次新增/修改 `sizeSearchHint`、`sizeNominal`、`sizeBoundingBox` 的中英文资源；
  资源版本 `frontend-2026.09.23.1`，catalog hash
  `fc6dd2d6e90b821dac934e441ba510f7657f1771ee8f1458fa44b9279ca66db7`。
- Part 编号、尺寸、状态、JSON key、API code、Artifact ID/hash 不翻译；用户内容不参与本模块。

## 6. 持久化、预览任务与权限

- 搜索与详情要求认证 actor，但官方 Part Library 是共享内容，不按 owner 分区。
- Goose v26 以 `part_geometries_searchable_logical_size_idx` 覆盖 exact/approximate 的版本、旋转后平面尺寸和高度；
  SQL 先固定页面，再关联 preview/artifact。
- Preview 是 PostgreSQL durable task。全库预生成按 500 行批次准备与领取，避免经 Supabase pooler 一次流式读取
  24,899 行导致任务心跳饥饿；每个 Part 独立提交，重启后只继续 pending/过期条目。
- GLB 仍由冻结 LDraw 输入重新确定性计算；若内容哈希对应的 verified Artifact 在 provider/bucket/key/SHA/大小等
  全部一致，全库 prebuild 直接复用并只重绑新 snapshot，不重复 PUT。单 Part materialize 可能由对象丢失触发，
  不走该捷径，继续承担 Storage 修复职责。
- PostgreSQL 保存业务/任务/Artifact metadata；对象正文位于 Storage。API 不返回 storage key，只返回短期签名 URL。
- 一次性 `20260923_studio_v5_replace.sql` 只允许精确 v4→v5 非生产替换；API/Worker startup 不执行该脚本。

## 7. SQL 性能预检与证据

| 项目 | 当前决策 |
|---|---|
| 驱动范围 | 唯一 active `part_library_version_id`，当前 24,954 Part / 24,899 ready |
| 增长 | 单 snapshot 随 Studio 增长；历史版本不进入 active 搜索 |
| 过滤 | 编号通常高选择性；描述包含匹配可能高命中；尺寸由查询专用表达式索引驱动 |
| 排序/分页 | 保留页码与 exact total；单版本接近 100,000 或真实指标触发时重开 keyset/排序投影 |
| 翻译 | 只读取请求 locale 的 reviewed 行；当前真实 v5 translation 为 0，fallback 分支已验收 |

2026-09-23 在真实 Supabase PostgreSQL 17.6、`shared_buffers=224MB`、`work_mem=2184kB`、
`effective_cache_size=384MB` 上运行 opt-in 只读 `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)`；以下为 warm-cache
远程开发库单次证据，不是生产 SLO：

| 场景 | 执行时间 | 计划结论 |
|---|---:|---|
| 无筛选首屏 | 116.034 ms | snapshot 有界扫描；约 3.6MB external merge，登记 PERF-01 |
| 编号 `3001` | 27.423 ms | 单 snapshot 包含扫描；无 temp |
| `plate` 高匹配 | 51.109 ms | 1,124 ready 命中；Top-N 内存排序 |
| zh-CN fallback + `2×4×1` | 2.023 ms | translation 0 行；尺寸索引，18 行 |
| 标称 `2×4×1` | 2.549 ms | `part_geometries_searchable_logical_size_idx`，226 候选 |
| bbox `5.8×1×0.031` | 1.403 ms | 同一尺寸索引，31 候选；包含 sticker |
| 最深支持页 | 156.197 ms | 24,899 候选 OFFSET；external merge 5.152MB |
| `plate` exact count | 45.604 ms | 1,124 行；无 temp |

本地 PostgreSQL 14.17 的 24,954 行 fixture 同时覆盖 reviewed translation、标称/bbox、边界恰好 2mm 与超过
2mm、首/深页和 count/list 语义；本地时间仅证明查询形状。

## 8. 关键代码索引

- 页面与详情：`frontend/src/parts/PartSearchPage.tsx`、`PartViewerPage.tsx`
- i18n：`frontend/src/i18n/resources/{en-US,zh-CN}/partSearch.json`
- Handler/DTO/Service：`backend-go/internal/workbench/handler.go`、`types.go`、`service.go`
- SQL/迁移：`backend-go/db/queries/parts.sql`、`db/migrations/00026_part_library_bbox_size_search.sql`
- 派生/importer：`backend-go/internal/partlibrary/ldraw_geometry.go`、`importer.go`
- 预生成：`backend-go/internal/workbench/part_preview_prebuild.go`、`scripts/start-part-preview-prebuild-worker.sh`
- 数据维护：`backend-go/db/data_migrations/20260923_studio_v5_replace.sql`
- 集成/计划：`backend-go/tests/integration/{workbench,httpapi}`、`backend-go/tests/performance/partsearch/search_test.go`

## 9. 验证与已知问题

真实 API 已用短期本地测试 JWT 验证：`brick + 3001 + 2×4×3` 返回 `3001.dat / Brick 2 x 4 / derived_exact`；
zh-CN `plate + 2×4×1` 在无 reviewed 翻译时正确回退源描述；`sticker + 003238j + 5.8×1×0.031` 返回唯一
`derived_approximate` 结果。预生成 task `592ac3da-7735-437c-8854-665e675559ef` succeeded；24,899 个 ready
geometry 全部具有当前 generator 的 ready/verified Preview，缺失、无效与失败计数均为 0。代表详情 API 另行确认
`3001.dat` 和 `003238j.dat` 均返回 ready GLB。浏览器已确认中英文筛选壳层、±2mm/尺寸来源提示及认证后的真实
搜索结果卡片；交互式 3D 详情仍按 `PART-LIBRARY-DATA-01` 客观门禁处理。

2026-09-25 已在认证浏览器的真实第一页验证 `glb-thumbnail-v3`：Arch、Ball、Bar 与 Baseplate 的轮廓、孔洞、折角、
曲面明暗和颗粒细节均可在浅灰背景上辨认，20 张卡片正常完成按需渲染。单元测试固定缩略图材质参数和三盏灯数量，
确保该视觉调整不引入纹理、阴影或额外灯光的性能成本；`npm test` 通过 25 个文件 / 108 个测试，`npm run build`
通过，`i18n:check` 随两项命令均验证 2 个 locale、10 个 namespace。

同日已在认证浏览器验证 `4100338.dat` Part 详情：详情页复用 `part-neutral` 后，Boat Bow 的舱体开口、stud、侧壁与
曲面明暗均可辨认，重置视角入口保持可用，既有地面和柔和阴影保留。`ComponentScene` 通过显式 profile 区分 Part
与 Component，Component 详情和候选工作台仍默认使用 `viewer`，不会被 Part 的中性材质覆盖。完整 `npm test`
继续通过 25 个文件 / 108 个测试，`npm run build` 通过。

已知问题：

1. `PART-LIBRARY-DATA-01`（部署验收）：v5 已是唯一 active，真实 API、查询计划和 24,899 个 ready geometry 的
   当前 generator ready/verified Preview 门禁均已通过；认证浏览器已核对真实搜索结果与缩略图，关闭条件只剩代表
   Part 的交互式详情验收。
2. `PART-LIBRARY-SIZE-01`（已关闭）：分类冻结为“通过描述+bbox 校验的标准 Brick/Plate/Tile 标称尺寸；其他 ready
   Part bbox”，算法版本和代表 fixture 已固定，v5 重导入审计为 3,067/21,832/55。
3. `PART-LIBRARY-PERF-01`（Deferred，产品决定）：真实首屏与最深页在 2.1MB work_mem 下均会 spill；本轮不做
   100,000 候选排序。单版本接近 100,000、生产 temp/延迟异常或产品批准改变页码交互时，改用 keyset 或权威
   搜索/排序投影并重跑 first/deep/cold/warm 门禁。
4. `PART-LIBRARY-SEARCH-01`（容量阶段）：名称/编号包含匹配当前是单 active snapshot 有界扫描；容量或指标触发后
   再选择 FTS/trigram/规范化投影并记录写放大与索引成本。
5. `PART-LIBRARY-I18N-01`（内容运营）：API 只选 reviewed translation，但 v5 当前 reviewed 覆盖率为 0；建立
   locale 覆盖率、审核责任和发布门禁后关闭。
6. `PART-LIBRARY-STORAGE-01`（独立清理）：旧 Artifact/Storage 对象不由本次数据库快照替换顺手删除；先排除全部
   Artifact/Task 引用，再经 Storage API 分批清理并核对对象与 metadata 一致性。
