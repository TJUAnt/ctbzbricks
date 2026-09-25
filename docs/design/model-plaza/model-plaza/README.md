# 组件广场详细设计

> 功能需求：[模型广场 / 模型广场](../../../requirements/model-plaza/model-plaza/README.md)
>
> 代码核对日期：2026-09-16
>
> 当前阶段：广场壳层已从个人仓库页面拆出，公共与个人订阅页签共用大图事件卡片；Cycles 优先/Go raster fallback 派生图片与 Docker 生产封装已在仓库实现。真实 Supabase 与仓库 schema head 均为 v24；Go API/前端发布、renderer v4 / Component Preview v6 的服务器运行与浏览器验收待统一执行。

## 1. 模块边界

组件广场对应用户可访问链接 `/model-plaza`，统一承载组件发布动态浏览。页面包含两个页签：

| 页签 | 地址 | 成员资格 | 详细领域设计 |
|---|---|---|---|
| 公共 | `/model-plaza` | 全部当前公开可见的用户 Component 发布事件，不考虑当前 actor 是否 Watch | [公共 Feed](../../../component_repo/public_feed.md) |
| 个人订阅 | `/model-plaza?tab=subscriptions` | 当前 actor active Watch 对应的窗口内发布事件 | [Watch](../../my-models/component-repo/watch.md) |

未知或缺失的 `tab` 参数回到公共页签。页签使用 URL 而非只存在于 React 内存的状态，因此刷新、浏览器前进后退和分享链接都能恢复相同页面。

`/component-repo/watches` 是订阅关系管理链接，只负责搜索、续页和取消订阅；发布动态已从该页面移除。个人订阅页签提供“管理订阅”入口返回该管理页。

## 2. 前端逻辑与调用

### 2.1 公共页签

`ComponentPlazaPage` 独立识别默认页签并请求 `listComponentPublicFeed`，不创建个人仓库的 Group、上传、Version
或收藏列表状态。事件按游标追加，由
`ComponentPublicFeedCard` 展示发布人、事件版本的 Worker 3:2 派生图片、Component 描述和发布说明。图片由 Go 持久任务优先调用 Blender 4.1 Cycles 离线生成，外部渲染失败时使用 Go raster 快速 fallback；pending 事件本次不返回，ready/fallback 终态都进入流。详细准入、渲染、Star 和
空状态见[公共 Feed 设计](../../../component_repo/public_feed.md)。
卡片 Star 操作复用 `ComponentStarButton`，以现有 typed Star/Unstar key 提供随状态变化的双语 `aria-label`，
并保留原生按钮的 Enter/Space 键盘语义。

### 2.2 个人订阅页签

`ComponentWatchFeedPanel` 挂载后默认读取最近 30 天，可切换 7/30/90 天。首屏调用
`listComponentWatchFeed({since,limit})`；后续页只发送服务端不透明 cursor，继续使用 cursor 冻结的窗口。
底部哨兵进入视口附近时自动续页，同时保留按钮作为无 `IntersectionObserver` 环境和失败重试入口。

页面切换 locale 或时间窗口时废弃旧请求并重载首屏；cursor 页面按事件 ID 去重。个人页签直接复用
`ComponentPublicFeedCard`，与公共页签保持相同的 3:2 大图、发布人、组件描述、发布说明、Star 和详情入口。
事件名称和发布说明保持 API 返回的用户原文或 reviewed official translation，日期通过统一 locale formatter 展示。

### 2.3 订阅管理

`ComponentWatchListPage` 保持独立链接，并作为“已订阅 Component Repo”的权威列表页。列表概要、名称、分类、
当前版本、订阅时间、搜索与 cursor 续页全部复用现有 `listComponentWatches`；取消订阅复用
`unwatchComponent`，不增加聚合概要接口或前端 first-N 假完整集合。取消订阅后，下次进入或刷新个人订阅页签时
由后端 read-time 语义重新计算成员资格，不跨路由维护一份共享的临时 Feed 副本。

## 3. HTTP、后端与持久化边界

### 3.1 个人订阅卡片投影性能预检（2026-09-15）

本次清理保持个人 Feed 的候选集合、时间窗口和 keyset 排序不变，只在页面事件固定后补齐与公共卡片一致的
发布人、Component 描述、Star 和终态派生图片投影。驱动关系仍是当前 actor 的 active Watch，规划上限为
1,000 条/actor；closed Watch 只追加历史，不能进入候选。发布事件随版本发布持续增长，查询先以
`occurred_at >= window_start` 和 `(occurred_at,event_id)` cursor 从每个已订阅 Component 的事件索引取最多
一页候选，再做全局 `ORDER BY occurred_at DESC,event_id DESC LIMIT page_size`。

个人 Feed 没有文本筛选或 exact count；首屏和续页不要求与另一次查询共享快照。公共 Feed 提供与个人仓库一致的
名称、Component ID、宽/深/高结构化 AND 筛选，cursor 绑定筛选签名，但仍不执行 exact count。Component 翻译、每页 Star
聚合、当前 actor Star 状态、Feed entry 与 Artifact 元数据只能读取已经固定的页面 ID；Feed entry 必须是
`ready/fallback` 且 `available_at` 非空，pending 不进入页面。图片 URL 在 SQL 完成后按当页 Storage key 一次
批量签发，签名失败只把对应卡片降级为无图，不改变发布成功和 Feed 成员资格。验证必须复跑现有
1,000 active Watch/actor、1,000,000 closed period 的首屏、宽窗口、深 cursor 和空 actor 计划门禁，确认新增
节点没有扫描 closed history、没有逐历史事件聚合、没有 spill；本地时间只证明查询形状。

当前后端契约：

- 公共页签：`GET /api/v1/component-public-feed?name&componentId&widthStud&depthStud&heightPlate`，由 v23 终态 Feed entry 部分索引驱动；
- 个人订阅：`GET /api/v1/component-watch-feed`，由 actor active Watch 索引驱动，响应复用公共事件卡片投影；
- 订阅管理：`GET /api/v1/component-watches` 与 `DELETE /api/v1/components/:componentId/watch`。

公共 Feed 按 `(available_at DESC,event_id DESC)` 续页并显示 `occurred_at`；个人 Feed 按事件时间续页。两者只在
`component_feed_entries` 已达到 `ready/fallback` 终态后返回事件，并批量签发当页图片 URL。两者都不执行 exact count，但成员资格不同。前端页签
不能把两类结果合并或用 Watch 过滤公共 Feed。SQL、权限、事件和性能证据分别由公共 Feed 与 Watch 文档维护。

## 4. 权限与 i18n

- 三个接口都使用 JWT actor；公共 Feed 的 actor 只影响 Star/Watch 展示投影，个人订阅 Feed 和管理列表按 actor 隔离。
- `tab=subscriptions` 是稳定路由机器值，不翻译；页签、管理入口、加载和空状态使用 typed semantic keys。
- 当前资源版本为 `frontend-2026.09.25.1`，生产 locale 为 `zh-CN/en-US`；公共筛选字段和尺寸提示使用 typed semantic
  keys，没有新增 locale 分支。
- Component 名称、描述、Release Note 与 locale 分类不因页面迁移改变。

## 5. 代码索引

| 层 | 代码 |
|---|---|
| 广场壳层与页签 | `frontend/src/componentRepo/ComponentPlazaPage.tsx`、`ComponentSearchForm.tsx` |
| 个人仓库壳层 | `frontend/src/componentRepo/ComponentRepoPage.tsx` |
| 公共事件卡片 | `frontend/src/componentRepo/ComponentPublicFeedCard.tsx`、`ComponentStarButton.tsx`、`componentPublicFeed.ts` |
| 个人订阅 Feed | `frontend/src/componentRepo/ComponentWatchFeedPanel.tsx` |
| 订阅关系管理 | `frontend/src/componentRepo/ComponentWatchListPage.tsx` |
| API adapter / DTO | `frontend/src/componentRepo/componentRepoApi.ts`、`componentRepoTypes.ts` |
| Watch 卡片投影 | `backend-go/internal/componentwatch/service.go`、`types.go`、`backend-go/db/queries/component_watches.sql` |
| 路由配置 | `frontend/src/main.tsx`、`frontend/src/app/appConfig.json` |
| 样式与资源 | `frontend/src/styles.css`、`frontend/src/i18n/resources/*/componentRepo.json` |
| Worker / Renderer | `backend-go/internal/feedrender/`、`backend-go/internal/ldrawmaterial/`、`backend-go/cmd/worker/main.go`、`scripts/start-feed-render-worker.sh`、`scripts/start-feed-render-worker.ps1`、`Dockerfile.feed-render`、`compose.production.yml` |
| 浏览器摄影棚 | `frontend/src/preview/studioPreviewRendering.ts`、`glbThumbnailRenderer.ts`、`frontend/src/parts/PartViewerPage.tsx` |
| 测试 | `frontend/src/i18n/__tests__/localizedPages.test.tsx`、`ComponentPlazaBoundary.test.ts`、`ComponentWatchListPage.test.ts`、`ComponentStarButton.test.tsx`、`componentPublicFeed.test.ts`、`backend-go/tests/integration/component/service_test.go`、`backend-go/tests/performance/component/watch_list_test.go` |

## 6. 验证证据

2026-09-12 已验证前端 typed i18n、事件投影、ready 图片/fallback 占位和生产构建；v23 隔离 PostgreSQL
迁移往返、任务终态触发器及 100,000 事件/entry 查询计划通过。详细计时见[公共 Feed 设计](../../../component_repo/public_feed.md)。
个人订阅页签继续复用 Watch 的 1,000 active/actor 与 1,000,000 closed period 计划证据。2026-09-12 真实
Supabase 从 v20 升级到 v23，2 条已有用户发布事件均回填为 fallback；真实 Go API readiness 和公共 Feed
请求返回 200。2026-09-13 同一黄色跑车 v4 GLB 已由 Blender 4.1 Cycles 完成 1200×800/128 samples
本地真实渲染；v4 材质 sidecar 通过正式 Go Worker 集成边界，约 46.6 秒。该结果是实现证据，不代表 v4 已部署。
Component GLB v6 与 Three.js 摄影棚已通过完整 Go 与前端门禁；Python legacy 测试已经从当前完成门禁移除；
最终全量测试结果以迁移进度文档为准；
Linux/amd64 API、通用/GLB Worker 与 Feed Render Worker 的镜像及单机 Compose 已完成仓库封装，通用 Worker
不会与专用 Feed Worker 竞争渲染任务，API 不接收 server-side Storage 密钥。真实任务产生 v4 Artifact、
浏览器卡片、容器构建和资源成本仍待联合验收。

2026-09-15 本轮前端 `i18n:check`、23 个测试文件/100 项测试和生产构建通过，Go `make check` 通过；隔离
PostgreSQL 14.17 完成 `0 -> v24 -> v23 -> v24`、重复 up 和完整集成契约。计划数据包含 1,000,000 条 active
Watch、1,000,000 条 closed period 和 92,700 条终态 Feed entry；首屏、宽窗口、90 天窗口、深 cursor 与空
actor 均从 active Watch 和 Component/time 事件索引驱动，页面固定后的 21 次 Star 聚合使用
`component_stars_component_idx`，没有 Watch/Feed 全表扫描、OFFSET 或磁盘 spill。选择性窗口为 5.334 ms，
其余时间只作为本机 warm-cache 查询形状证据。

同日真实 Supabase PostgreSQL 17.6 从 Goose v23 升级到 v24，重复 `up` 无操作。升级前在同一
`REPEATABLE READ, READ ONLY` 快照中保存 22 个 Component、23 个 Version 及受影响 schema 元数据，恢复包位于
`/Users/dujun/Documents/ctbzbricks-backups/watch-plaza-v24-20260915T144233Z-pre-migration`，13 个文件均通过
SHA-256 复核。升级后 Component/Version 数量守恒，三个共享投影分别返回 11/11/0 行，资格回填差异为 0，
5 个目标索引有效且触发器启用；queued/running task、非终态 Feed entry、非法终态、无效索引和长事务均为 0。
全库唯一未验证约束属于 Supabase `realtime.messages`，与 Goose v24 无关。当前 Watch Feed 权威 SQL 随后在生产
空 actor 上完成 `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)`：actor active index 驱动，其他节点不执行，执行
1.786 ms；这验证查询可预编译，不代表非空 Feed 的生产 SLO。

## 7. 清理项

| 编号 | 证据与影响 | 依赖阶段与关闭条件 |
|---|---|---|
| PLAZA-CLEAN-01（已关闭） | `ComponentRepoPage` 曾同时持有个人仓库与公共广场状态 | 2026-09-15 已拆出 `ComponentPlazaPage`，路由和边界测试确认广场不再依赖 Group、上传或 Version 管理 |
| PLAZA-CLEAN-02（代码已关闭，视觉待验收） | 两个页签曾使用不同卡片密度，个人接口也缺少图片、发布人与描述 | 2026-09-15 已统一 `ComponentPublicFeedCard` 和事件投影；隔离 SQL/功能/前端门禁通过，真实图片与响应式视觉留到联合验收 |
| PLAZA-CLEAN-03（已关闭） | 订阅管理与 Feed 需要清晰的职责和导航边界 | 产品确认保留独立管理链接；管理页以 `listComponentWatches` 为权威列表概要并复用既有 Unwatch API，不合并进 Feed 页签 |
