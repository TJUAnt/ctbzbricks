# 组件库广场（公共 Feed）详细设计

## 1. 模块边界与产品语义

公共 Feed 对应 `/model-plaza` 默认“公共”页签。每次用户 Component 版本发布形成一条事件；同一 Component 多次发布可出现多张卡片。

- 候选内容为 `content_kind=user` 的发布事件，当前 Component 必须 `active` 且未删除，事件 Version 必须未删除。
- Watch 不参与成员资格；认证 actor 只影响卡片上的 owner、Star 和 Watch 投影。
- 发布事务先创建 `pending` 图片任务。API 不等待任务：pending 本次不返回；成功变为 `ready`，重试耗尽、取消或永久失败变为 `fallback`，两种终态都进入 Feed。
- Feed 按 `(available_at DESC,event_id DESC)` 做 keyset 分页，卡片时间仍展示不可变事件的 `occurred_at`。`available_at` 只在首次到达终态时写入，避免晚完成事件被旧游标永久跳过。
- 卡片采用 Facebook/Reddit 式单列事件流，显示发布人、1200×800 派生图片、Component 描述、可选发布说明、Star 和详情入口；Star 复用 `ComponentStarButton` 的双语可访问名称和原生键盘语义。
- 发布人来自领域事件受信 `actor_id`；公开资料尚未建模，前端显示匿名头像和缩短 ID，不推断邮箱或昵称。
- 用户名称、描述和发布说明保持原文及 `contentLocale`，不自动翻译；official Component 不进入公共 Feed。

领域事件从 Goose v16 开始。v23 把已经存在的用户发布事件登记成 `fallback`，升级后历史 Feed 不消失，但不会在迁移或启动时批量生成图片。v16 之前没有事件的发布版本仍不推断。

## 2. SQL 性能设计预检

| 项目 | 决策 |
|---|---|
| 驱动关系 | `component_repo.component_feed_entries`；每个发布事件至多一行，随发布持续增长 |
| 规划分布 | 当前最多 1,000 用户；公共 Feed 跨 actor，当前门禁使用 100,000 事件/entry |
| 候选来源 | 发布事务原子创建事件、持久任务和 pending entry；数据库任务终态触发器推进 ready/fallback |
| 筛选选择性 | pending 是短暂窗口；低匹配名称搜索在当前 100,000 entry 包络内沿终态索引有界扫描，容量提高前重开搜索投影评审 |
| 稳定排序 | `available_at DESC,event_id DESC`；展示时间是 `occurred_at` |
| 分页/总数 | 不透明 keyset cursor；不使用 OFFSET，不计算 exact count |
| 一致性 | 单页由一条 SQL 读取；新终态进入头部，旧 cursor 沿既有边界继续 |
| 查询形状 | 终态部分索引驱动；每个 entry 通过有界 LATERAL 校验 Event、Version 和 v24 `component_catalog_candidates`，固定 `pageSize+1` 后才从 catalog projection 读取展示尺寸、聚合 Star、连接个人关系和图片 Artifact |
| 索引 | v23 `(available_at DESC,event_id DESC)` partial index，只包含 ready/fallback；v22 索引继续服务事件审计和 Watch Feed |

## 3. 发布、渲染与读取链路

1. `PublishVersion` 在同一个 serializable transaction 内更新 Version/current Version、写 `component.version.published.v1`、创建 `component.feed_render.materialize` 任务并登记 pending entry。图片失败不能回滚发布。
2. Preview GLB 处于 queued/running 时，Feed 图片任务建立持久依赖；Preview 已失败或缺失时图片任务自行失败并由通用任务系统最多尝试三次。
3. Go Worker 校验 task/event/owner/version 和 verified `component_preview_glb`，限制 GLB 为 32 MiB，并复核 SHA-256。
4. `component-feed-renderer-v4` 由 Go Worker 调用固定 Blender 4.1 Cycles CPU 进程。每次执行使用 Worker 新建的隔离临时目录、`--factory-startup` 和 `--disable-autoexec`，只传受控临时路径与固定数字；五分钟超时后由 Go 取消子进程。Blender 内嵌 adapter 负责导入 GLB、42° 折角平滑、微倒角、三点软箱、环境光、透明 shadow catcher、128 samples/denoise、8 次反弹和玻璃折射，输出 1200×800 RGBA PNG。
5. v4 延续固定 68 mm 产品摄影视角，按完整模型包围盒自动缩放到宽 52%、高 46% 的目标上限。该比例与黄色跑车 Studio 参考的主体尺度接近，同时为不同长宽比的 Component 保留卡片留白。灯光功率按模型 `extent²` 归一化，避免 LDraw 绝对坐标使大型模型变暗；`Standard + Medium High Contrast` 和 0.3 EV 保留高饱和 LEGO 色。Go 在接收 PNG 后移除 shadow catcher 的低 alpha 全画布底噪，但保留局部接触阴影。
6. Go 从 `LDraw <code>` 材质名生成一次性 sidecar，使用与 Component GLB 相同的 `ldraw-studio-pbr-v1` Profile。提交快照覆盖 Studio `LDConfig.ldr` 的 148 个 code 及 plastic/glass/rubber/chrome/pearl/metal/luminous/glitter/speckle 分类，向 Blender Principled BSDF 映射线性颜色、alpha、roughness、metallic、IOR、specular、clearcoat、transmission 和 emission；Studio 历史 GLB 的 `100000+code` 名称先归一化。启用 transmission 时 alpha 只作为 GLB 兼容层，不在 Cycles 中重复削弱表面。Component Preview GLB v6 把相同 Profile 写为核心 PBR、可选 Khronos 扩展和稳定 extras；v4 Feed 仍能读取既有 v4/v5 GLB 并由 sidecar 补齐材质。Blender 不访问数据库、对象存储或用户路径，也不承担任务消费职责；子进程环境采用固定 allowlist，不继承 Worker 的数据库、JWT 或 Storage 凭据。
7. Blender 未配置、版本不符、超时、崩溃或输出 PNG 校验失败时，同一次 Go Attempt 使用 `go_raster_v2` 快速 fallback。Artifact metadata 和 task result 记录实际 `renderEngine`、`rasterFallback`，metadata 另记稳定 `fallbackCode`；两条路径都受 32 MiB 输入/输出和 1200×800 尺寸校验约束。
8. Worker 用 Version、Preview hash、profile、renderer version 和最终 PNG hash 形成派生 Artifact 身份，写 verified `component_feed_image`；输出 hash 防止重试期间 Cycles/fallback 或硬件差异覆盖同一 immutable key。任务成功结果携带 Artifact ID。v1～v3 Artifact 不原地覆盖；只有新发布或另行批准的可追溯重建任务生成 v4 身份。
9. v23 触发器把 succeeded + Artifact 映射为 ready，把 failed/cancelled 映射为 fallback，并首次写 `available_at`。对象存储禁用或暂不可用时 Worker 仍消费任务，确保有限重试后不会永久 pending。
10. `GET /api/v1/component-public-feed` 只读取 ready/fallback。Service 为页面内 ready 图片批量签发短期 URL；签名失败只把对应卡片降级为 fallback。
11. `ComponentPublicFeedCard` 直接懒加载派生 PNG；fallback 复用已有本地化占位。浏览器不再为 Feed 下载 GLB 或即时截图。页面底部哨兵自动续页并按 event ID 去重。
12. API 与 Worker 是独立进程。开发环境使用 `scripts/start-feed-render-worker.sh` 或 `.ps1`；生产使用 `Dockerfile.feed-render` 的 Linux/amd64 容器，并发固定为 1。通用 Worker 通过 exclude list 移交 Feed 类型但保留上传维护，专用 Worker 只领取 Feed 类型。生产镜像固定并校验 Blender 4.1 归档，显式配置 `/opt/blender/blender`。专用 Feed Worker 不要求 `LDRAW_ROOT`，因为输入边界是已验证 GLB。完整拓扑与运行顺序见[Docker 生产部署](../deployment/docker_production.md)。

## 4. API、权限和 i18n

请求为 `GET /api/v1/component-public-feed?limit&cursor&query`。`limit` 为 1～100，`query` 最长 200；响应为 `{items,nextCursor}`。每项在既有事件和 Component 投影外增加：

```json
{
  "render": {
    "status": "ready",
    "availableAt": "2026-09-12T08:00:00Z",
    "image": {
      "artifactId": "uuid",
      "url": "short-lived-url",
      "format": "png",
      "sha256": "hex",
      "byteLength": 12345,
      "width": 1200,
      "height": 800
    }
  }
}
```

fallback 时 `status=fallback,image=null`。pending 永不出现在响应中。内部 Storage provider、bucket 和 key 不返回。

请求经过 JWT middleware；owner 校验只发生在发布和 Worker 输入边界。公共 Feed 的 actor 不过滤候选。无效 cursor/limit/query 使用既有稳定 `code + params`。

Feed 图片没有新增用户可见文本，复用图片 alt 和 `previewUnavailable` typed semantic key；当前 catalog 为
`frontend-2026.09.16.1`，Star 按钮继续复用既有 Star/Unstar key。`render.status/profile/version`、Artifact 字段、
尺寸、hash、cursor 和时间都是机器值，不翻译；用户内容规则不变。

## 5. 代码索引

| 层 | 代码 |
|---|---|
| 页面与卡片 | `frontend/src/componentRepo/ComponentPlazaPage.tsx`、`ComponentPublicFeedCard.tsx`、`ComponentStarButton.tsx`、`componentPublicFeed.ts`、`frontend/src/styles.css` |
| API adapter | `frontend/src/componentRepo/componentRepoApi.ts`、`frontend/src/app/appConfig.json` |
| HTTP / Service | `backend-go/internal/component/handler.go`、`service.go`、`mapping.go`、`types.go` |
| Worker / Renderer | `backend-go/internal/feedrender/`、`backend-go/internal/ldrawmaterial/`、`backend-go/cmd/worker/main.go`、`scripts/start-feed-render-worker.sh`、`scripts/start-feed-render-worker.ps1` |
| GLB 与浏览器材质 | `backend-go/internal/workbench/task_handlers.go`、`frontend/src/preview/studioPreviewRendering.ts`、`glbThumbnailRenderer.ts`、`frontend/src/parts/PartViewerPage.tsx` |
| 生产部署 | `Dockerfile.api`、`Dockerfile.worker`、`Dockerfile.feed-render`、`compose.production.yml`、`deploy/docker/*.env.example`、`docs/deployment/docker_production.md` |
| SQL / Migration | `backend-go/db/queries/component_public_feed.sql`、`component_feed_entries.sql`、`backend-go/db/migrations/00022_component_public_feed.sql`、`00023_component_feed_rendering.sql`、`00024_component_catalog_projection.sql` |
| Tests | `public_feed_test.go`、`service_integration_test.go`、`public_feed_performance_integration_test.go`、`renderer_test.go`、`image_renderer_test.go`、`image_renderer_integration_test.go`、`componentPublicFeed.test.ts`、`ComponentPublicFeedCard.test.tsx`、`ComponentStarButton.test.tsx` |

## 6. 验证证据

2026-09-12 本地隔离 PostgreSQL 完成 `0 -> v23 -> v22 -> v23`、重复 up、API/Worker 启动无 DDL 及全部集成测试。数据集有 100,000 个事件和 100,000 个终态 entry，其中 90,000 个用户事件、10,000 个 official 事件；以下是 ANALYZE 后 warm-cache 查询形状，不是生产 SLO：

| 场景 | 执行时间 | 计划结论 |
|---|---:|---|
| 无筛选首屏 | 0.138 ms | v23 终态 partial index 驱动，固定 21 条 |
| 单 Component 选择性搜索 | 53.097 ms | 当前包络内沿同一索引有界扫描，无 entry Seq Scan 或 spill |
| 名称高匹配搜索 | 0.142 ms | 终态索引快速填满页面 |
| 第 80,000 条后的深 cursor | 0.128 ms | row-value 边界进入 Index Cond，无 OFFSET |

渲染单元测试验证 1200×800 PNG、70%×65% 构图上限、旧 v4 GLB 透明材质恢复、单 Part 平滑法线边界、alpha 混合与损坏 GLB 拒绝；前端 20 个文件/90 项测试覆盖 ready 图片和 fallback 占位，生产构建与 i18n 检查通过。Go `make check`、最终 v23 隔离 PostgreSQL 和 Python 296 项回归通过，保留 6 个既有 pytest warning。

2026-09-12 真实 Supabase PostgreSQL 17.6 从 Goose v20 升级到 v23；表、部分索引和终态触发器均存在，2 条既有用户发布事件回填为 fallback，状态约束检查无异常。重复 `up` 无操作，真实 Go API readiness 与公共 Feed 请求返回 200，确认升级前的 `pgconn.PrepareError` 已消失。真实 Worker 图片、对象存储、模型视觉和浏览器滚动仍待联合验收。

2026-09-14 的 Component 08 清理把公共 Feed 的删除、active、公开 Version 资格切换到 v24 candidate projection，并在固定页后从 catalog projection 读取展示尺寸；
事件、图片终态、排序和 cursor 合约未改变。v24 已于 2026-09-15 部署真实 Supabase 并完成数据守恒、投影、索引、触发器和重复 up 回查；Go API/前端仍需另行发布后才会使用新查询。

同日首次真实发布后发现本机只运行 API、没有 Worker：2 条 Feed 任务均为 queued、attempts=0、无 lease。限定类型 Worker 启动后，两条任务均一次成功并生成 1200×800 PNG，Artifact 分别为 51,478 和 122,917 bytes；公共 Feed 返回 `ready,ready,fallback`，两个签名 URL 实际读取均为 HTTP 200 `image/png`。这验证了任务、Storage 和 API 图片链路；浏览器画面构图与滚动仍需人工验收。

renderer v2 完成后，从同一黄色车辆的已验证 v4 Preview GLB 本地生成 112,978-byte PNG，实际检查
确认模型宽度不超过 70% 且背景、阴影、透明材质链路均完整。Go `make check` 通过，v2 专用
`component.feed_render.materialize` Worker 已在本机重启。已存在的 v1 Artifact 保持不变，本次不通过绕过持久
任务的直接写入修改旧图；历史图片批量重建需要独立的可追溯调度契约。

2026-09-13 renderer v3 使用同一黄色车辆 v4 Preview GLB 完成真实 Blender 4.1 Cycles CPU 渲染：
1200×800、128 samples，保存的基准端到端 47.672 秒，最终 PNG 297,421 bytes；最小环境 allowlist 的正式可选集成测试为 50.818 秒。最终图黄色样本中位值为
`238/202/62`，Studio 参考为 `223/187/58`；透明画布四角 alpha 从 Cycles 原始底噪清理为 0，接触阴影保留。
单次真实基准只证明本机渲染正确与当前成本量级，不是生产 SLO。Go 单元测试覆盖 Cycles 成功、失败回退、
取消不回退、隔离路径、凭据环境隔离、PNG/Artifact 不可变身份与透明底清理；`make check` 和相关包 race 测试通过。
本轮未写 Supabase、未重建既有 Artifact。2026-09-13 后续完成 Linux/amd64 三镜像与单机 Compose 仓库封装：
API 不持有 Worker Storage 密钥，通用 Worker 排除 Feed task 但保留上传维护，Feed Worker 固定 Blender 4.1、
并发 1、4 CPU/4 GiB 和 1 GiB 临时目录；迁移保持 `ops` profile 显式执行。Compose 静态展开与 Go 能力过滤
测试通过；本机 Docker daemon 未运行，因此镜像构建、容器内 Blender 冒烟与真实服务器资源验收仍待联合执行。

2026-09-13 renderer v4 / Component Preview v6 完成 `ldraw-studio-pbr-v1`：固定 Studio 2.0 `LDConfig.ldr`
148 色快照、九类材质、标准 glTF IOR/specular/clearcoat/transmission/emissive 扩展，以及 Three.js 共享
RoomEnvironment/Neutral tone mapping。材质分类、GLB 扩展、透明透射不重复计算和前端运行时单测通过；前端生产构建
通过。相同黄色跑车旧 v4 GLB 通过新版 sidecar 的正式 Go Worker + Blender 4.1 集成，1200×800/128 samples 用时
46.59 秒并返回 Cycles 成功，证明旧 GLB 补材质路径可运行。完整 Go `make check`、前端 21 文件/93 项、
typed i18n、生产构建及 Python 296 项回归通过（保留 6 个既有 pytest warning）；尚未生成真实 v6 Preview、
写 Supabase 或重建既有 Feed Artifact。

2026-09-13 部署准备只清理任务队列：真实 Supabase 操作前没有 Preview/Feed renderer 非终态任务，
仅有 2 个 artifact verify 与 2 个 import parse 的未来 queued execution，均 attempts=0 且无 lease。
4 条任务已在事务中转为 cancelled，并各自保留 task event 与 outbox event；复查 queued/running 为 0。
Feed 投影保持 v1 的 2 条 ready、2 条 fallback，v6 Preview 与 v4 Feed Artifact 仍均为 0。产品决定将
真实 v6/v4 生成与浏览器联合验收留到后续；启动联合验收前必须重新检查队列。

## 7. 清理项

| 编号 | 证据与影响 | 依赖与关闭条件 |
|---|---|---|
| PUBLIC-FEED-CLEAN-01（已关闭） | 广场曾由巨型 `ComponentRepoPage` 持有数据和滚动状态 | 2026-09-15 已拆出独立 `ComponentPlazaPage`，源码边界测试确认不初始化个人目录、Group、上传或 Version 状态 |
| PUBLIC-FEED-CLEAN-02 | 低匹配名称搜索在 100,000 entry 包络内需扫描部分全局时间索引 | 容量接近包络或实测延迟不满足目标时，设计权威搜索投影并提供新计划证据 |
| PUBLIC-FEED-CLEAN-03 | v16 之前没有领域事件，v23 只能回填已有事件为 fallback | 产品批准历史来源、事件时间和幂等策略后才能补齐 |
| PUBLIC-FEED-CLEAN-04 | 发布者只有 actor ID，没有公开昵称/头像 | 定义公开资料表、字段可见性、修改与删除策略后接入 |
| PUBLIC-FEED-CLEAN-05 | v4 已把完整固定颜色快照和九类物理材质统一到 Component GLB、Three.js 与 Cycles；BrickLink Studio Eyesight 的私有 shader/灯光实现无法逐项复用，现有量化仍只有黄色跑车 v3 基准，细小透明件、橡胶、金属和发光材质没有成套对照 | 建立至少包含透明件、橡胶/轮胎、chrome/pearl、夜光、大型 MOC 和纯白模型的版本化视觉基准；在生产同规格硬件记录耗时/峰值内存并由产品盲测后关闭 |
| PUBLIC-FEED-CLEAN-06 | v1～v3 Artifact 按不可变身份保留，当前没有批量生成 v4 的用户操作或维护契约 | 产品批准范围、速率、失败恢复、成本和审计策略后新增持久重建调度；不得直接覆盖旧对象 |
| PUBLIC-FEED-CLEAN-07 | v4 Handler 严格校验 renderer version；切换镜像时遗留 queued/running v3 task 会被新 Worker 永久拒绝并最终进入 fallback | 部署前查询旧版本非终态任务并由旧镜像排空；将该检查及一次新 v4 真实发布写入联合验收记录后关闭 |
