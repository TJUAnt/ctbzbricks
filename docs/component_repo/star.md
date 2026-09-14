# Component Repo Star 详细设计

> 代码核对日期：2026-09-13
>
> 当前阶段：STAR-1～STAR-3 核心能力已实现；产品容量按每 actor 最多 1,000 Star 规划。
>
> 接口权威定义：[Component Repo API](../api.md)；产品与容量决策：[Star 方案与路线](../design/lego_design/component_repo_star_design_and_roadmap.md)。

## 1. 职责和边界

Star 是 actor 对公开、非本人 Component 的个人收藏关系。它用于个人收藏列表和公开热度计数，不授予读取、下载、
编辑或分组权限，也不会自动创建 Watch。本人 Component 通过 root Group 表示，不允许 Star。

Star 只有当前关系，没有历史 period。Unstar 物理删除 actor 自己的关系；Component 删除后，列表先按可见性立即隐藏，
持久清理任务再删除残留关系。

## 2. 前端功能点

### 2.1 目录与广场收藏按钮

`ComponentRepoPage` 的个人仓库、收藏和广场共用一套列表。非 owner 行展示 Star 图标按钮：

1. 点击后先乐观翻转 `starredByActor` 和 `starCount`；
2. 在收藏视图中执行 Unstar 时立即移除该行，并同步调整 `total/relationshipTotal`；
3. 调用 `starComponent` 或 `unstarComponent`；
4. 成功后刷新当前列表和 Group 树；
5. 失败后显示结构化错误并重新读取，服务端状态覆盖乐观状态；
6. 当前页最后一条收藏被移除时，页码回退一页。

### 2.2 详情页收藏按钮

`ComponentDetailPage` 从 Component DTO 的 `starredByActor/starCount/ownedByActor` 决定按钮或只读计数。操作同样
乐观更新；失败时触发详情重载。按钮不对 owner 开放。

### 2.3 “我的收藏”列表

收藏是 `ComponentRepoPage` 内的 `libraryView=starred`，不是独立路由。页面调用 `listComponentStars`，支持页码、
名称/ID 或 Box 尺寸搜索、category 精确筛选，并固定 `sort=starred_at_desc`。返回：

- `total`：当前筛选后仍可见的收藏数；
- `relationshipTotal`：actor 的关系总数，删除清理完成前可能包含已隐藏关系；
- `starredAt`：收藏时间，用作列表排序和展示。

前端代码：

- 列表、乐观状态与筛选：[ComponentRepoPage.tsx](../../frontend/src/componentRepo/ComponentRepoPage.tsx)；Group 联动与续页：[ComponentGroupControls.tsx](../../frontend/src/componentRepo/ComponentGroupControls.tsx)
- 详情页按钮组合：[ComponentDetailPage.tsx](../../frontend/src/componentRepo/ComponentDetailPage.tsx)；权限、Star/Watch 乐观更新：[useComponentDetailMutations.ts](../../frontend/src/componentRepo/useComponentDetailMutations.ts)
- 稳定请求入口：[componentRepoApi.ts](../../frontend/src/componentRepo/componentRepoApi.ts)；目录/Star/Group 实现：[componentCatalogApi.ts](../../frontend/src/componentRepo/api/componentCatalogApi.ts)
- 路径配置：[appConfig.json](../../frontend/src/app/appConfig.json)

## 3. HTTP 接口与后端逻辑

### 3.1 Star

`PUT /api/v1/components/:componentId/star`

`component.Handler.star` 读取 JWT actor 并调用 `Service.Star`。Service：

1. 校验 Component UUID；
2. 开启 serializable transaction；
3. 取得 Component shared activity lock，与删除的 exclusive lock 建立顺序；
4. `GetComponentStarTarget` 从 v24 `component_catalog_candidates` 读取删除边界、owner、状态、公开 Version 可用性和既有关系；
5. owner 返回 `component_repo.star_own_component_forbidden`；
6. 已有关系直接返回首次 `starredAt`，不重复写入；
7. 新关系要求 Component active 且存在非 Draft Version；
8. `CreateComponentStar` 插入，`(actor_id,component_id)` 主键处理并发唯一性。

### 3.2 Unstar

`DELETE /api/v1/components/:componentId/star`

`Service.Unstar` 只按 actor+Component 删除；目标已不可见或关系不存在仍返回 204。它不需要先读取 Component，保证
用户在目标下线后仍能清理个人关系。Unstar 不改变 custom Group membership。

### 3.3 收藏列表

`GET /api/v1/component-stars?page&pageSize&locale&query&category&sort`

`Service.ListStars` 将 pageSize 限制在 1～100，sort 只接受 `starred_at_desc`。完整 `axb`/`axbxc` 搜索进入轴无关
逻辑尺寸模式，普通输入匹配展示名称或 Component ID。SQL：

1. `actor_stars` 先按 actor 物化权威候选；
2. 关联 v24 candidate projection，只保留 active 且存在非 Draft Version 的 Component；固定页面后再从 catalog projection 读取展示尺寸；
3. 从 `component_reviewed_translations` 读取唯一允许展示的 official translation；
4. 尺寸筛选直接读取 Component 当前规范化 `current_logical_size_a/b/c`；
5. 按 `starred_at DESC,component_id` 排序并用 OFFSET 分页；
6. 固定页后一次聚合页内 `starCount`，再读取展示用原始方向尺寸；
7. Count 查询返回过滤后 `total` 和未经可见性过滤的 `relationshipTotal`。

后端代码：

- Handler 与 Service：[handler.go](../../backend-go/internal/component/handler.go)、[service.go](../../backend-go/internal/component/service.go)
- Star SQL：[component_stars.sql](../../backend-go/db/queries/component_stars.sql)
- Component 展示投影：[components.sql](../../backend-go/db/queries/components.sql)
- v14 数据模型与旧 subscription 迁移：[00014_component_stars.sql](../../backend-go/db/migrations/00014_component_stars.sql)
- v17 删除生命周期：[00017_component_relationship_lifecycle.sql](../../backend-go/db/migrations/00017_component_relationship_lifecycle.sql)
- v18 规范化尺寸：[00018_component_current_logical_size.sql](../../backend-go/db/migrations/00018_component_current_logical_size.sql)
- v24 共享候选、展示与翻译投影：[00024_component_catalog_projection.sql](../../backend-go/db/migrations/00024_component_catalog_projection.sql)

## 4. DTO 投影和跨功能关系

Component 列表与详情都返回 `starredByActor` 和 `starCount`。Star 关系只参与展示：

- 不进入 Component 可见性判断；
- 不允许读取其他 actor 的收藏明细；
- 不因为加入 custom Group 而自动 Star；
- Unstar 不移除 custom Group membership；
- Watch 状态由独立关系投影，Star 操作不修改 Watch。

当前 Version Preview 成功时会写 Version 的方向尺寸；若它仍是 current Version，同事务刷新 Component 的轴无关
规范化尺寸。发布新 Version 也刷新该投影。Star 尺寸搜索因此不逐条计算 Version。

## 5. 权限、国际化和错误

- actor 只来自认证上下文，API 不接收 owner 或 recipient。
- user Component 文本保持原文；official 文本只选择请求 locale 的 reviewed translation。
- Star、Component ID、sort 和 category 是机器值；按钮、空态和错误使用 typed semantic keys。
- 结构化错误包括目标不存在、本人禁止收藏、目标不可收藏和通用 validation/conflict。
- 当前没有 Star 专属 Prometheus 指标；公开计数来自权威关系表。

## 6. 测试定位

- Service、SQL、并发、删除和列表语义：[service_integration_test.go](../../backend-go/internal/component/service_integration_test.go)
- HTTP 授权与 DTO：[component_integration_test.go](../../backend-go/internal/httpapi/component_integration_test.go)
- 百万关系与尺寸计划：[star_size_performance_integration_test.go](../../backend-go/internal/component/star_size_performance_integration_test.go)
- Schema 与迁移：[schema_integration_test.go](../../backend-go/internal/database/schema_integration_test.go)
- 前端 API adapter：[componentRepoApi.test.ts](../../frontend/src/componentRepo/__tests__/componentRepoApi.test.ts)
- Group 候选完整性与可见续页：[ComponentGroupControls.test.tsx](../../frontend/src/componentRepo/__tests__/ComponentGroupControls.test.tsx)
- 页面语言壳：[localizedPages.test.tsx](../../frontend/src/i18n/__tests__/localizedPages.test.tsx)

2026-09-14 的 Component 03/04/08 清理未改变 Star HTTP 合约；Star SQL 已改读 v24 candidate/catalog/reviewed translation 共享投影，
迁移往返、跨模块集成和十万 Component 查询计划通过。没有新增文案、资源键或 locale 分支；当前完整验证结果见迁移进度。

## 7. 已发现的偏移与清理准备

| 编号 | 证据与问题 | 影响 | 清理前置条件 |
|---|---|---|---|
| STAR-CLEAN-01（已关闭） | `ComponentRepoPage` 已移出 Group、上传和通用 presenter；详情 Star/Watch mutation 与权限投影进入独立 Hook | Star 列表、Group 候选和详情乐观状态不再集中在两个巨型页面中 | 关闭证据：页面与职责文件、现有 Feed/列表测试、Group 101 条 UI 测试 |
| STAR-CLEAN-02（已关闭） | DTO、统一 transport 和 catalog/version/workbench/import/task 领域调用已拆分，原 adapter 仅兼容重导出 | Star/Group 改动不再直接耦合上传、Storage 和任务轮询实现 | 关闭证据：`componentRepoTypes.ts`、`componentRepoTransport.ts`、`api/` 与前端全量编译 |
| STAR-CLEAN-03 | Count 与 List 是两个独立 SQL 调用，且重复可见性、translation 和尺寸谓词 | 默认 READ COMMITTED 下可能来自不同快照；人工同步谓词有漂移风险 | 产品先确认是否要求页与 total 同快照；若要求，改为单语句并重跑 100 万关系计划 |
| STAR-CLEAN-04 | 页码 OFFSET 是线性深翻页 | 当前 1,000 Star/actor 包络内已测且产品保留页码；扩大包络后不适用 | 保持现状；接近包络 70%、提高容量或批准交互变化时重开 keyset 设计 |
| STAR-CLEAN-05（已关闭） | 候选编辑器分页调用自有、Star 与现有成员搜索，合并去重并显示续页；完整 membership 另行逐页加载 | 超过 100 条时仍可搜索或续载收藏并加入 Group | 关闭证据：`listComponentGroupMembershipCandidates`、`ComponentGroupControls.test.tsx` |
| STAR-CLEAN-06 | 列表图标按钮主要依赖 `title`/`aria-pressed`，缺少完整键盘与双 locale 可访问性验证 | 辅助技术反馈可能不完整 | 补 typed `aria-label` 和键盘测试；对应 `STAR-A11Y-01` |
| STAR-CLEAN-07 | `relationshipTotal` 与 `total` 在删除清理窗口内有意不同，但同屏统计容易被误读 | UI 可能把物理关系量当作可见收藏量 | 明确产品展示是否需要 relationshipTotal；不需要时停止暴露，需保留则增加解释文案与契约测试 |

STAR-CLEAN-05 已先关闭，随后完成 01/02 的前端拆分。03、07 仍需要产品语义决定，04 只能在容量或交互条件触发后处理。
