# 组件广场详细设计

> 代码核对日期：2026-09-13
>
> 当前阶段：公共 Feed、Cycles 优先/Go raster fallback 派生图片、个人订阅 Feed 与 Docker 生产封装已在仓库实现；真实 Supabase 已部署到 v23，renderer v4 / Component Preview v6 的服务器部署、重建范围与浏览器验收待统一执行。

## 1. 模块边界

组件广场对应用户可访问链接 `/model-plaza`，统一承载组件发布动态浏览。页面包含两个页签：

| 页签 | 地址 | 成员资格 | 详细领域设计 |
|---|---|---|---|
| 公共 | `/model-plaza` | 全部当前公开可见的用户 Component 发布事件，不考虑当前 actor 是否 Watch | [公共 Feed](public_feed.md) |
| 个人订阅 | `/model-plaza?tab=subscriptions` | 当前 actor active Watch 对应的窗口内发布事件 | [Watch](watch.md) |

未知或缺失的 `tab` 参数回到公共页签。页签使用 URL 而非只存在于 React 内存的状态，因此刷新、浏览器前进后退和分享链接都能恢复相同页面。

`/component-repo/watches` 是订阅关系管理链接，只负责搜索、续页和取消订阅；发布动态已从该页面移除。个人订阅页签提供“管理订阅”入口返回该管理页。

## 2. 前端逻辑与调用

### 2.1 公共页签

`ComponentRepoPage` 识别默认页签后请求 `listComponentPublicFeed`。事件按游标追加，由
`ComponentPublicFeedCard` 展示发布人、事件版本的 Worker 3:2 派生图片、Component 描述和发布说明。图片由 Go 持久任务优先调用 Blender 4.1 Cycles 离线生成，外部渲染失败时使用 Go raster 快速 fallback；pending 事件本次不返回，ready/fallback 终态都进入流。详细准入、渲染、Star 和
空状态见[公共 Feed 设计](public_feed.md)。

### 2.2 个人订阅页签

`ComponentWatchFeedPanel` 挂载后默认读取最近 30 天，可切换 7/30/90 天。首屏调用
`listComponentWatchFeed({since,limit})`；后续页只发送服务端不透明 cursor，继续使用 cursor 冻结的窗口。
底部哨兵进入视口附近时自动续页，同时保留按钮作为无 `IntersectionObserver` 环境和失败重试入口。

页面切换 locale 或时间窗口时废弃旧请求并重载首屏；cursor 页面按事件 ID 去重。事件名称和发布说明保持
API 返回的用户原文或 reviewed official translation，日期通过统一 locale formatter 展示。

### 2.3 订阅管理

`ComponentWatchListPage` 只调用 `listComponentWatches` 和 `unwatchComponent`。取消订阅后，下次进入或刷新个人
订阅页签时由后端 read-time 语义重新计算成员资格，不跨路由维护一份共享的临时 Feed 副本。

## 3. HTTP、后端与持久化边界

当前后端契约：

- 公共页签：`GET /api/v1/component-public-feed`，由 v23 终态 Feed entry 部分索引驱动；
- 个人订阅：`GET /api/v1/component-watch-feed`，由 actor active Watch 索引驱动；
- 订阅管理：`GET /api/v1/component-watches` 与 `DELETE /api/v1/components/:componentId/watch`。

公共 Feed 按 `(available_at DESC,event_id DESC)` 续页并显示 `occurred_at`；个人 Feed 按事件时间续页。两者都不执行 exact count，但成员资格不同。前端页签
不能把两类结果合并或用 Watch 过滤公共 Feed。SQL、权限、事件和性能证据分别由公共 Feed 与 Watch 文档维护。

## 4. 权限与 i18n

- 三个接口都使用 JWT actor；公共 Feed 的 actor 只影响 Star/Watch 展示投影，个人订阅 Feed 和管理列表按 actor 隔离。
- `tab=subscriptions` 是稳定路由机器值，不翻译；页签、管理入口、加载和空状态使用 typed semantic keys。
- 本次资源版本为 `frontend-2026.09.12.2`，生产 locale 为 `zh-CN/en-US`。
- Component 名称、描述、Release Note 与 locale 分类不因页面迁移改变。

## 5. 代码索引

| 层 | 代码 |
|---|---|
| 广场壳层与页签 | `frontend/src/componentRepo/ComponentRepoPage.tsx` |
| 公共事件卡片 | `frontend/src/componentRepo/ComponentPublicFeedCard.tsx`、`componentPublicFeed.ts` |
| 个人订阅 Feed | `frontend/src/componentRepo/ComponentWatchFeedPanel.tsx` |
| 订阅关系管理 | `frontend/src/componentRepo/ComponentWatchListPage.tsx` |
| API adapter | `frontend/src/componentRepo/componentRepoApi.ts` |
| 路由配置 | `frontend/src/main.tsx`、`frontend/src/app/appConfig.json` |
| 样式与资源 | `frontend/src/styles.css`、`frontend/src/i18n/resources/*/componentRepo.json` |
| Worker / Renderer | `backend-go/internal/feedrender/`、`backend-go/internal/ldrawmaterial/`、`backend-go/cmd/worker/main.go`、`scripts/start-feed-render-worker.sh`、`scripts/start-feed-render-worker.ps1`、`Dockerfile.feed-render`、`compose.production.yml` |
| 浏览器摄影棚 | `frontend/src/preview/studioPreviewRendering.ts`、`glbThumbnailRenderer.ts`、`frontend/src/parts/PartViewerPage.tsx` |
| 测试 | `frontend/src/i18n/__tests__/localizedPages.test.tsx`、`ComponentWatchListPage.test.ts`、`componentPublicFeed.test.ts`、`backend-go/internal/feedrender/*_test.go` |

## 6. 验证证据

2026-09-12 已验证前端 typed i18n、事件投影、ready 图片/fallback 占位和生产构建；v23 隔离 PostgreSQL
迁移往返、任务终态触发器及 100,000 事件/entry 查询计划通过。详细计时见[公共 Feed 设计](public_feed.md)。
个人订阅页签继续复用 Watch 的 1,000 active/actor 与 1,000,000 closed period 计划证据。2026-09-12 真实
Supabase 从 v20 升级到 v23，2 条已有用户发布事件均回填为 fallback；真实 Go API readiness 和公共 Feed
请求返回 200。2026-09-13 同一黄色跑车 v4 GLB 已由 Blender 4.1 Cycles 完成 1200×800/128 samples
本地真实渲染；v4 材质 sidecar 通过正式 Go Worker 集成边界，约 46.6 秒。该结果是实现证据，不代表 v4 已部署。
Component GLB v6 与 Three.js 摄影棚已通过完整 Go `make check`、前端 21 文件/93 项、typed i18n、生产构建和
Python 296 项回归（保留 6 个既有 warning）；
最终全量测试结果以迁移进度文档为准；
Linux/amd64 API、通用/GLB Worker 与 Feed Render Worker 的镜像及单机 Compose 已完成仓库封装，通用 Worker
不会与专用 Feed Worker 竞争渲染任务，API 不接收 server-side Storage 密钥。真实任务产生 v4 Artifact、
浏览器卡片、容器构建和资源成本仍待联合验收。

## 7. 清理项

| 编号 | 证据与影响 | 依赖阶段与关闭条件 |
|---|---|---|
| PLAZA-CLEAN-01 | `ComponentRepoPage` 仍同时持有个人仓库与公共广场状态，虽已将个人订阅 Feed 抽出，但广场壳层依赖巨型页面 | 前端模块整理阶段拆出 `ComponentPlazaPage`；公共/订阅页签测试不再初始化 Group、上传或 Version 管理状态 |
| PLAZA-CLEAN-02 | 公共 Feed 是大图事件卡片，个人订阅 Feed 仍是紧凑事件行；同一发布事件在两个页签的视觉与信息密度不同 | 产品确认个人 Feed 是否也需要派生图片、发布人和描述；有明确字段/API 成本设计及视觉验收后关闭 |
| PLAZA-CLEAN-03 | 订阅管理保留独立链接，广场页签与管理页之间需要往返导航 | 观察真实验收中的导航理解；只有产品确认合并管理能力后才能改变 URL 和列表交互 |
