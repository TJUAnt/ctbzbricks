# Component Repo Component 详细设计

> 功能需求：[我的模型 / 个人 Component 仓库](../../../requirements/my-models/component-repo/README.md)
>
组件广场已按独立菜单模块拆分设计，其公共/个人订阅页签见[组件广场详细设计](../../model-plaza/model-plaza/README.md)，公共发布事件、成员资格和滚动加载见
[公共 Feed 详细设计](../../../component_repo/public_feed.md)。本文件中的公开目录仅描述 Component 资源目录契约。

> 代码核对日期：2026-09-19
>
> 当前阶段：Component Repo 公开 API 和持久任务主链路已切换到 Go。
>
> 接口权威定义：[Component Repo API](../../../api.md)；迁移边界：[Go Component 迁移计划](../../../go_component_migration_plan.md)。

## 1. 本文范围

本文描述 Component 与 ComponentVersion 的核心生命周期，以及创建它们所需的上传、Import、Candidate、Preview、
BOM、Source 和 Diff 链路。Group、Star、Watch 是 Component DTO 的关联投影，但各自的业务实现由独立文档描述。

核心边界：PostgreSQL 保存业务、版本、任务和 Artifact 元数据；Supabase Storage 保存源文件和大型派生文件；耗时解析、
关系检测、验证和 GLB 生成由持久 Go Worker 执行，Gin Handler 不做长计算。

## 2. 前端页面与调用链

| 页面/功能点 | 前端调用 | 结果用途 |
|---|---|---|
| 个人仓库 | `listComponentGroups` + `searchComponentGroupComponents` | root 表示自有 Component；custom Group 表示直接 membership |
| 收藏视图 | `listComponentStars` | 详见 [Star 设计](star.md) |
| Component 详情 | `getComponent` + `listComponentVersions` | 选择 current published 或最新可见 Version；阅读页不预取连接分析 |
| Version 详情 | `getComponentVersion` | 切换历史版本并显示状态、发布说明和来源 |
| Preview | `loadComponentVersionPreview` | 只读取 Worker 已生成且验证通过的 GLB；失败只降级预览区域 |
| BOM | `loadComponentVersionParts` | 读取 SceneSnapshot 解析期冻结的零件汇总、reviewed Part 名称和可选 ready Part Preview 定位符 |
| Version Diff | `loadComponentVersionDiff` + 前后 Preview | owner 即时比较 SceneSnapshot；不创建任务或新 Artifact |
| 元数据编辑 | `updateComponent`、`updateComponentVersion` | 只允许 owner user Component / Draft Version |
| 发布 | `publishVersion` | 发布 Draft、切换 current Version、产生领域事件并原子创建 Feed 图片任务 |
| 删除 | `deleteComponent`、`deleteComponentVersion` | Component 软删除并异步清理关系；owner 详情页把 Component 删除收进发布按钮右侧的更多菜单；Version 只允许删除 Draft |
| Source 下载 | `downloadComponentVersionSource` | 详情页明确显示“图纸源文件”下载；后端校验可见性、Artifact ownership/key 后返回短期签名 URL |
| 新建/修订上传 | `createComponentImportWithProgress` | 创建 upload session、直传 Storage、complete 后进入持久任务 |
| Import 进度/历史 | `getComponentImport`、`listComponentImports`、`getTask` | 映射上传、解析/BOM、3D Preview 三个持久阶段；页面关闭不取消任务 |
| Candidate 工作台 | relation/connector/interface/validate API | owner 审核解析结果并形成可发布 Draft Version |

页面代码：

- 个人目录与列表控制器：[ComponentRepoPage.tsx](../../../../frontend/src/componentRepo/ComponentRepoPage.tsx)；该页面只拥有个人 Group、收藏、上传和 Version 入口状态，不再承载广场。Group 树和成员编辑：[ComponentGroupControls.tsx](../../../../frontend/src/componentRepo/ComponentGroupControls.tsx)；上传弹窗：[ComponentUploadDialog.tsx](../../../../frontend/src/componentRepo/ComponentUploadDialog.tsx)；列表纯展示：[ComponentRepoPresenters.tsx](../../../../frontend/src/componentRepo/ComponentRepoPresenters.tsx)。广场由独立 [ComponentPlazaPage.tsx](../../../../frontend/src/componentRepo/ComponentPlazaPage.tsx) 承载，详见[组件广场设计](../../model-plaza/model-plaza/README.md)。
- 详情控制器：[ComponentDetailPage.tsx](../../../../frontend/src/componentRepo/ComponentDetailPage.tsx)；读取编排：[useComponentDetailData.ts](../../../../frontend/src/componentRepo/useComponentDetailData.ts)；权限与写操作：[useComponentDetailMutations.ts](../../../../frontend/src/componentRepo/useComponentDetailMutations.ts)；纯展示：[ComponentDetailPresenters.tsx](../../../../frontend/src/componentRepo/ComponentDetailPresenters.tsx)
- 上传入口：[ComponentImportPage.tsx](../../../../frontend/src/componentRepo/ComponentImportPage.tsx)
- Import 历史/状态：[ComponentImportHistoryPage.tsx](../../../../frontend/src/componentRepo/ComponentImportHistoryPage.tsx)、[ComponentImportStatusPage.tsx](../../../../frontend/src/componentRepo/ComponentImportStatusPage.tsx)
- Candidate 工作台：[ComponentCandidateWorkbenchPage.tsx](../../../../frontend/src/componentRepo/ComponentCandidateWorkbenchPage.tsx)
- 稳定兼容入口：[componentRepoApi.ts](../../../../frontend/src/componentRepo/componentRepoApi.ts)；DTO：[componentRepoTypes.ts](../../../../frontend/src/componentRepo/componentRepoTypes.ts)；鉴权请求、路径与完整分页：[componentRepoTransport.ts](../../../../frontend/src/componentRepo/componentRepoTransport.ts)；领域调用位于 [api](../../../../frontend/src/componentRepo/api)

`componentRepoApi.ts` 仅重导出稳定名称。目录/Group/Star/Watch/Feed、Component/Version、Workbench、Import/Storage、Task
轮询分别由领域文件维护，页面现有 import 路径保持兼容。

## 3. Component 目录、详情与元数据

### 3.1 目录

`GET /api/v1/components?limit&cursor&locale&query&category&status`

`Service.ListComponents` 返回 actor 自有和公开可见 Component。owner 可读取自己的 Draft/active；非 owner 只读取
active 且至少存在一个非 Draft Version 的 Component。official Component 选择 reviewed translation；user 内容保持
原文。owner 与公开 active 两个互斥来源分别使用 `(updated_at DESC,id DESC)` keyset，并各自在合并前截到一页；最终页
固定后才选择展示翻译、聚合页内 Star 并投影当前 actor 的 Star/Watch。opaque cursor 同时冻结排序边界和
locale/query/category/status，筛选改变时旧 cursor 返回 validation error。

响应为 `{items,nextCursor}`。目录不计算 exact total，已经删除 `CountVisibleComponents`，因此每页只有一个列表 SQL
快照。完整 UUID 使用等值路径；其他输入保留名称、部分 ID 和 reviewed official translation 的 contains 搜索。

### 3.2 详情

`GET /api/v1/components/:componentId?locale`

`GetVisibleComponent` 在一条查询中执行可见性、展示翻译、逻辑尺寸、Star 状态/计数和 active Watch 投影。非 owner 对
不可见对象得到稳定 not-found，不泄露对象是否存在。Preview stale/failed 不改变 Component 可见性。

详情操作由服务端返回的 `ownedByActor` 投影决定显示：本人 Component 不显示 Star 和 Star 数量，显示验证/发布；Component
删除放在发布按钮右侧的更多菜单内，确认和服务端 owner 校验保持不变。别人的 Component 才显示 Star；Watch 仍遵守既有资格。
连接点、关系和 external interface 属于 Candidate 工作台审核面，详情页不请求也不展示这些数据。

### 3.3 创建与更新

Component 没有独立公开创建接口。新建上传完成后，`component.import.parse` Go Worker 在同一事务内创建
`Component -> Candidate -> Draft Version -> initial Preview Task`，避免留下没有来源链或没有初始结构版本的半成品。
`PATCH /api/v1/components/:componentId` 仅更新 owner、user、未删除 Component 的 name、description、tags、category
和 `contentLocale`；用户文本原样保存。内部 `Service.CreateComponent/CreateVersion` 只服务事务编排与隔离集成 fixture，
不注册 HTTP route。

后端核心代码：[component/handler.go](../../../../backend-go/internal/component/handler.go)、
[component/service.go](../../../../backend-go/internal/component/service.go)、[components.sql](../../../../backend-go/db/queries/components.sql)。

### 3.4 Group、收藏与公共 Feed 的统一筛选

三处页面复用 [ComponentSearchForm.tsx](../../../../frontend/src/componentRepo/ComponentSearchForm.tsx)，只在用户提交时
把 `name/componentId/widthStud/depthStud/heightPlate` 写入请求；页面内状态当前不持久化到 URL。名称按空白或中英文逗号
分词并要求全部 token 命中，ID 是独立 contains 字段，所有非空字段按 AND 组合。宽深允许旋转，单独填写宽或深时可命中
任一水平轴；宽深闭区间为 ±0.25 stud，高度固定轴闭区间为 ±0.625 plate，均对应 Part Search 的每轴 ±2 mm。

Handler 只解析结构化机器值，Service 完成长度、正数/有限值、去重和 LIKE 转义。Group 从 owner/membership 候选驱动，
Star 从当前 actor 的 Star 关系驱动，公共 Feed 从终态 Feed entry keyset 驱动；只有任一尺寸条件启用时，gated lateral 才
读取 `component_catalog_projection` 的当前展示 Version。Group 列表与状态 count 共享 `REPEATABLE READ READ ONLY` 快照，
Star 在同一窗口查询中得到 exact total，公共 Feed 不计算 count 且 cursor 绑定规范化后的完整筛选签名。官方 Component 的
名称筛选仍只选择 reviewed translation；公共 Feed 仅含 user Component，按用户原始名称筛选。

## 4. 创建与修订的异步主链路

### 4.1 安全上传

1. 前端计算文件 size/hash，调用 `POST /api/v1/component-imports/upload-sessions`；
2. Artifact Service 创建 owner-scoped session、pending Artifact metadata 和唯一 Storage object key；
3. 前端使用登录用户 Supabase token 直接上传 source/exchange，禁止 upsert；
4. 前端调用 `POST /api/v1/component-imports/upload-sessions/:sessionId/complete`；
5. 后端校验 session、对象 metadata/hash/size 与 owner，完成 Artifact verification，并持久创建 Import 和首个 Task；
6. complete 返回 202，浏览器结束上传交互，不在请求内等待解析。

Source 是不可变资产。Exchange 可以是 source，也可以是明确 `derived_from_artifact_id` 指向 source 的派生资产。
Storage key、bucket、owner 和数据库 Artifact 必须一致。

代码：[artifact/handler.go](../../../../backend-go/internal/artifact/handler.go)、
[artifact/service.go](../../../../backend-go/internal/artifact/service.go)、[artifacts.sql](../../../../backend-go/db/queries/artifacts.sql)。

### 4.2 Import 与 Worker

Go Worker 从 PostgreSQL 持久任务领取工作。主链包括 Artifact verify、Import parse、关系检测、Preview materialize 和关系清理；
解析成功写 SceneSnapshot、BOM、Candidate 和后续任务依赖。`component.import.parse` 与
`component.relations.detect` 均已由 Go Worker 执行，Component Repo 不再保留 Python 任务消费者。

Import API 的 GET 只读取已经提交的状态，不触发后台处理。任务错误保存稳定 `code + params`，locale/timezone 来自创建
时冻结上下文。状态页同时读取 Import 的 `taskId` 和 `previewTaskId`，把权威状态映射为“已上传 → 解析/BOM → 3D 预览”；
Task 读取失败只降级阶段细节，队列等待不伪装成算法精确百分比。解析器已去掉 `materializeImport` 中为调用
`scene.ExpandJSON` 产生的一次完整 Document JSON 编码/解码，改为 typed document 直接调用 `scene.Expand`；持久 Snapshot
仍保存完整来源结构，Worker/事务边界不变。

代码：[ingestion](../../../../backend-go/internal/ingestion)、[worker](../../../../backend-go/internal/worker)、
[task](../../../../backend-go/internal/task)、[go_task_protocol.md](../../../go_task_protocol.md)。

### 4.3 Candidate 到 Draft Version

Candidate 绑定 Import、SceneSnapshot 和 owner。Parse Worker 创建 Draft Version 时，在同一事务内验证：

- Candidate 属于 actor 且状态允许；
- Import 成功并以该 Component 为 target；
- SceneSnapshot/parser version 一致；
- source Artifact verified、immutable、未删除；
- exchange Artifact 若存在，也满足 owner、来源与验证规则；
- interface/structure/geometry hash 已生成。

通过后，Draft Version 冻结 Artifact、SceneSnapshot、Part Library、hash 和发布说明引用。Version 不是对 Import mutable
状态的实时视图。

## 5. Version 生命周期

| 接口 | 当前逻辑 |
|---|---|
| `GET /components/:componentId/versions` | owner 读取全部未删除 Version；非 owner 只读非 Draft；按创建时间倒序 OFFSET 分页 |
| `GET /component-versions/:versionId` | 使用 Component+Version 联合可见性读取 |
| `PATCH /component-versions/:versionId` | 只允许 owner Draft 更新 version/revision/releaseNote/locale |
| `DELETE /component-versions/:versionId` | 只软删除 owner Draft；published 历史不允许删除 |
| `POST /component-versions/:versionId/publish` | serializable 发布事务；deprecated 其他 published、设置 current、刷新尺寸、追加唯一事件，并创建 pending Feed entry 与图片任务 |
| `POST /component-versions/:versionId/deprecate` | owner user Version 状态转换；非法来源状态返回 conflict |
| `POST /component-versions/:versionId/archive` | owner user Version 状态转换；保留不可变来源链 |

发布不以 ValidationReport 或 Feed 图片作为强制门禁。发布事件、Version 状态、pending Feed entry 和持久图片任务同事务；重复或并发发布最多产生一个事件/entry。图片任务成功或重试终结后事件才进入公共 Feed，但图片结果不改变发布状态。实现见
[component_versions.sql](../../../../backend-go/db/queries/component_versions.sql)、
[component_domain_events.sql](../../../../backend-go/db/queries/component_domain_events.sql)、
[component_feed_entries.sql](../../../../backend-go/db/queries/component_feed_entries.sql)和
[component/service.go](../../../../backend-go/internal/component/service.go)。

## 6. Preview、BOM、Diff 与 Source

### 6.1 Preview

`GET /api/v1/component-versions/:versionId/preview` 是纯读：generator 过期返回 stale；ready 且 Artifact 存在时才签发
短期 URL。`POST .../preview/materialize` 只允许 owner 显式恢复/重建，复用 ready/succeeded 或 pending/running 任务，
failed、stale、对象丢失时增加 generation 并创建新任务。

Worker 从冻结 SceneSnapshot 和 Part Library 生成 GLB、计算 world-space AABB、stud/plate 逻辑尺寸及完整性，最后在
事务内 upsert Artifact 和 Version Preview 状态；若 Version 是 current，同时刷新 Component 规范化尺寸。
v6 生成器在单个 Part 几何内按折角生成顶点 `NORMAL`，并使用固定 `ldraw-studio-pbr-v1` 材质 Profile。Profile
由 Studio 2.0 `LDConfig.ldr` 的 148 个 `!COLOUR` 定义生成并提交到 Go 二进制，源码 SHA-256 固定在生成文件中；
运行时不读取服务器或客户端安装目录。每个材质写线性 base color、alpha、metallic/roughness 和稳定
`ldrawColorCode/materialClass/materialProfileVersion` extras，并按实际类别使用可选
`KHR_materials_ior`、`KHR_materials_specular`、`KHR_materials_clearcoat`、`KHR_materials_transmission` 和
`KHR_materials_emissive_strength`。当前类别为 plastic、glass、rubber、chrome、pearl、metal、luminous、glitter、
speckle；未知 code 使用中性塑料。扩展没有列入 `extensionsRequired`，因此普通 glTF 读取器仍能回退到核心 PBR/alpha。

Three.js 加载 v6 后使用预过滤 `RoomEnvironment`、Neutral tone mapping 和统一三点光；按材质类别设置环境反射，支持
physical transmission 时只使用 transmission，避免再乘兼容 alpha。详情页继续使用接触阴影，但不再为每个 mesh
附加黑色 `EdgesGeometry`，减少与 Studio 产品渲染不同的描边感。列表静态缩略图版本升级为
`glb-thumbnail-v2`，旧 IndexedDB 缓存因 key 变化自动失效。Version Diff 的颜色覆盖承担变化语义，不套用本摄影棚材质。

v5 及更早 ready Preview 不会被原地覆盖：读取时返回 stale，owner materialize 或已有
`backfill-component-preview-bounds.sh` durable 调度可生成 v6 Artifact。批量重建范围、速率和对象保留在部署验收时统一决定。

### 6.2 BOM

`GET /api/v1/component-versions/:versionId/parts?locale` 读取解析期持久化 BOM，不读取源文件重新解析。所有显式 root
实例递归展开后计数，并使用 Version 冻结的 Part Library 读取 reviewed Part translation、geometry status，以及当前生成器下
ready 且 Artifact 已 verified 的可选 `previewModel`。候选由 BOM refs 先固定，Part/geometry/preview/Artifact 均按冻结复合键或
Artifact ID 点查；服务端一次批量签名，前端只在卡片进入视口附近后使用共享 renderer 生成 WebP。缺失和签名失败仅显示占位图，
GET 不创建任务。

### 6.3 Diff

`GET /api/v1/component-versions/:versionId/diff` 仅 owner 可用。Go `componentdiff` 即时比较当前 Version 与 Import
冻结的 `base_version_id` SceneSnapshot；不创建 Task 或 Artifact。前端再加载前后两个已有 Preview 用于三维对照。

### 6.4 Source

`GET /api/v1/component-versions/:versionId/source` 先执行 Version 可见性，再验证 Artifact owner/bucket/key，最后使用
用户身份创建短期签名 URL。Source 与派生 GLB 使用不同来源语义，不互相替代。
详情页将这个入口称为“图纸源文件”，避免把 Studio/LDraw 模型误称为逐步拼搭说明书。

代码：[workbench](../../../../backend-go/internal/workbench)、[componentdiff](../../../../backend-go/internal/componentdiff)、
[artifact](../../../../backend-go/internal/artifact)。

## 7. Component 删除

`DELETE /api/v1/components/:componentId` 仅 owner user Component 可执行。事务取得 exclusive activity lock，写
`status=archived/deleted_at/deleted_by`，冻结 Watch 结束边界，并以 Component ID 作为幂等键创建
`component.relationships.cleanup` 任务。

提交后所有公开列表、详情、Star 和 Watch/Feed 立即通过可见性条件隐藏目标。Worker 分批关闭 active Watch、删除 Star。
Version、Import、Artifact、普通历史 Task 和 Storage object 按保留策略继续存在。

## 8. 数据模型和模块边界

| 数据对象 | 权威内容 |
|---|---|
| `components` | owner/content kind、用户源内容、状态、current Version、规范化当前逻辑尺寸、删除标记 |
| `component_translations` | official reviewed translation；不存用户自动翻译 |
| `component_reviewed_translations` | Goose v24 的只读审核翻译投影；所有 Component/Group/Star/Watch 用户读取共用 |
| `component_catalog_candidates` | Goose v24 的轻量候选投影；统一删除边界与任意/公开 Version 资格，Count/搜索/分页不连接 Version 展示数据 |
| `component_catalog_projection` | Goose v24 的只读展示投影；在固定页面后统一当前 Version / Draft 展示尺寸 |
| `component_versions` | 不可变来源引用、SceneSnapshot、Part Library、hash、状态、Preview 与发布说明 |
| `scene_snapshots` | 解析后冻结结构和 BOM 输入 |
| `artifacts` | source/derived 元数据、owner、Storage key、hash、验证和生命周期 |
| `component_feed_entries` | 发布事件的 pending/ready/fallback 展示准入、图片任务/Artifact 与首次 `available_at` |
| `imports/candidates` | 上传解析和审核工作流状态 |
| `tasks/task_jobs/task_dependencies` | 持久执行、重试、依赖和恢复 |

HTTP 模块按职责分为 `component`（Component/Version/Group/Star）、`componentwatch`、`artifact`、`ingestion`、
`workbench`、`task`。所有持久化使用 sqlc+pgx；迁移由 Goose 管理 `component_repo` schema。

## 9. 权限与国际化

- actor 来自 JWT；owner 权限不从浏览器缓存推断。
- user-authored name/description/tags/releaseNote 原样保存并携带 `contentLocale`。
- official Component/Part 只使用 reviewed translation，缺失时返回 source 和 missing 标记。
- 机器状态、ID、hash、Storage key、任务类型和 JSON 字段不翻译。
- 公共错误与任务失败只暴露稳定 `code + params`。
- Preview/Source 签名 URL 不能绕过 Component/Version 可见性和 Artifact owner/key 检查。

## 10. 测试定位

- Component/Version/Group/Star 主集成：[service_test.go](../../../../backend-go/tests/integration/component/service_test.go)
- Component 目录十万行计划：[component_catalog_test.go](../../../../backend-go/tests/performance/component/component_catalog_test.go)
- HTTP 与认证契约：[component_test.go](../../../../backend-go/tests/integration/httpapi/component_test.go)
- 上传与 Storage：[artifact](../../../../backend-go/internal/artifact)、[storage](../../../../backend-go/internal/storage)
- Import/Worker：[ingestion](../../../../backend-go/internal/ingestion)、[worker](../../../../backend-go/internal/worker)
- Import 解析基准：[import_parser_test.go](../../../../backend-go/internal/ingestion/import_parser_test.go)
- Version BOM 缩略图 SQL 计划：[version_parts_test.go](../../../../backend-go/tests/performance/workbench/version_parts_test.go)
- Schema/迁移：[schema_test.go](../../../../backend-go/tests/integration/database/schema_test.go)、[migrations](../../../../backend-go/db/migrations)
- 前端 API adapter：[componentRepoApi.test.ts](../../../../frontend/src/componentRepo/__tests__/componentRepoApi.test.ts)
- Import 三阶段 UI：[ComponentImportStatusPage.test.tsx](../../../../frontend/src/componentRepo/__tests__/ComponentImportStatusPage.test.tsx)
- Group 候选完整性与续页：[ComponentGroupControls.test.tsx](../../../../frontend/src/componentRepo/__tests__/ComponentGroupControls.test.tsx)
- 材质 Profile、GLB 扩展和前端摄影棚运行时：[catalog_test.go](../../../../backend-go/internal/ldrawmaterial/catalog_test.go)、[task_handlers_test.go](../../../../backend-go/internal/workbench/task_handlers_test.go)、[studioPreviewRendering.test.ts](../../../../frontend/src/preview/__tests__/studioPreviewRendering.test.ts)
- 页面与 i18n：[localizedPages.test.tsx](../../../../frontend/src/i18n/__tests__/localizedPages.test.tsx)

2026-09-14 的 03/04/08 清理新增 v24 迁移、目录 cursor 单元/集成测试和十万行 `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)`
门禁。数据为 100,000 个 Component：90,000 active、10,000 archived、10,000 official、5,000 条 reviewed zh-CN
翻译，测试 actor 拥有 1,000 条；另测空 actor。查询 fixture 直接写迁移维护的资格事实，业务集成另行锁定
`false/false -> true/false -> true/true` 的无 Version、Draft、Published 状态转换。

迁移完成 up/down/up 往返；所有场景均无 Version 全表扫描或磁盘 spill。无筛选和深 cursor 使用排序索引，选择性名称与
reviewed translation 使用各自 trigram GIN；高命中名称/翻译允许 PostgreSQL 在 100,000 条包络内选择顺序扫描。
PostgreSQL 14.17、`shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB` 的 warm-cache 结果如下；
这些时间只证明本地查询形状，不是生产 SLO。

| 场景 | 执行时间 | 计划结论 |
|---|---:|---|
| 无筛选 / category | 0.568 / 0.365 ms | owner/active 排序索引驱动，搜索分支 `never executed` |
| 选择性名称 / 高命中名称 | 18.455 / 7.480 ms | 选择性路径使用 source trigram；高命中由规划器选择顺序扫描，无 spill |
| 选择性翻译 / 高命中翻译 | 5.294 / 44.810 ms | 选择性路径使用 reviewed translation trigram；高命中扫描 100k Component 包络，无 spill |
| 完整 UUID | 0.111 ms | Component 主键等值路径 |
| 第 80,001 条 cursor / 空 actor | 0.263 / 0.202 ms | 无 OFFSET；深边界进入排序索引，空 actor 不执行无关内层 |

2026-09-19 的 BOM 缩略图门禁使用 PostgreSQL 14.17、24,000 个 Part/geometry/preview/Artifact、1,000 条 reviewed
translation 和单 Version 1,000 个 distinct BOM refs；`shared_buffers=128MB`、`work_mem=4MB`、
`effective_cache_size=4GB`，数据已 ANALYZE。warm-cache 结果只证明查询形状，不代表生产 SLO：

| 场景 | 执行时间 | 计划结论 |
|---|---:|---|
| 无 Preview | 4.598 ms | BOM refs 驱动，Part/geometry/translation 均为键索引点查 |
| 500 个 ready Preview | 5.141 ms | Preview/Artifact 只对命中项作 LATERAL 点查，无全表扫描 |
| 1,000 个 ready Preview | 5.792 ms | 全 enrichment 仍无 Seq Scan、temp 或磁盘 spill |
| 1,000 个缺失 Part ref | 1.353 ms | Part 主键探测后快速结束，后续 enrichment 不执行 |

同日 Apple M2 上对仓库 `test.io`（210 个 Part）的 `BenchmarkMaterializeImportTrackedStudioFixture` 连跑 5 次：
移除 Document JSON 往返前约 4.91～5.03 ms/op、3.87～3.89 MB/op、42,920 allocs/op；修改后约
2.34～2.37 ms/op、2.79～2.82 MB/op、27,183～27,185 allocs/op。本地 fixture 显示约 52% 时间和 28% 内存下降，
只作为解析热点证据，不外推生产吞吐或队列 SLO。

前端 i18n、测试、构建和 Go 结果见迁移进度。

## 11. 已发现的偏移与清理准备

### 11.0 详情页体验调整实施前记录（2026-09-19）

- 详情页连接分析属于 owner Candidate 审核能力，不是已发布 Version 的核心阅读信息。本轮详情页停止请求和展示 relation、
  connector 与 external interface；能力和接口继续保留在 Candidate 工作台，不删除领域数据或公共 API。
- BOM 缩略图继续由不可变 Part Preview GLB 派生。`GET .../parts` 只投影当前 generator 已 ready、Artifact 已 verified 且未删除的
 模型定位符，Storage key 不出 API；服务端对当次 BOM 中的可用对象批量签名，前端进入视口附近后才使用共享单 WebGL renderer
  生成静态 WebP。缺失/签名失败只显示既有占位图，GET 不调度 Part Preview 任务。
- BOM 查询由 SceneSnapshot 中已经持久化的 `bom` 键集合驱动。数量随单个 Version 的 distinct Part 类型增长，通常远小于实例总数，
  但不能把当前样例规模当成 API 硬上限。候选先由 `unnest(ldraw_part_nums)` 固定，再以冻结
  `(part_library_version_id,ldraw_part_num)` 主键点查 Part、geometry、preview 和 Artifact；translation 仅按同一冻结库、Part 编号、
  locale、reviewed 状态点查。没有搜索、排序分页或 exact count，`ORDER BY` 仅稳定 BOM 编号；缩略图 enrichment 不得驱动全库扫描。
  性能验收至少覆盖无 Preview、部分 ready、全部 ready 和缺失 geometry，并检查 preview/Artifact/translation 内层均由键索引探测。
- 上传完成后的聚合处理仍以 Import、Parse Task 和 Preview Task 为权威。UI 只把 durable 状态映射为“已上传 → 解析/BOM → 3D 预览”
  三阶段，不保存最终进度句子，也不把队列等待时间伪装成算法精确进度。任务 code/percent 若存在则继续按结构化协议展示。
- 解析性能优化先以真实 `.io/.ldr/.mpd` fixture 基准定位。首个低风险候选是移除 `materializeImport` 为调用 `scene.ExpandJSON`
  产生的 Document JSON 编码/解码往返，直接构造 typed scene document；源文件读取、Studio ZIP 解包和 GLB 物化保持 Worker 边界。
  若基准不能证明收益，则不据此宣称性能已经提升，并把流式解析/阶段并行化保留为后续独立清理项。
- 当前 Source API 返回不可变 Studio/LDraw 原始文件。本轮详情页增加可见下载入口，但明确为“图纸源文件”；它不是分页、分步骤的
  拼搭说明书。真正的说明书生成需要新的 Artifact 类型、持久任务、版本化导出上下文和独立验收，不能复用 Source 名称冒充。

### 11.1 03/04/08 实施前查询设计记录

- 驱动关系：全局 `components`，按至少 100,000 条验证；增长方向是跨 actor 增长。当前最多 1,000 用户，分别覆盖空 actor、
  少量自有 Component 和高占比公开 Component，不把 Star/Watch 的每 actor 1,000 条规划误当作 Component 总量上限。
- 候选来源：无文本搜索时 actor 自有候选从 `(owner_id,updated_at,id)` partial index 驱动，公开候选从
  `(updated_at,id) WHERE status='active' AND deleted_at IS NULL AND public_version_available` 驱动。文本搜索把 source name、
  partial UUID 和 reviewed translation 分成独立索引路径，再各自拆成 owner/public 来源；每个来源先截一页，最多
  `6 × (limit+1)` 行在内存中按 Component ID 去重并固定最终页面。
- 筛选选择性：无筛选、status/category 选择性筛选、UUID 精确匹配、名称高命中四类分别检查；名称模糊搜索不得依赖普通
  B-tree，必须通过搜索投影/索引，或保持在客观有界候选内。
- 稳定顺序：`updated_at DESC,id DESC`；不透明 cursor 同时冻结该边界和 locale/query/category/status，筛选改变时旧 cursor
  返回 validation error。第一页与最深 cursor 使用同一查询，不接受 page-number OFFSET 或隐藏结果上限。
- Count 决策：Component 目录交互不需要 exact total；API 删除 `total/totalPages/page`，返回 `items/nextCursor`。因此不再运行
  独立 Count，也不存在 Count/List 两次 `READ COMMITTED` 快照不一致。一次列表语句内的页面和 enrichment 共用单一快照。
- enrichment：先固定 Component ID 页面，再读取 reviewed translation、当前尺寸、Star/Watch 和页内 Star 聚合；不在全候选
  上执行逐行展示聚合。共享 candidate projection 固化删除状态与任意/公开 Version 可用性，catalog projection 只在固定页
  补当前展示尺寸；两者均不吸收 actor/locale；
  Version 的 insert/delete/status/component_id 变化由数据库触发器同步两个资格布尔值。
- 索引成本：替换原 owner 排序索引并新增带 `public_version_available` 谓词的 active partial 排序索引；名称、ID text 和
  reviewed translation 名称各有与 contains 谓词对应的 trigram GIN。代价是 Component/翻译写入维护 B-tree/GIN，Version
  变更另执行一次同 Component 的资格刷新；这些索引和触发器只服务已记录的查询与共享事实，不作为推测性索引。

| 编号 | 证据与问题 | 影响 | 清理前置条件 |
|---|---|---|---|
| COMPONENT-CLEAN-01（已关闭） | `listComponentVersions` 逐页读取裸 `items` 到短页终点，再对完整集合应用可选 status；adapter 测试覆盖第 101 个 Version | 不再因首个 100 条页面静默遗漏历史或 Draft | 关闭证据：`componentVersionApi.ts`、`componentRepoApi.test.ts` |
| COMPONENT-CLEAN-02（已关闭） | Group 当前成员逐页读全；候选按自有、收藏、现有成员三个服务端分页来源合并，UI 提供明确“加载更多” | 第 101 条之后的成员和收藏候选可继续发现，保存差异基于完整 membership baseline | 关闭证据：`componentCatalogApi.ts`、`ComponentGroupControls.tsx`、101 条 UI 测试 |
| COMPONENT-CLEAN-03（已关闭） | `ListComponents` 已删除独立 Count，只用一个 SQL 固定页并完成 enrichment；响应不再暴露 exact total | rows 不再与另一快照的 total 冲突，授权和筛选谓词只有一个读取入口 | 关闭证据：`components.sql`、cursor/Service 集成测试和十万行计划门禁 |
| COMPONENT-CLEAN-04（已关闭） | Component 目录已改为 `(updated_at DESC,id DESC)` opaque keyset，cursor 绑定 locale/query/category/status | 深页不再线性跳过历史行，且没有固定首 N 代表完整集合 | 关闭证据：第 80,001 条 cursor 计划无前置行过滤、API adapter 和稳定续页测试 |
| COMPONENT-CLEAN-05（已关闭） | 目录页保留列表控制，Group、上传和 presenter 已拆出；详情页保留页面组合，读取、mutation/权限和 presenter 已拆出 | 页面副作用边界可单独验证；目录/详情控制器均约 800 行，其余按职责独立 | 关闭证据：上述前端代码索引、Group UI 测试及全量前端测试 |
| COMPONENT-CLEAN-06（已关闭） | 原巨型 adapter 已拆为 DTO、统一鉴权 transport 以及 catalog/version/workbench/import/task 五个领域模块；原文件只做兼容重导出 | 上传、任务、映射和目录调用不再共处一个实现文件，调用方 import 契约保持不变 | 关闭证据：`componentRepoApi.ts` 7 行、`componentRepoTransport.ts` 和 `api/`；全量编译通过 |
| COMPONENT-CLEAN-07（已关闭） | Web/CLI/维护入口均未调用拆分创建接口；公开 `POST /components` 与 `POST /components/:id/versions` 已移除，Import Parse Worker 保持原子创建 Component/Candidate/Draft/Preview Task | 不再存在绕过来源链或产生半成品 Component 的第二入口 | 关闭证据：Handler route、HTTP 404 契约测试、Parse Worker 原子事务及 API 文档 |
| COMPONENT-CLEAN-08（已关闭） | v24 `component_catalog_candidates` 统一删除与 Version 资格，`component_catalog_projection` 统一页内展示尺寸，`component_reviewed_translations` 统一 official reviewed 边界；Component、Group、Star、Watch 及公共 Feed 已切换 | 共享资格规则有一个 Goose 权威定义，候选查询不会提前执行 Version 展示点查，各查询只保留 actor、locale、筛选和分页职责 | 关闭证据：v24 up/down/up、三项 schema view 契约、跨模块集成测试及十万行计划；Version 资格由触发器维护的持久布尔值驱动 |
| COMPONENT-CLEAN-09（已关闭） | Group、收藏和公共 Feed 共用 Part Search 风格的名称、Component ID、宽/深/高结构化表单；所有非空字段按 AND 组合，宽深可旋转并沿用每轴 ±2 mm | 三个列表的同名控件具有相同请求字段、容差、提交和空态语义 | 关闭证据：共享 `ComponentSearchForm`、三条 API/SQL、cursor 筛选签名、集成/API/i18n 测试与查询计划门禁 |
| COMPONENT-CLEAN-10 | v6 已覆盖版本化颜色表、材质类别、折角法线和 glTF PBR 扩展，但 `collectLDrawTriangles` 仍只输出几何；Part 内部 16/24 颜色继承、直接色、多材质、BFC/TEXMAP 和印刷纹理尚未进入 Component GLB | 纯色普通砖显著接近 Studio，印刷、多色、贴图和特殊 BFC 模型仍可能偏差 | 扩展 triangle material identity 与 mesh primitive 分组；为 16/24、direct color、BFC、TEXMAP/printed fixture 分别建立 GLB validator 与 Studio 视觉基准后关闭 |
| COMPONENT-CLEAN-11（已关闭） | 详情页已停止连接读取；BOM 返回可选 ready `previewModel` 并按视口生成缩略图；Import 展示三个 durable 阶段；本人不显示 Star，发布右侧更多菜单承载删除 | 阅读页不再承担 owner 审核请求，零件可识别、长任务有恢复友好的阶段反馈，删除降为次级操作 | 关闭证据：详情/状态页与 presenter、BOM Service/SQL 集成和 24,000 Part 计划门禁、双语/i18n、前端全量测试；解析 typed document 基准另证明热点收益 |
| COMPONENT-CLEAN-12 | 当前 Source 是 Studio/LDraw 模型源文件，没有逐步拼搭说明书 Artifact | 若直接称为“说明书/图纸”会误导用户对文件内容的预期 | 本轮只提供明确的图纸源文件下载；另立产品设计确定步骤拆分、版式、PDF/图片产物、导出 locale 与 Worker 性能门禁后才能关闭 |

01～09、11 已关闭。10 依赖多材质/BFC/TEXMAP 的独立实现和视觉基准；12 等待逐步拼搭说明书产品设计。
