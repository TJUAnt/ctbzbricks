# Component Repo Watch 功能方案与路线跟踪文档（用途：实现、验收与容量重评）

> 文档状态：Approved / Implemented in repository
> 最后更新：2026-09-16
> 当前方案：读取时基于当前 active Watch 动态聚合发布 Feed
> 非目标：推荐算法、recipient fan-out、推送通知、通知中心、Watch 专属 Worker

## 1. 文档用途

本文是 Component Repo Watch 的产品、交互、数据、API、查询性能和路线状态的唯一专项依据。它用于：

- 判断一次 Watch、Unwatch、Rewatch 和 Feed 读取是否符合产品语义；
- 指导前端“我的订阅”页、Go API、PostgreSQL schema 和 SQL 的实现；
- 记录当前容量包络、性能门禁和未来重新设计的触发条件；
- 防止把旧的 event-time recipient snapshot/fan-out 方案重新引入代码。

## 2. 产品目标

用户可以显式订阅一个公开的、非本人 Component，并在“我的订阅”中完成两件事：

1. 管理当前订阅关系；
2. 查看当前订阅 Component 在选定时间点之后的版本发布更新。

Feed 是按需查询视图，不是提前投递给用户的通知副本。用户当前 Watch 什么，加载时就看到这些 Component 的
窗口内更新。

## 3. 冻结的核心语义

### 3.1 Watch 资格

首次 Watch 或 Rewatch 必须同时满足：

1. Component 存在且未删除；
2. 不是本人拥有的 Component；
3. Component 状态为 `active`；
4. 至少存在一个未删除、非 Draft Version。

Watch 不授予读取、编辑、Fork、Group 或 Storage 权限，也不隐式创建 Star。

### 3.2 重复 Watch 与 Rewatch

- 当前存在 active period 时再次 PUT 是重复 Watch：返回原 `watchedAt`，不新增、不改写历史。
- 当前没有 active period 时 PUT 是首次 Watch 或 Rewatch：追加一个新 period。
- 当前 Web 采用数据库提交顺序的 last-write-wins。
- 尚无离线 mutation 队列或自动重放，因此暂不引入 `mutationId`。引入这些能力前必须重新冻结强意图幂等协议。

### 3.3 Feed 成员资格

Feed 每次读取都只看“此刻的 active Watch”：

- 发布后再 Watch：只要发布事件在所选时间窗口内，就可以看到；
- 发布后 Unwatch：下一次加载或刷新时不再看到该 Component 的更新；
- Rewatch：重新获得当前窗口内该 Component 的既有发布更新；
- closed period 不决定 Feed 资格，也不参与 Feed SQL；
- Component 删除/归档后立即从 Feed 消失，持久清理随后关闭 active period；
- Feed 不保存已读/未读，不创建每用户通知记录。

这意味着 Feed 回答的是“我当前订阅的对象最近发生了什么”，不是“事件发生时系统曾经给我投递过什么”。

## 4. 当前容量与增长模型

当前规划包络不是 API 硬限制：

| 维度 | 当前设计值 | 增长方向 |
|---|---:|---|
| 用户总量 | ≤ 1,000 | 后续会提高 |
| active Watch / actor | ≤ 1,000 | 后续会提高 |
| active Watch 总量 | ≤ 1,000,000 | 随用户和订阅增长 |
| closed period | 1,000,000 为重评点 | 随 Rewatch 单调增长 |
| 发布事件 | 约 100/日，突发 20/5 分钟作为当前规划样本 | 随发布长期增长 |
| 默认 Feed 窗口 | 30 天 | UI 可选 7/30/90 天 |
| Feed page | 默认 20，最大 100 | keyset 续页 |

当任一观测量接近当前包络 70%、产品提高包络，或 Feed 的时间窗口/发布频率显著提高时，必须用生产 PostgreSQL
版本和真实分布重新执行计划门禁。不得把上述规划数字变成未经产品批准的拒绝错误或静默截断。

## 5. 用户界面

### 5.1 Component 详情页

- 非本人且满足资格时展示“订阅更新”按钮；
- 当前已订阅时展示“已订阅/取消订阅”；
- 操作可乐观更新，但失败必须回到服务端权威状态；
- Watch 和 Star 是两个独立操作，不互相改变。

### 5.2 “我的订阅”页

页面由两个区块组成。

“订阅更新”区块：

- 默认读取最近 30 天，可切换最近 7/30/90 天；
- 按发布时间倒序展示 Component 名称、版本、revision、发布说明、分类和时间；
- 支持刷新和“加载更多”；
- 空状态明确表示“当前时间范围没有更新”，不暗示系统推荐内容；
- 取消订阅后立即移除页面上该 Component 已加载的 Feed 条目。

“已订阅组件”区块：

- 服务端按名称/ID、分类筛选；
- 展示订阅级别、当前公开版本、订阅时间；
- 使用 cursor 加载更多，不显示伪造的 exact total；
- 支持取消订阅，失败时恢复原位置。

所有界面文案使用 typed semantic keys。用户发布说明保持原文；official Component 名称只使用 reviewed
translation。

## 6. 总体架构

```text
Publish Draft
  -> serializable transaction
  -> publish Version + set current Version
  -> append immutable component_domain_event

Watch / Unwatch
  -> short serializable transaction
  -> append or close component_watch_period

GET Watch Feed
  -> actor current active Watch IDs
  -> visible active Components
  -> domain events after windowStart
  -> keyset page
  -> page-level Version and localized Component projection
```

Watch 没有独立进程。现有 Go Task Worker 继续负责 Component 导入、关系、预览、生命周期清理等持久任务；
GLB/几何计算 Worker 的职责与运行方式不因本功能改变。

## 7. 数据模型

### 7.1 `component_watch_periods`

权威保存 Watch/Rewatch 历史：

- `actor_id/component_id/watch_level`；
- `started_seq/watched_at`；
- `ended_seq/unwatched_at/ended_reason`；
- sequence 只表达 Watch/Rewatch 审计和 Component 删除统一生命周期边界，不参与 Feed 成员资格或 cursor；
- `(actor_id,component_id) WHERE ended_seq IS NULL` 保证唯一 active period；
- actor active-time partial index支持管理列表。

closed period 当前 append-only、永久保留，单独按 Rewatch 频率和保留期评估。它不是 Feed 历史账本。

### 7.2 `component_domain_events`

每次 Draft 首次成功发布追加一个 `component.version.published.v1`：

- 事件与 Version 发布同事务提交；
- `event_seq` 只保留发布审计顺序，不与 Watch period 比较来推导 recipient；
- 同一 Version 的同类事件唯一；
- 数据库拒绝 UPDATE/DELETE；
- user 事件 actor 必须是 Component owner；official 没有 owner，事件 actor 必须是 Version `created_by`；
- payload v1 固定 `{}`，不复制名称、Release Note、译文或 Storage 路径；
- v16 不回填迁移前已发布 Version。

### 7.3 Feed 索引

Goose v20 只添加与查询谓词一致的索引：

```sql
(component_id, occurred_at DESC, id DESC)
INCLUDE (event_type, component_version_id)
```

不创建 `component_event_deliveries`、`user_notifications` 或 Component notification 指标表，也不复用 Task
`outbox_events`。

## 8. API 契约

### 8.1 Mutation

- `PUT /api/v1/components/:componentId/watch`
  - Body：`{ "level": "releases_only" }`
  - 返回：`{componentId,watching,level,watchedAt}`
- `DELETE /api/v1/components/:componentId/watch`
  - 幂等 `204`

PUT 不再接收 locale、timezone 或 catalogVersion，因为 Feed 展示上下文在读取时确定。

### 8.2 管理列表

`GET /api/v1/component-watches?locale&limit&cursor&query&category`

- 排序：`watched_at DESC, component_id DESC`；
- row-value keyset；
- 返回 `items,nextCursor`，不返回 exact count。

### 8.3 动态 Feed

`GET /api/v1/component-watch-feed?locale&since&limit&cursor`

- `since` 是 RFC 3339 时间点；为空时默认最近 30 天；
- 排序：`occurred_at DESC,event_id DESC`；
- 首次响应返回规范化 `windowStart`；
- cursor 冻结 `windowStart` 和最后一项排序键；
- cursor 与显式 `since` 不一致时返回 `request.validation_failed`；
- 返回 `items,nextCursor,windowStart`，不返回 exact count。

新事件若在用户翻到后续页时发布，不插入旧 cursor 的前序页；刷新首屏即可看到。这避免新事件造成跨页重复或跳跃。

## 9. SQL 设计与性能契约

Feed 的 driving relation 必须是 actor-scoped active Watch：

1. 从 active partial index 取得当前 actor 最多约 1,000 个 Component ID；
2. 联接 active、未删除 Component，立即排除生命周期失效目标；
3. 对每个候选使用 Component/time/event 复合索引读取窗口内事件；
4. 按稳定双键排序并固定 `limit+1` 页面；
5. 只对页内 ID 读取 Version、Component 名称和 reviewed translation。

禁止：

- 从全量事件或全量 Watch 表开始，再用宽泛 `EXISTS/OR` 过滤 actor；
- 让 closed period 进入 Feed；
- `OFFSET` 深翻页；
- 每页附加 exact `COUNT`；
- 页面固定前逐行读取翻译或展示聚合；
- 用固定 first-N 假装完整集合。

显式性能门禁覆盖：首屏、窄窗口、高匹配窗口、空 actor、当前包络最深 cursor、多 actor 分布、100 万 active
和 100 万 closed period。`EXPLAIN (ANALYZE,BUFFERS,SETTINGS)` 必须确认 active Watch 与事件索引驱动、无 closed
全扫、无 skipped-row OFFSET、无临时文件 spill。本地时间只证明查询形状，不作为生产 SLO。

2026-09-09 本地 PostgreSQL 14.17 门禁使用 100 万 active、100 万 closed 和 92,700 条发布事件通过：Feed
窄窗口、高匹配、深 cursor、空 actor 分别为 1.940ms、3.154ms、3.451ms、0.027ms（warm-cache）。最终查询
对每个 active Component 先按复合索引最多取得 `page_size` 条候选再做全局 Top-N；因为全局一页不可能包含某
Component 排名超过页面大小的事件，所以该截断结果等价，并把事件候选上界固定为 `active Watch × pageSize`。

## 10. 并发与生命周期

- Watch/Unwatch 使用 Component 派生的 shared advisory transaction lock；
- Publish 和 Component 删除使用同 key 的 exclusive lock；
- Publish 不遍历 watcher，事件写入失败会回滚整个发布事务；
- 删除事务先令 Component 不可见并持久入队关系清理；Feed 联接即时隐藏目标；
- 清理 Worker 分批关闭 Watch、删除 Star，重复执行为空操作；
- 即使清理尚未完成，Feed 也不会因为残留 active period 泄漏已删除 Component。

## 11. 国际化与内容边界

- `eventType/watchLevel/ID/cursor/since/windowStart` 是机器值，不翻译；
- UI 标题、按钮、时间范围、空态和错误通过双语言 typed keys；
- user Component 名称和 Release Note 保持作者原文及 `contentLocale`；
- official Component 名称只选择请求 locale 下 reviewed translation，缺失时返回源内容和缺失标记；
- Feed 不把最终译文写入事件，因此切换语言后重新读取即可使用当前语言展示。

## 12. 可观测性

- `component_watch_mutation_total{action,result}`：Watch/Unwatch 成功/失败；
- `component_domain_event_total{event_type,result}`：发布事件 committed/failed；
- `component_watch_feed_requests_total{result}` 与 `component_watch_feed_duration_seconds`：动态 Feed 结果和耗时；
- 不存在 fan-out backlog、recipient、dead-letter 或通知重试指标；
- 所有指标禁止 actor、Component/event ID、查询文本和用户内容标签。

## 13. 测试与验收

功能集成必须验证：

- 重复 Watch 不新增 period，Rewatch 追加 period；
- 发布后再 Watch 可以看到窗口内旧事件；
- 发布后 Unwatch 下一次读取为空；
- Rewatch 恢复窗口内事件；
- Component 删除后立即从管理列表和 Feed 隐藏；
- 发布事件与 Version 状态原子提交、唯一且不可变；
- Watch 管理 cursor 绑定 locale/query/category，Feed cursor 冻结 since；非法或不匹配 cursor 拒绝；
- official translation 和用户 Release Note 内容边界；
- 双语言页面、API adapter、Go unit/integration、空库 migration up/down/up；
- 上述 SQL 计划门禁。

真实 Supabase 部署与仓库代码完成分开判断。v20 已在 2026-09-11 的受限前置操作中部署，v21～v23 已在 2026-09-12 部署，v24 已在 2026-09-15 部署；当前 Go API/前端/Worker 镜像发布、完整浏览器、Worker 图片和生产计划验收仍未执行。

## 14. 路线状态

| 阶段 | 状态 | 完成定义 |
|---|---|---|
| WATCH-0 | Complete | 资格、删除策略、当前容量、交互语义冻结 |
| WATCH-1 | Complete | period、幂等 Watch/Unwatch、详情投影、管理列表 |
| WATCH-2 | Complete in repository | 发布事务追加不可变领域事件和指标；v21 补齐 official Version 发布者约束 |
| WATCH-3 | Complete in repository | 当前 active Watch 的动态 Feed API、索引、cursor、语义/性能测试 |
| WATCH-4 | Complete in repository | “我的订阅”管理与 Feed UI、7/30/90 天、双语言和取消订阅联动 |
| WATCH-DEPLOY | In progress | 真实 Supabase 已应用仓库 head v24，迁移后任务队列和 Feed 终态回查通过；仍需发布当前应用并统一完成 Watch/广场真实浏览器、Worker 图片与生产版本计划验收 |

## 15. 重新设计触发条件

只有出现下列需求或量级变化时，才重新讨论物化 Feed 或异步投递：

- active Watch/actor 或用户数明显超过当前包络；
- 发布事件频率和查询窗口使读取时聚合不能满足 SLO；
- 产品要求事件发生时的收件人审计、未读状态、邮件/推送、跨设备已读或保证送达；
- 产品要求离线重放 mutation；
- 生产计划显示事件索引随机读取或排序成为主要瓶颈。

届时应作为新方案评估 pull、hybrid fan-out-on-read/write 或物化 inbox，不能把当前 Task `outbox_events`
直接改造成 Component 领域事件或用户通知表。

## 16. 决策记录

- 2026-09-01：WATCH-2 使用独立不可变领域事件，不复用 Task outbox。
- 2026-09-04：Component 删除立即隐藏关系，Worker 仅收敛持久关系。
- 2026-09-06：曾冻结 event-time fan-out 前置方案，但未部署。
- 2026-09-09：产品改为读取时按当前 Watch 聚合。旧 delivery/notification/recipient snapshot 与专属 Worker
  方案被明确废止；“先发布后 Watch 可见、发布后 Unwatch 不可见”成为权威语义。
- 2026-09-11：实现审查发现管理 cursor 未绑定筛选条件，并且 official Component 没有 owner 时无法写合法发布事件；
  仓库通过筛选绑定 cursor 与 v21 official Version 发布者约束补齐，部署和完整验收统一后置。
- 2026-09-16：关闭 WATCH-CLEAN-01～05。activity lock SQL 归入中性文件；strict/display locale 使用共享无业务依赖包；
  sequence 明确保留为审计和删除统一边界，但不参与 read-time Feed；v24 共享投影由目录/详情/Watch 跨入口契约测试约束。
