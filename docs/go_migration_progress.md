# Go 后端迁移进度

> 最后更新：2026-09-05（G8 真实 RLS、恢复与发布门禁关闭）
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

当前 schema head 为 **v18**。Go API 已覆盖目录、版本、分组、Star、Watch、Artifact、上传、Import、Candidate、
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
| Watch | 幂等 Watch/Unwatch、筛选/keyset 管理页、详情投影、发布领域事件、mutation 指标 | 尚无 recipient snapshot、fan-out、通知或 Feed |
| Upload/Import | owner-scoped 直传、complete `202`、持久处理链、状态恢复 | complete 是写交互终点，不等待 Worker |
| Task | logical job、execution/attempt、依赖、租约、重试、取消、事件 | PostgreSQL 是权威状态，不使用进程内队列 |
| Scene/Candidate | Studio/LDraw 解析、多 root expansion、hash/signature、relation 审核 | source 与 derived Artifact 分离 |
| Preview | Component/Part meshopt GLB、partial preview、Box、静态缩略图 | Storage 保存正文，数据库保存状态和引用 |
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

## 5. 最新里程碑：Watch 偏好、发布事件与关系生命周期

日期：2026-09-04
阶段：G8 / Component Repo 关系能力
状态：WATCH-1～2 complete and verified in isolated environment；WATCH-3～4 未完成

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
  重评。WATCH-3 定义并验证 completion watermark 或 recipient snapshot 前不得删除、合并或覆盖历史区间。
- 新增 Watch 结构化错误和双语言 typed semantic key；机器 level、ID、时间和 API 字段不翻译。
- Goose v16 新增独立 `component_domain_events`。Version 首次发布在原 serializable transaction 内取得同
  Component exclusive activity lock，更新 Version/current version 后插入事件并分配 `event_seq`；事件与业务
  状态原子提交。数据库拒绝非 published/mismatched 目标、重复 Version 事件及 UPDATE/DELETE；集成测试确认
  有效订阅区间满足 `started_seq < event_seq < ended_seq`。
- v1 事件 payload 固定 `{}`；不复制 Version Label、Release Note/locale、Component 名称、Artifact 路径或译文。
  现阶段不复用 Task outbox，不创建 delivery、recipient snapshot、通知或 Feed；v16 不回填迁移前的历史发布。
- Go API `/metrics` 以 Prometheus 文本格式暴露固定低基数
  `component_domain_event_total{event_type="component.version.published.v1",result}`，其中 result 仅允许
  `committed/failed`。只在最终
  事务结果确定后计一次，内部 retry 不重复；指标不包含 actor、Component ID 或用户内容。
- `/metrics` 同时暴露 `component_watch_mutation_total{action,result}`；action 固定为 `watch/unwatch`，result
  固定为 `succeeded/failed`，幂等重复操作计为 succeeded，全部事务重试结束后每次 Service 调用只计一次。
- Goose v17 为 Watch 历史增加 `ended_reason` 和 `(component_id,actor_id) WHERE ended_seq IS NULL`。Component
  DELETE 在 exclusive activity lock 内软删除、冻结公共结束边界并原子入队 `component.relationships.cleanup`；
  列表立即隐藏目标，Worker 以 5,000 条 actor-keyset 短事务关闭 Watch 并物理删除 Star。任务重放是空操作，
  不创建 recipient snapshot、通知或 Feed。

### 5.2 发布事件 SQL 设计复核

事件按每次新 Version 发布追加，驱动关系随发布总量单调增长；actor/tenant 分布、筛选、排序、分页和 exact count
在 WATCH-2 均不适用，因为没有读取 API 或 fan-out 查询。写路径只有一次点 INSERT：主键、
`(event_type,component_version_id)` 与 `event_seq` 三个唯一索引分别承担身份、业务去重和共同顺序域不变量，
不存在推测性查询索引。WATCH-3 必须根据实际 recipient candidate、事件时点区间和 100 万关系数据重新冻结
查询、索引与 EXPLAIN，不能把 v16 唯一索引当作 fan-out 性能证据。

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

- [ ] WATCH-0：删除/归档关系策略已冻结并由 v17 实现；用户总量 1,000、active Watch 1,000/actor 的当前容量包络已冻结；closed period 永久保留且 1,000,000 条触发重评。通知渠道、频控、去重窗口和生产 SLO 仍待冻结。
- [x] `WATCH-CAPACITY-01`：按 1,000 actor × 1,000 active 与 1,000,000 closed 重评点验证列表、最深 cursor、
  Unwatch 和 Rewatch；closed 容量已按 Rewatch 频率 × 观察窗口建模。本地时间仅作为查询形状证据。
- [x] WATCH-1：偏好存储、幂等 API、keyset 列表和详情入口。
- [x] 当前在线 Web 阶段不提前实现 `mutationId`；没有离线队列或自动网络重放，继续采用数据库操作顺序 last-write-wins。
- [ ] Watch 强意图幂等（条件门禁）：只有引入离线队列或自动重放前，
  冻结 `mutationId` 或等价协议，防止跨 Unwatch 的延迟旧 PUT 被解释为 Rewatch。
- [x] WATCH-2：发布事务、不可变唯一事件、回滚/并发/event-time 门槛和正式
  `component_domain_event_total` Prometheus 指标均完成；发布 Handler 不同步 fan-out watcher。
- [ ] WATCH-3：closed history 已冻结为永久保留；仍需基于 v15 append-mostly period 与共享 sequence 冻结 event-time fan-out 查询、completion watermark 和 Component 侧索引；随后生成 inbox/delivery，补退订竞态、去重、限流、失败重试，并按 active
  1,000/actor 与另行估算的历史总量提供生产计划证据。
- [ ] WATCH-4：“我的订阅”管理页已完成；通知中心、未读状态、批量标记以及可访问性/双语言真实浏览器验收未完成。

## 7. 下一步顺序

1. WATCH-3 前冻结容量、通知渠道、频控、去重/保留和 SLO，并补齐 fan-out 专属指标；fan-out 必须使用
   PostgreSQL 持久执行协议，但不得把 Task `outbox_events` 直接改造成 Component 领域事件或用户通知表。
2. 持续采集真实 Rewatch 频率、closed 总量、表/索引大小与 autovacuum/bloat；接近 1,000,000 closed、容量
   包络提高或准备 WATCH-3 event-time 查询时，使用生产 PostgreSQL 版本重新执行计划门禁。本地时间不得作为
   生产 SLO。

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
