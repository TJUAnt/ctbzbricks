# Go 后端迁移进度

> 后续领域专项：[2D 像素化与拼接方案 Go 迁移](go_pixel_2d_migration.md)（P2D，独立记录；不计入 Component Repo G0～G8）。

> 最后更新：2026-09-13（Component Preview v6 / Feed renderer v4 材质 Profile）
> 状态依据：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 跟进指南：[go_migration_followup_guide.md](./go_migration_followup_guide.md)
> 记录规则：本文只保留当前状态、已验证里程碑和未关闭门禁；过程细节由专项文档、测试和 Git 历史承载。

## 1. 当前状态

| 阶段 | 状态 | 当前事实 |
|---|---|---|
| G0 原则与决策 | Completed | 目标架构、迁移边界和完成定义已固化 |
| G1 Go 工程骨架 | Completed | Gin API、独立 Worker、Goose、sqlc/pgxpool 和验证命令可用 |
| G2 PostgreSQL baseline | Completed | `component_repo` 由 Goose 独占；空库迁移、回滚和启动不改 schema 已验收 |
| G3 目录、版本和分组 | Completed | Component、Version、Group、可见性和不可变来源链已迁移 |
| G4 Artifact 与上传 | Completed | source/derived、owner、直传会话、验证和 Storage 补偿边界已迁移 |
| G5 持久任务系统 | Completed | Job/Execution/Attempt、lease/retry/cancel、event/outbox 和依赖图已迁移 |
| G6 导入与候选 | Completed | upload -> verify -> Go parse -> Snapshot/Candidate/Draft 已闭环 |
| G7 关系、校验和预览 | Completed | relation、interface、可选 validation、BOM 与 GLB preview 均由 Go 执行 |
| G8 前端切换与 Python 退出 | Completed | Component Repo public API/task consumer 已 Go-only；Python public router 已删除，双语言、双身份 Auth/Storage RLS、恢复/回滚和真实指标门禁通过 |

当前仓库 schema head 为 **v24**（v19 属于独立 P2D 路线，v20 为 Watch Feed 索引，v21 补齐 official 发布事件
受信发布者，v22 为公共 Feed 事件索引，v23 为 Feed 图片终态投影和索引，v24 为 Component 目录/审核翻译共享投影与
keyset/search 索引）；真实 Supabase 已于 2026-09-12 从 v20 升级到 v23，v24 尚未部署。Component Preview v6 与 renderer v4 已在仓库实现 `ldraw-studio-pbr-v1`，本地 Blender 集成通过；v6 Artifact 重建范围、v4 服务器运行、浏览器视觉与生产资源/查询计划验收仍待统一执行。Go API 已覆盖目录、公共广场 Feed、版本、分组、Star、Watch/Feed、Artifact、上传、Import、Candidate、
关系审核、Part Library、任务、BOM、Preview、Search 和 Version Diff。Component Repo 不再新增 Python task；
`component.import.parse` 与 `component.relations.detect` 已由 Go Worker 执行。

代码完成与部署完成必须分开判断：仓库中的 migration、API 和测试通过，不代表真实 Supabase 已升级到相同
schema head，也不代表浏览器、RLS、冷热缓存或生产 SLO 已验收。

## 2. 已确认的不变量

- Go 是 Component Repo system backend；采用模块化单体 Gin API 和可独立运行的 Go Worker。
- PostgreSQL-only；手写 SQL + sqlc + pgx/v5/pgxpool，不引入 ORM 或 MySQL 兼容层。
- Goose 独占 `component_repo`；Alembic 仅暂管未迁移 `public` 对象和 provider-owned `storage` policy。
- API/Worker 启动不执行 DDL、schema repair 或数据回填。
- 文件解析、几何、搜索、验证与派生产物生成通过 PostgreSQL 持久任务执行；Handler 只做有界工作。
- PostgreSQL 保存业务/任务元数据；对象存储保存上传源文件和大型派生产物。
- 新 API 使用 `/api/v1`；不新增双写、兼容代理或 shadow traffic。
- API 错误使用稳定 `code + params + traceId`；未知错误不泄露 SQL、路径、堆栈或最终翻译文本。
- 用户内容保留原文与 `contentLocale`；official 内容只选 reviewed translation；机器值不翻译。
- ComponentVersion 不可变；发布与可选 ValidationReport 解耦，验证失败不撤销发布。

## 3. 当前能力地图

| 领域 | 已实现能力 | 主要边界 |
|---|---|---|
| Component | CRUD、公开目录、owner 管理、逻辑尺寸与复合搜索 | 公开可见性与 owner 操作分离 |
| Version | Draft/Publish/Deprecate/Archive、历史、source、BOM、Diff | 来源字段由服务端沿 Candidate 链取得 |
| Group | root/custom、移动、成员管理 | root 仅代表 owned；Star 是独立集合 |
| Star | 幂等 Star/Unstar、列表、计数、详情/目录投影 | 不授予权限、不通知、不公开 actor 列表 |
| Watch | 幂等 Watch/Unwatch、筛选/keyset 管理页、详情投影、组件广场个人订阅 Feed、发布领域事件、mutation 指标 | 不做推荐、recipient snapshot、fan-out Worker、通知或未读中心 |
| 组件广场 | 公共/个人订阅双页签；公共卡片展示发布人 ID、Worker 生成的 1200×800 图片和事件内容；个人页签展示当前 Watch 更新 | Go 持久任务优先调用 Blender 4.1 Cycles，失败时 Go raster fallback；pending 图片事件本次跳过，ready/fallback 都发布成功并进入流；两个 Feed 成员资格独立且不返回 exact count |
| Upload/Import | owner-scoped 直传、complete `202`、持久处理链、状态恢复 | complete 是写交互终点，不等待 Worker |
| Task | logical job、execution/attempt、依赖、租约、重试、取消、事件 | PostgreSQL 是权威状态，不使用进程内队列 |
| Scene/Candidate | Studio/LDraw 解析、多 root expansion、hash/signature、relation 审核 | source 与 derived Artifact 分离 |
| Preview | Component v6 PBR GLB、Part meshopt GLB、partial preview、Box、共享摄影棚静态缩略图 | 固定 148 色/九类材质 Profile；Storage 保存正文，数据库保存状态和引用；Part 内部多材质/TEXMAP 仍是明确缺口 |
| Part Library | Studio manifest/import、LDraw geometry、connector/interface、Search | active snapshot 冻结解析与关系语义 |

## 4. 里程碑证据摘要

| 日期/阶段 | 已完成事实 | 证据摘要 |
|---|---|---|
| 2026-08-06 / G0-G2 | 原则、工程骨架、baseline、migration authority | Go unit/race；空 PostgreSQL up/down/up；sqlc；API/Worker 启动 schema 无变化 |
| 2026-08-06～08 / G3-G4 | Component/Version/Group、Artifact、上传会话、来源不可变 | service/HTTP/PostgreSQL contract；RLS 与 Storage key 边界测试 |
| 2026-08-08～10 / G5 | durable task system、attempt fence、event/outbox、依赖任务 | Worker 竞争、lease/retry/cancel、崩溃恢复和 startup contract |
| 2026-08-10～14 / G6-G7 | Go import parser、Candidate、relation、validation、preview | 真实 Studio/LDraw fixtures；Task chain 与 PostgreSQL integration |
| 2026-08-14～25 / G8 | 前端 `/api/v1` 切换、JWT/JWKS、Part Library、BOM/Preview/Search | Go/frontend 全量验证；真实开发库专项执行记录见路线文档 |
| 2026-08-26 | Component Version Diff v1 | Go SceneSnapshot diff、owner-only API、CLI、上限与歧义测试 |
| 2026-08-27 | Diff 双栏三维投影 | 共用世界坐标、相机同步、稳定变化高亮、typed i18n key |
| 2026-08-29～30 | Star / Goose v14 | 幂等关系、列表/详情/UI、资格检查、SQL 计划复核和 review 跟踪 |
| 2026-08-31 | Watch / Goose v15 | 独立历史关系、幂等 API、keyset 列表、详情入口、10 万关系计划复核 |
| 2026-09-01 | Watch publish event / Goose v16 | exclusive 发布边界、不可变唯一事件、空 payload、回滚与并发契约 |
| 2026-09-04 | 关系生命周期 / Goose v17 | Component 删除立即隐藏关系；持久 Worker 统一关闭 Watch、分批删除 Star；百万关系计划验证 |
| 2026-09-04 | Star logical-size / Goose v18 | 当前公开 Version 规范化尺寸投影；发布/Preview 原子维护；1000 actor × 1000 Star 计划验证 |
| 2026-09-05 / G8 | 真实 Supabase Goose v14～v18 | 明确目标、迁移前备份、v13→v18、schema/data contract 与重复 up 无操作验收 |
| 2026-09-05 / G8 | Python public router 删除、Storage RLS v25 | FastAPI Component Repo public 入口退出；双语言错误切换修复；真实 Supabase Preview policy 去除失效 subscription/Star/Watch 授权 |
| 2026-09-09 | Watch dynamic Feed / Goose v20 | 当前 active Watch 读取时聚合、发布前后语义、Feed keyset/API/UI、7/30/90 天窗口；旧 fan-out 原型删除 |
| 2026-09-12 / G8 文档治理 | Component、Star、Watch 当前实现分别建档并由根 README 引用 | 前端→API→Service→SQL/Task/测试代码索引；记录固定 100 条、Count/List 快照、职责过载、时间精度与共享锁归属等清理候选；无运行时变更 |
| 2026-09-12 / G8 公共广场 Feed / Goose v22 | `/model-plaza` 改读用户版本发布事件，按事件倒序 keyset 连续加载；Watch 与成员资格解耦 | API/Service/sqlc/前端与 cursor/HTTP/集成测试通过；100,000 事件计划门禁覆盖首屏、筛选和深 cursor，无全事件 Seq Scan 或磁盘 spill |
| 2026-09-12 / G8 公共广场事件卡片 | 广场表格改为单列发布事件卡片，展示事件发布人、事件版本 GLB、描述、发布说明、Star 与详情入口 | `publisher.id` 取受信事件 actor；GLB 进入视口附近才加载，并由 Component/Part 共享的单 WebGL context 生成缓存缩略图；前端 20 文件/89 项、build/i18n、Go check、v22 PostgreSQL/10 万事件计划及 Python 296 项通过 |
| 2026-09-12 / G8 组件广场双 Feed 页签 | `/model-plaza` 默认公共 Feed，`?tab=subscriptions` 承载个人订阅 Feed；`/component-repo/watches` 收敛为关系管理页 | Watch Feed 组件和 cursor helper 从管理页拆出；页签 URL 可恢复；后端 API/SQL/权限无变化；资源版本 `frontend-2026.09.12.2`；前端 20 文件/89 项、build/i18n 与 Python 296 项通过 |
| 2026-09-12 / G8 Feed 派生图片 / Goose v23 | 发布事务原子创建 pending entry 与 `component.feed_render.materialize`；Go Worker 生成 1200×800 摄影棚 PNG；成功或重试终结后按 `available_at` 进入流 | renderer v1 采用 15° 相机、86%×80% 最大构图、双光源/接触阴影/2×超采样；ready 返回短期图片 URL，fallback 返回占位；100,000 事件/entry 首屏、搜索、深 cursor 均由终态 partial index 驱动，无 entry Seq Scan、OFFSET 或 spill |
| 2026-09-12 / G8 真实 Supabase Goose v21～v23 | 目标项目从 v20 升级到 v23，修复新 API 查询旧 schema 导致的 `pgconn.PrepareError` | PostgreSQL 17.6；表、索引、触发器存在；2 个历史用户发布事件回填 fallback；非法终态 0；重复 `up` 无操作；真实 API readiness 与公共 Feed 均返回 200 |
| 2026-09-12 / G8 真实 Feed 图片链路 | 发现开发环境只运行 API、无 Worker，2 条新任务保持 queued/attempts=0；以限定类型 Worker 恢复 | 两条任务均 attempt 1 成功，生成 51,478/122,917-byte 的 1200×800 PNG；API 返回两个 ready 图片，签名 URL 均为 HTTP 200 image/png；补充 Worker 能力与 Attempt 安全日志 |
| 2026-09-12 / G8 Feed renderer v2 | 根据真实 Studio/Worker 黄车对照收敛首轮视觉差异 | 构图从 86%×80% 调整为 70%×65%；共享 LDraw 线性颜色与 plastic/glass/rubber/metal 分类；Component Preview GLB v5 写 NORMAL/PBR/alpha，Feed v2 兼容 v4 并重建折角平滑法线、透明背到前混合；黄车 v4 GLB 实渲染与 Go `make check` 通过，本地专用 v2 Worker 已重启 |
| 2026-09-13 / G8 Feed renderer v3 | Go Worker 管理任务并在隔离临时目录调用 Blender 4.1 Cycles；Go raster v2 保留为失败 fallback | 68 mm 固定视角、52%×46% 构图、128 samples/denoise、三点尺度归一化软箱、8 次反弹、玻璃传输、微倒角、透明接触阴影与低 alpha 清理；黄色跑车 1200×800 保存基准 47.672 秒/297,421 bytes，凭据隔离集成测试 50.818 秒；`make check` 和相关包 race 通过，未写 Supabase、未重建旧 Artifact |
| 2026-09-13 / G8 Docker 生产封装 | API、通用/GLB Worker、Feed Render Worker 三个 Linux/amd64 容器与显式 migration profile | Blender 4.1/glTFPack 1.2 归档固定 checksum；非 root/只读 rootfs/tmpfs/资源上限；API 与 Worker 密钥分离；通用 Worker exclude Feed 且保留上传维护；Compose 普通/ops 展开、三个 Linux/amd64 二进制和 Go `make check` 通过，Docker daemon 未运行故镜像/容器验收待执行 |
| 2026-09-13 / G8 Component Preview v6 / Feed renderer v4 | `ldraw-studio-pbr-v1` 成为 GLB、Three.js 与 Cycles 的共同材质事实源 | 固定 Studio 2.0 `LDConfig.ldr` 148 色与源码 hash；九类材质映射线性颜色、alpha、roughness、metallic、IOR、specular、clearcoat、transmission、emission；GLB 写标准可选扩展和 Profile extras；浏览器使用共享 RoomEnvironment/Neutral tone mapping 并移除黑色边线；完整 Go `make check`、前端 21 文件/93 项、typed i18n、build 和 Python 296 项通过，旧 v4 黄车 GLB 经新版 sidecar 的 Go Worker + Blender 4.1 集成 46.59 秒成功；未写 Supabase、未生成真实 v6 Artifact |
| 2026-09-13 / WATCH-DEPLOY 队列准备 | 真实 Supabase 非终态任务按持久任务取消语义清空，v6 Preview 与 v4 Feed 图片暂缓 | 操作前仅有 2 个 artifact verify 与 2 个 import parse，均 queued、attempts=0、无 lease；事务取消后 queued/running 均为 0，保留 4 个任务行并写入 4 个 task event 与 4 个 outbox event；Goose 保持 v23，v6 Preview/v4 Feed Artifact 均为 0；正式联合验收前仍须重新检查队列 |
| 2026-09-13 / G8 前端数据完整性与结构清理 | 先关闭 Component Version/Group 候选固定首 100 条缺口，再拆分目录、详情与 API adapter 职责 | 第 101 条 Version/成员回归和 Group 候选续页 UI 测试通过；详情读取、mutation/权限和 presenter 独立；API 拆为 DTO、统一鉴权 transport 与五个领域模块，7 行兼容入口保留原调用名；未修改 Go API、SQL、迁移或部署状态 |
| 2026-09-14 / G8 Component 目录一致性与共享投影 / Goose v24 | 关闭 COMPONENT-CLEAN-03/04/08：目录删除独立 Count 和 OFFSET，使用绑定筛选的 `(updated_at DESC,id DESC)` opaque cursor；Component/Group/Star/Watch/公共 Feed 共用 candidate/catalog/reviewed translation 投影 | API 改为 `{items,nextCursor}`；完整 UUID 等值，选择性名称/翻译走 trigram，高命中允许规划器扫描 100,000 条 Component 包络；所有场景无 Version 全表扫描与 spill，最深第 80,001 条 cursor 为 0.263 ms；v24 up/down/up、完整 Go `make check`、隔离 PostgreSQL database/component/httpapi、前端 22 文件/97 项、i18n 与 build 均通过；真实 Supabase 保持 v23 |

## 5. 最新里程碑：Watch 偏好、发布事件与关系生命周期

日期：2026-09-11
阶段：G8 / Component Repo 关系能力
状态：WATCH-1～4 complete in repository；仓库 schema head v24、真实 Supabase v23，Component Preview v6 / renderer v4 的运行部署、v24 部署、重建范围、真实浏览器与生产计划/资源验收待联合执行

### 5.1 已实现

- Goose v15 新增 `component_watch_periods` 与 `component_activity_sequence`；每次 Rewatch 追加新 period，
  Unwatch 只写一次 `ended_seq/unwatched_at`，已关闭区间不覆盖、不重开、不删除。
- Watch 资格为：Component 存在且未删除、非本人、`active`、存在非 Draft Version。重复 PUT 返回当前 active
  period 且不写历史；Rewatch 追加新 period；Unwatch 即使目标不可见也幂等成功。并发创建由 active partial
  unique 与 serializable retry 收敛。Watch/Unwatch 获取同 Component shared advisory xact lock；Publish 已
  复用同 key 的 exclusive lock 后再分配 `event_seq`，消除 sequence 顺序与提交可见性的竞态。
- 新增 `PUT/DELETE /api/v1/components/:componentId/watch` 和 `GET /api/v1/component-watches`。
  当前只接受稳定机器值 `releases_only`；Watch API 本身不创建 Star、领域事件或通知。
- Watch 列表从 actor 的 active period 部分索引驱动，按 `watched_at DESC, component_id DESC` 做不透明
  keyset cursor；不返回 exact count。名称/ID 与 category 筛选只运行在当前 actor 的 active 候选内；搜索启用
  时才读取候选 reviewed translation，筛选后固定 `limit + 1` 页面，再读取展示翻译和 current Version。
- Component 公开详情和目录投影当前 actor 的 Watch 状态；前端详情页提供独立 Watch/Unwatch 按钮、可访问名称、
  pending 状态和失败后服务端重载。
- 前端新增独立 `/component-repo/watches`“我的订阅”页：服务端筛选、不透明 cursor 续页、最近公开发布、
  订阅时间和乐观 Unwatch 失败回滚。页面已加载数不冒充 exact total。
- closed period 当前永久保留，不设置 TTL、自动清理或按 actor 裁剪；总量达到 1,000,000 条只触发容量和计划
  重评。动态 Feed 不读取 closed period，历史区间不再承担 recipient 或 Feed 完整性账本职责。
- 新增 Watch 结构化错误和双语言 typed semantic key；机器 level、ID、时间和 API 字段不翻译。
- Goose v16 新增独立 `component_domain_events`。Version 首次发布在原 serializable transaction 内取得同
  Component exclusive activity lock，更新 Version/current version 后插入事件并分配 `event_seq`；事件与业务
  状态原子提交。数据库拒绝非 published/mismatched 目标、重复 Version 事件及 UPDATE/DELETE；集成测试确认
  有效订阅区间满足 `started_seq < event_seq < ended_seq`。
- v1 事件 payload 固定 `{}`；不复制 Version Label、Release Note/locale、Component 名称、Artifact 路径或译文。
  不复用 Task outbox，不创建 delivery、recipient snapshot 或通知；v16 不回填迁移前的历史发布。
- Go API `/metrics` 以 Prometheus 文本格式暴露固定低基数
  `component_domain_event_total{event_type="component.version.published.v1",result}`，其中 result 仅允许
  `committed/failed`。只在最终
  事务结果确定后计一次，内部 retry 不重复；指标不包含 actor、Component ID 或用户内容。
- `/metrics` 同时暴露 `component_watch_mutation_total{action,result}`；action 固定为 `watch/unwatch`，result
  固定为 `succeeded/failed`，幂等重复操作计为 succeeded，全部事务重试结束后每次 Service 调用只计一次。
- WATCH-3 已改为读取时聚合：当前 active Watch/actor 按 1,000 规划，Feed 默认 30 天、UI 可选 7/30/90 天，
  按发布事件时间与 UUID keyset 分页。旧 notification fan-out 容量、重试和 backlog 指标契约已废止。
- Goose v20 新增 `(component_id,occurred_at DESC,id DESC)` 发布事件索引；API 新增
  `GET /api/v1/component-watch-feed`。发布早于 Watch 但位于窗口内时可见，Unwatch 后下一次读取立即不可见。
- 前端组件广场“个人订阅”页签承载动态 Feed、窗口选择、刷新和滚动续页；“我的订阅”独立页面只管理 active Watch。
- Goose v17 为 Watch 历史增加 `ended_reason` 和 `(component_id,actor_id) WHERE ended_seq IS NULL`。Component
  DELETE 在 exclusive activity lock 内软删除、冻结公共结束边界并原子入队 `component.relationships.cleanup`；
  列表立即隐藏目标，Worker 以 5,000 条 actor-keyset 短事务关闭 Watch 并物理删除 Star。任务重放是空操作，
  不创建 recipient snapshot 或通知；动态 Feed 通过 Component 可见性联接立即排除已删除目标。

### 5.2 发布事件 SQL 设计复核

事件按每次新 Version 发布追加，驱动关系随发布总量单调增长。WATCH-2 写路径只有一次点 INSERT：主键、
`(event_type,component_version_id)` 与 `event_seq` 三个唯一索引分别承担身份、业务去重和共同顺序域不变量，
v20 再按动态 Feed 的实际 `component_id + occurred_at + id` 谓词新增复合索引。Feed 从 actor active Watch
候选开始，使用发布时间窗口和稳定 keyset，不读取 closed period、不执行 exact count；专项 EXPLAIN 不能把
v16 唯一索引或功能测试当作性能证据。

### 5.3 Watch 列表 SQL 性能证据

隔离环境：PostgreSQL 14.17，200,000 条 Watch period（密集 actor 100,000 active + 100,000 closed history）、
100,000 个 Component/Version、10,000 条 reviewed official translation。另以稀疏/空 actor 验证索引边界。执行
`EXPLAIN (ANALYZE, BUFFERS, SETTINGS)`，数据已 ANALYZE；以下为本机 warm-cache 查询形状证据，不是生产 SLO：

| 场景 | 执行时间 | 关键计划事实 |
|---|---:|---|
| 密集 actor 首页 21 候选 | 0.269 ms | row-value 条件进入 active partial index；Component/Version 各 21 loops；翻译内层仅 official 2 loops |
| 密集 actor 第 99,980 行后 | 0.239 ms | `ROW(watched_at,component_id)` 进入 Index Cond，只读取剩余 20 行，无 skipped-row filter |
| 稀疏 actor 20 条 | 0.011 ms | active partial index-only scan 读取 20 行 |
| 空 actor | 0.004 ms | active partial index 返回 0，Heap Fetches 为 0 |

加入名称/ID 与 category 筛选后，驱动关系和 cursor 不变。隔离 PostgreSQL 14.17 以 1,000 actor × 每人
1,000 条 active Watch（总计 1,000,000）并追加 1,000,000 条 closed period、1,000 Component/Version、
100 条 reviewed translation 验收；closed 数据等价于每个当前关系曾完成一次 Rewatch，并达到既定容量重评点。
`shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB`，数据已 ANALYZE。warm-cache 计划仅证明
查询形状，不代表生产 SLO：

| 场景 | 执行时间 | 关键计划事实 |
|---|---:|---|
| 无筛选首屏 | 1.800 ms | actor active 索引限定 1,000 候选；100 万 closed 不进入候选；展示只处理 21 行 |
| category + 名称选择性 | 1.040 ms | category 与 actor 候选求交后匹配 |
| 名称高匹配 | 6.984 ms | 最多扫描 actor 的 1,000 候选，无 spill、temp 或 ledger 全表扫描 |
| reviewed translation 选择性 | 0.793 ms | 搜索启用时才运行候选翻译 probe |
| 最深支持 cursor | 0.549 ms | row-value 条件进入 active-time index，无 skipped-row filter |
| 空 actor | 0.023 ms | 关系索引返回 0，Component/Version/translation 候选分支未执行 |
| Unwatch / Rewatch | 0.131 / 0.223 ms | 点更新与 conflict arbiter 均使用 active partial index；closed history 不参与探测 |

本地 Watch ledger 总物理大小为 560,545,792 bytes；这是刚装载并 ANALYZE 的 fixture 大小，不代表生产容量
或 bloat。closed 增长模型、1%/10%/100% 每月 Rewatch 场景及 90 天/1 年/3 年观察窗口记录在 Watch 路线文档。
可重复组合门禁：`RUN_STAR_SIZE_PLAN_TEST=1 RUN_WATCH_LIST_PLAN_TEST=1 make test-postgres`。没有增加推测性
索引；所有本地时间只证明查询形状。

### 5.4 Component 关系生命周期 SQL 设计与证据

预检按单个热门 Component 各 1,000,000 条 active Watch/Star 设计；候选由 Component 关系索引驱动，无展示
筛选、translation、exact count、OFFSET 或列表快照要求。实测同步关闭 100 万 Watch 约 12.75s、同步删除
100 万 Star 约 2.22s，因此否决在 DELETE Handler 中清理。最终事务只软删除、冻结统一 Watch 边界并持久入队；
Worker 使用 5,000 条短事务和 actor keyset，避免每批从索引起点回扫。

隔离环境为 PostgreSQL 14.17，`shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB`；数据已
ANALYZE。以下 `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` 是本机查询形状证据，不是生产 SLO：

| 场景 | 代表执行时间 | 关键计划事实 |
|---|---:|---|
| Watch 高匹配首批 5,000 | 36.21 ms | `component_watch_periods_component_active_idx` 同时承载 component 与 actor cursor Index Cond |
| Star 高匹配首批 5,000 | 13.62 ms | `component_stars_component_idx` 同时承载 component 与 actor cursor Index Cond |
| Watch/Star 空候选 | 0.03 / 0.03 ms | 对应 Component 索引返回 0；内层主键 probe 不执行 |
| Watch/Star 深游标 5,000 | 1.27s / 0.56s（冷页） | 从 `actor_id >= fe00…` 直接定位，无 skipped-row filter、全表扫描或前序批次回扫 |

首轮冷缓存高匹配为 Watch 1.38s、Star 0.33s；成本受随机 heap/index page 读取影响，但单事务仍固定最多
5,000 条。任务重试从零游标重新发现未处理关系；已关闭 Watch 不在 partial index，已删除 Star 不再成为候选。

### 5.5 验证

```text
go tool sqlc generate                         PASS
backend-go make check                        PASS
backend-go make test-postgres                PASS（Goose 0 -> v18、v18 down/up、全部 integration、startup contract）
关系生命周期 EXPLAIN（1m Watch + 1m Star）   PASS（高匹配、空候选、深 actor cursor；PostgreSQL 14.17）
Star 尺寸 EXPLAIN（1000 actor × 1000 Star） PASS（无筛选、选择性/高/零命中、空 actor、首/最深页）
Watch 列表 EXPLAIN（1000 actor × 1000 active + 100 万 closed）PASS（筛选、翻译、最深 cursor、Unwatch/Rewatch）
metrics counter/route/integration            PASS（Domain Event 与 Watch mutation 固定标签、真实 API scrape）
Go race（observability/componentwatch）      PASS
frontend npm run i18n:check                  PASS（2 locales / 10 namespaces / frontend-2026.09.04.1）
frontend npm test                            PASS（15 files / 71 tests）
frontend npm run build                       PASS（仅既有 Vite deprecation/chunk-size warning）
backend Python pytest                        PASS（295 tests；6 个既有 PytestReturnNotNoneWarning）
```

i18n catalog hash：`25ef31679402e7c0aaafae4d3d25607f9a96286bd864ec1ed9b086d999a6379d`。

### 5.6 Star 尺寸投影与容量证据

Goose v18 在 Component 上增加当前公开 Version 的升序规范化 logical-size 投影。发布事务切换
`current_version_id` 时同步刷新投影；若 Preview 晚于发布完成，Worker 将 Version 标记 ready 的同一 SQL 只在
该 Version 仍为 current 时刷新投影。Star 的二维/三维尺寸计数和候选过滤直接读取该投影，不再对 actor 的每条
关系读取当前 Version 并现场执行 `LEAST/GREATEST`。原始宽/深/高仍由不可变 ComponentVersion 持有。

当前产品容量包络为用户总量不超过 1,000、单 actor Star 不超过 1,000、单 actor active Watch 不超过 1,000；
这些是规划规模，不是 API 硬拒绝阈值。隔离 PostgreSQL 14.17 使用 1,000 个 actor × 每人 1,000 条 Star（总计
1,000,000），`shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB`，数据已 ANALYZE。warm-cache
`EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` 结果仅证明查询形状，不代表生产 SLO：

| 场景 | 执行时间 | 关键计划事实 |
|---|---:|---|
| 无尺寸筛选 | 1.154 ms | actor 主键 Bitmap Index Scan 读取 1,000 条关系；Version 只按候选索引探测 |
| 三维选择性命中 10 条 | 0.407 ms | 直接过滤 Component 规范化投影，Version 仅执行 10 次索引探测 |
| 三维高命中 990 条 | 1.493 ms | 候选仍限于 actor 的 1,000 条关系，无临时文件 |
| 三维零命中 | 0.193 ms | 尺寸投影排除全部候选，Version 分支 `never executed` |
| 空 actor | 0.011 ms | 关系索引返回 0；Component 与 Version 分支均 `never executed` |
| 首页 / 最深支持页 | 1.423 / 1.484 ms | 均只排序 actor 的最多 1,000 条候选；最深页 quicksort 使用 102kB，无 spill |

因此 `STAR-PERF-02` 已关闭，且没有增加无法同时服务 actor 顺序和二维配对谓词的推测性尺寸索引。
`STAR-PERF-01` 按产品决定延期：继续保留页码交互；若产品批准交互变化、容量包络提高或实测接近每 actor
1,000 条，则重新开启 cursor/keyset 设计。

### 5.7 真实 Supabase v14～v18 部署验收

2026-09-05 在用户确认的 Supabase 项目 `wkwffflomyrgqpilsozx`、数据库 `postgres` 上执行 G8 环境门禁。
只读预检确认 PostgreSQL 17.6、当前用户 `postgres`、Goose v13；因此本次必须从 v14 开始，不能只执行原计划
中的 v15～v18。迁移前核心数据为 19 个 Component、20 个 ComponentVersion、0 个 legacy Subscription，
且没有 v14～v18 的部分 schema。未执行 reset、down、redo 或 reseed。

迁移前使用经固定 SHA-256 校验的 `pg_dump 18.6` 创建 custom-format 归档，精确覆盖本次可能读取、改写或删除的
既有表 `components`、`component_versions`、`component_subscriptions` 和 `goose_db_version`，包含结构、数据、
索引、约束与触发器。归档位于
`/tmp/ctbzbricks-supabase-affected-tables-before-v14-v18-20260905.dump`，SHA-256 为
`ce87f108bfbac428399e9d7d4373ec9ef6492de335e1ea3428932f17fb6db31c`。`/tmp` 归档是当前工作机上的临时恢复
材料，不替代长期备份策略；G8 完成前仍需验证正式恢复点与 rollback/failure drill。

`go run ./cmd/migrate up` 已依次成功执行 v14、v15、v16、v17、v18。迁移后验收确认：Goose v18；
`component_stars`、`component_watch_periods`、`component_domain_events` 存在，legacy
`component_subscriptions` 已移除；Watch 的 `ended_reason`、Component 当前逻辑尺寸三列、关系驱动索引、9 个
关键已验证约束及 Domain Event INSERT 校验/UPDATE-DELETE 不可变触发器均存在。数据守恒为 19 个 Component、
20 个 ComponentVersion；Star、Watch period、Domain Event 均为 0。真实库没有 active Component，因此 v18
回填 0 行尺寸投影符合预期。再次执行 `up` 返回 `no migrations to run`，最终版本仍为 v18。

### 5.8 G8 public router 删除与 Preview RLS 收口

2026-09-05 以 Go-only 启动拓扑运行真实 Chrome：Component 列表和“我的订阅”页只访问 `/api/v1`；未登录
请求返回 `auth.authentication_required`，失效 bearer 返回 `auth.session_invalid`。真实用户登录并硬刷新后
`/api/v1/auth/session` 为 200；owner Draft、Version、BOM、Preview 和 source 签名下载正常，Watch 列表正常，
跨 owner Component 与 Version 均返回 404 且不显示 owner 控件。`zh-CN` 与 `en-US` 页面壳、登录态/未登录态
错误及来回切换通过。验收中发现列表、Watch 和详情错误对象曾固化切换前译文，现三页在 locale 变化时重新
请求并使用当前结构化错误译文；未增加文案键或 locale 分支。

FastAPI 已取消 `create_component_repo_router` 挂载并删除旧 public router、专用 DTO 与仅验证旧 HTTP 合约的
测试；Component translation 的旧 Python public endpoint 同步移除。新增静态契约验证共享 Python 配置不能
重新声明 `/api/components*` 或 `/api/component-*`。仍被 fitting/维护工具调用的算法、模型和 Storage
辅助模块保留，但不构成 Component Repo public API 或 task consumer。

真实 Supabase PostgreSQL 17.6 的 Alembic revision 已从 `20260823_0024` 升到 `20260905_0025`。升级前
函数定义证实 Go Preview 分支仍引用已由 Goose v14 删除的 `component_repo.component_subscriptions`；升级后
helper 不再引用该表、`component_stars` 或 `component_watch_periods`，且明确要求 owner，或 `active`
Component + 非 Draft Version + verified derived Artifact。四条 Component Storage policy 均仍限定
`authenticated` role；INSERT 继续使用 pending upload-session 精确 key helper。精确 INSERT policy 上线后
真实库已有 10 个 completed upload session 与 10 个 verified Supabase Artifact，v25 未改写 INSERT policy。
后续以真实短生命周期 Supabase Auth 身份、disposable active Component 和受控 upload session 执行网络矩阵：
non-owner Preview 为 `200`，下载正文与数据库 SHA-256 一致；任意 key 和过期 session key 都被 provider
按 RLS 拒绝，精确 pending key 控制请求为 `200`。Supabase Storage 外层返回 `400`，正文
`statusCode=403` / `Unauthorized` 表达授权拒绝；这不是 Go API 参数校验错误。Go API 以相同 viewer JWT
读取 Component/Preview 均为 `200`，Watch/Unwatch 为 `200/204`。

本次验证：`backend-go make check`、隔离 PostgreSQL 0→v18/回滚/Worker 恢复、前端 i18n check/71 tests/build、
Python 295 tests、Python compile/cutover contract 与 `git diff --check` 均通过。真实 Chrome 未登录/登录双语言、
session 刷新、owner Preview/source、cross-owner 404 与 `/api/v1` 网络路径通过；真实 Supabase Alembic v25
revision/policy/function definition 复核通过。临时 Auth、Storage object、viewer upload session/关系和 active
测试 Component 均为 0；disposable Component 的 immutable 来源链按产品保留策略转为 archived 历史，不以
关闭 trigger 的方式伪造物理清理。

### 5.9 G8 恢复点、rollback/failure drill 与真实指标

最终正式 RLS fixture 写入前在仓库外目录
`/Users/dujun/Documents/ctbzbricks-backups/g8-20260905T133920Z-pre-fixture` 创建权限 `700/600` 的正式应用
恢复包。它包含完整 `component_repo` schema（323 个 TOC 条目）、Goose/Alembic 控制表（10 个 TOC 条目）、
Storage RLS 定义快照，以及同一 `REPEATABLE READ` 快照下的 G8 业务依赖闭包；18 个 CSV 与控制文件均有
SHA-256。包总量约 4.2 MB，明确排除本次不写入的 bulk Part Library geometry/connectivity/preview/search 数据，
也不声称包含 Supabase Storage 对象正文。

该包已在全新 PostgreSQL 17.11 实例实际恢复：19 个 Component、20 个 Version、58 个业务引用 Artifact，
`invalid_constraints=0`。随后注入事务失败，临时列未泄漏；Goose `18 -> 17 -> 18` 成功，Component/Version
行数守恒。`RESTORE_DRILL.txt` 和 `REAL_RLS_GATE.txt` 已加入同目录 SHA-256 清单。
清除失败尝试产生的不完整归档后，最终目录只保留正式恢复材料；`SHA256SUMS` 覆盖的 24 个文件已逐一使用
OpenSSL 复核通过。

真实 Supabase PostgreSQL 17.6 指标快照：数据库 469,011,603 bytes、12 个采样时 active connection、
`deadlocks=0`、`temp_bytes=0`、`invalid_indexes=0`、超过 60 秒的 `idle in transaction=0`。门禁期间发现的三条
失败备份遗留长事务已按精确 PID 终止。独立 Go API `/metrics` 记录 Watch/Unwatch succeeded 各 1、failed
各 0；本次网络耗时是开发环境单次样本，不作为生产 SLO。

发布收口时再次只读核验真实环境：PostgreSQL `17.6`、Goose `18`、Alembic `20260905_0025`；active
Component、G8 临时 Auth、G8 Storage object、无效索引和超过 60 秒的 `idle in transaction` 均为 `0`。
最终全量门禁为 Go `make check`、隔离 PostgreSQL `make test-postgres`、前端 15 files / 71 tests + build、
Python 295 tests、`git diff --check` 全部通过。

### 5.10 WATCH-3/4 动态 Feed

2026-09-09 产品确认 Feed 采用 pull/read-time 语义：发布后再 Watch 可以读取窗口内既有更新；发布后 Unwatch
则在下一次读取立即移除。由此废止 2026-09-06 的 event-time recipient、delivery、notification、重试、backlog
和独立 Notification Worker 方案。Task `outbox_events` 仍未修改，GLB/算法 Worker 也未改变。

Goose v20 仅新增 `(component_id,occurred_at DESC,id DESC)` 发布事件索引。Feed SQL 从 actor active partial
Watch index 驱动，closed history 不参与；按 `occurred_at DESC,event_id DESC` keyset，默认 30 天，页面支持
7/30/90 天，不执行 exact count。页面固定后才加载 Version 和 locale-aware Component 展示字段；Release Note
保持作者原文。`component_watch_feed_requests_total{result}` 与 `component_watch_feed_duration_seconds` 使用固定
低基数标签观测同步读取结果和耗时，不存在 notification backlog 指标。

新增 `GET /api/v1/component-watch-feed`；当前由组件广场“个人订阅”页签调用。PUT Watch Body 收敛为唯一偏好字段
`{level:"releases_only"}`，不再写 locale/timezone/catalogVersion。双语言资源版本更新为
`frontend-2026.09.09.1`。

2026-09-11 实现复核补齐两项契约：管理列表 cursor 现在绑定规范化后的 `locale/query/category`，换筛选条件继续
翻页会稳定返回 validation error；Goose v21 允许 official Component 的合法发布事件以 Version `created_by`
作为受信 actor，同时继续要求 user Component actor 等于 owner。集成测试覆盖同时间事件的 UUID tiebreaker、
首屏后新增事件不插入旧 cursor 序列、刷新后可见、official reviewed translation 以及用户名称/Release Note 原文。

隔离计划门禁使用 PostgreSQL 14.17、1,000 actor × 1,000 active Watch、1,000,000 closed period、1,000
Component、92,700 发布事件（90,000 窗口外、2,700 窗口内）和 100 条 reviewed translation；`shared_buffers=128MB`、
`work_mem=4MB`、`effective_cache_size=4GB`，数据已 ANALYZE。查询采用每个 active Component 先按复合索引截断
`page_size` 候选再做全局 Top-N，结果等价且把候选上界固定为 `active Watch × page_size`。warm-cache 本地查询形状：

| 场景 | 执行时间 | 计划结论 |
|---|---:|---|
| Feed 窄窗口首屏 | 1.940 ms | actor active partial index + Component/time event index，无 closed 扫描 |
| Feed 31 天高匹配 | 3.154 ms | 每 Component 有界 LATERAL 探测，全局 Top-N 无 spill |
| Feed 当前包络深 cursor | 3.451 ms | row-value cursor 进入事件 Index Cond，无 OFFSET |
| Feed 空 actor | 0.027 ms | active index 返回 0，事件内层不执行 |
| Watch 管理列表无筛选/高匹配 | 2.490 / 3.008 ms | actor active index 驱动，closed history 不参与 |
| Watch 管理列表深 cursor | 0.354 ms | cursor 进入 actor-time Index Cond |

以上时间只证明本机查询形状，不是生产 SLO。真实 Supabase 已在 2026-09-12 从 v20 升级到 v23，并验证 1 条当前
可见历史事件能够通过公共 Feed API 返回；该事实不代表派生图片、浏览器交互或生产查询计划/延迟已经验收。

```text
backend-go make check                                      PASS
backend-go make test-postgres                              PASS（0 -> v23 -> v22 -> v23、启动与集成契约）
RUN_WATCH_LIST_PLAN_TEST=1 RUN_WATCH_FEED_PLAN_TEST=1 ... PASS（上述容量与计划门禁）
RUN_PUBLIC_FEED_PLAN_TEST=1 ...                           PASS（100,000 事件/entry；0.138/53.097/0.142/0.128 ms）
frontend npm run i18n:check                                PASS（2 locales / 10 namespaces）
frontend npm test                                          PASS（20 files / 90 tests）
frontend npm run build                                     PASS
backend .venv-app/bin/python -m pytest                     PASS（296 tests）
```

## 6. 未关闭门禁

### 6.1 G8 发布与环境门禁

- [x] 已明确确认真实 Supabase 项目 `wkwffflomyrgqpilsozx` / 数据库 `postgres`，创建迁移前归档并从实际 Goose
  v13 升级到 schema head v18；schema/data contract 与重复 `up` 无操作均通过。详细证据见 5.7。
- [x] 真实用户 JWT 下的 owner Preview/source、cross-owner 404、第二身份 non-owner Preview 正向、任意/过期
  upload key RLS 拒绝和精确 pending key 控制请求均通过；provider 拒绝契约为外层 `400` + 正文
  `statusCode=403` / `Unauthorized`。
- [x] 完成登录态/未登录态 `zh-CN/en-US` 浏览器路径、刷新会话、401/404 与隔离 Worker 恢复；三处错误态
  locale 切换缺陷已修复。403 归入上一条 Storage RLS 网络样本门禁。
- [x] 删除旧 Python Component Repo public router、专用 DTO、旧 HTTP tests 与 Component translation public
  endpoint；其他 Python 领域和共享算法模块不得重新承接 Component Repo public API/task。
- [x] 正式应用恢复包、PostgreSQL 17.11 实际恢复、Goose `18 -> 17 -> 18`、故障注入回滚和真实环境指标已验证。

### 6.2 Star review 跟踪

- [ ] `STAR-PERF-01`（Deferred）：产品决定保留页码交互；当前 1,000 条/actor 最深页计划已验证。只有交互变更获批、容量提高或观测接近边界时重新开启 cursor/keyset。
- [x] `STAR-PERF-02`：v18 权威规范化投影已由发布/Preview 事务维护，并通过 1,000,000 总关系、1,000 条/actor 的尺寸计划门禁。
- [ ] `STAR-CONSISTENCY-01`：冻结 Count/List 一致性语义；需要一致时改为单语句或显式一致读快照。
- [ ] `STAR-UI-01`：custom Group 候选去除前端 first-100 假完整集合，补服务端分页/搜索和连续操作测试。
- [ ] `STAR-A11Y-01`：为 Star 图标按钮补 typed `aria-label` 与双 locale 键盘测试。
- [ ] STAR-3：1,000,000 总关系、多 actor 与 warm-cache 计划已完成；冷缓存、生产版本/参数、限流、指标和灰度验收仍待完成。

上述编号的评审原文、量化证据和客观关闭条件保存在 Star 方案与路线跟踪文档中。

### 6.3 Watch 路线跟踪

- [x] WATCH-0 前置契约：删除/归档策略、用户 1,000、active Watch 1,000/actor、closed 重评点和当前关系
  read-time Feed 语义已冻结；详细值见 Watch 方案与路线文档。
- [x] `WATCH-CAPACITY-01`：按 1,000 actor × 1,000 active 与 1,000,000 closed 重评点验证列表、最深 cursor、
  Unwatch 和 Rewatch；closed 容量已按 Rewatch 频率 × 观察窗口建模。本地时间仅作为查询形状证据。
- [x] WATCH-1：偏好存储、幂等 API、绑定 locale/query/category 的 keyset 列表 cursor 和详情入口。
- [x] 当前在线 Web 阶段不提前实现 `mutationId`；没有离线队列或自动网络重放，继续采用数据库操作顺序 last-write-wins。
- [ ] Watch 强意图幂等（条件门禁）：只有引入离线队列或自动重放前，
  冻结 `mutationId` 或等价协议，防止跨 Unwatch 的延迟旧 PUT 被解释为 Rewatch。
- [x] WATCH-2（仓库）：发布事务、不可变唯一事件、user owner / official Version creator actor 约束、回滚/并发门槛和正式
  `component_domain_event_total` Prometheus 指标均完成；发布 Handler 不同步 fan-out watcher。
- [x] WATCH-3（仓库）：当前 active Watch 动态 Feed API、事件复合索引、冻结窗口 cursor、发布前后 Watch/Unwatch
  语义和 active 1,000/actor + 100 万 closed 计划门禁均已实现；不创建 delivery/notification 或专属 Worker。
- [x] WATCH-4（仓库）：组件广场“个人订阅”Feed、7/30/90 天窗口、刷新/滚动续页，以及独立“我的订阅”管理页和双语言资源已完成。
- [ ] WATCH-DEPLOY：真实 Supabase 已应用 v23，公共 Feed API、renderer v3 基准、renderer v4 材质集成及 Docker 生产封装通过；2026-09-13 已将当时 4 个非终态任务安全取消并确认 queued/running 为 0。队列状态会变化，联合验收开始前仍须重新检查；镜像/服务器运行、v6 Preview 与 v4 Worker 真实任务、浏览器以及生产 PostgreSQL/渲染资源计划验收按产品决定留待后续一起完成。

## 7. 下一步顺序

1. 在联合验收时先备份并把真实 Supabase 从 v23 升级到仓库 v24，再确认没有旧 renderer version 的 queued/running task；构建并启动固定标签的三个镜像，受控生成 v6 Preview 并发布一条新版本，确认 GLB/图片 metadata 分别为 `ldraw-studio-pbr-v1` 与 `blender_cycles_4_1`，完成 Watch、目录 cursor、真实浏览器、渲染资源和生产 PostgreSQL 计划/延迟验收。
2. 持续采集 active Watch/actor、Feed 窗口内发布量、Rewatch 频率、closed 总量、表/索引大小与
   autovacuum/bloat；接近当前包络 70% 或包络提高时重新执行计划门禁。本地时间不得作为生产 SLO。

## 8. 后续更新格式

每次只更新以下内容，禁止恢复逐次操作流水账：

```text
日期 / 阶段 / 状态
契约变化：API、schema、Task、Storage、i18n
完成事实：只列可验证结果
验证证据：测试、migration、EXPLAIN、真实环境版本
未关闭门禁：稳定 ID、owner phase、客观关闭条件
```

专项设计、长执行记录和评审讨论写入对应路线文档；本文只保留指向它们的结论。

## 9. 2D 工具专项（2026-09-07）

P2D-0～P2D-3 代码迁移与本地验证完成；真实环境已升级至 v19 并验证上传、编辑和拼接，剩余发布门禁见 [2D 迁移记录](go_pixel_2d_migration.md)。Go Worker 消费三种 `pixel_2d.*` 任务，FastAPI 2D 入口已移除，前端只使用认证 `/api/v1`。成功修订不长期保存原始图片正文；输入只服务持久任务与重试，完成后幂等删除。页面把 projectId 写入 URL，使用轻量 Task API 显示可恢复进度，关闭页面不取消任务。P2D-RELEASE-01、P2D-SQL-01、P2D-DATA-01、P2D-STORAGE-01 的关闭条件保留在专项文档。

## 2026-09-06 P2D-3 真实运行与预览卡顿修复

详见 [独立 2D 迁移记录](go_pixel_2d_migration.md#2026-09-06-真实运行与卡顿排查p2d-3)。真实库 v19、227 色/27 Plate 目录已导入；Go-only 上传、编辑、拼接均成功，浏览器已显示结果。默认不启动 Python，DEM/3D 工具入口关闭并保留归档。预览计算移出主线程、绕开像素循环的本地化 Proxy，并取消离页轮询。前端 79 项、构建、i18n 与 Python 296 项通过。真实双语言下载、第二身份与修复后照片预览复测仍是门禁，不标记 P2D-3 全部完成。

Go 全包与隔离 PostgreSQL v19 集成复核通过，包含持久任务、进度插值和启动无 DDL。服务端分段延迟仍按 P2D-LATENCY-01 跟进。

2026-09-07：2D 页面改为可离页恢复的异步任务体验，任务状态轮询切换到共享轻量 Task API；成功修订删除临时 source/input 正文，相同内容的并发任务使用独立 UUID。前端 79 项/i18n/build、Go 全包、隔离 PostgreSQL v19 和 Python 296 项通过。上传直传及失败终态/孤儿清理仍由 P2D-LATENCY-01、P2D-STORAGE-01 跟进。
