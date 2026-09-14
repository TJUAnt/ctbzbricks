# Component Repo Watch 详细设计

> 代码核对日期：2026-09-12
>
> 当前阶段：WATCH-1～WATCH-4 已在仓库完成；真实 Supabase 已部署到 v23，浏览器与生产查询计划验收待执行。
>
> 接口权威定义：[Component Repo API](../api.md)；产品、容量与路线决策：[Watch 方案与路线](../design/lego_design/component_repo_watch_design_and_roadmap.md)。

## 1. 职责和边界

Watch 是“当前用户订阅某个 Component 的版本发布更新”。它和 Star 完全独立：Watch 不创建 Star、不授予读取权限、
不改变 Group，也不生成邮件、推送、未读记录或收件人快照。

当前 Feed 使用 read-time 模型。读取 Feed 时，从 actor 当前 active Watch 出发关联时间窗口内的不可变发布事件：

- 发布后再 Watch，可以看到窗口内较早的发布；
- Unwatch 后下一次读取立即看不到该 Component 的更新；
- Rewatch 会新建一个历史 period，并重新获得当前窗口内事件；
- closed period 只保留关系历史和删除边界，不参与 Feed 查询。

## 2. 前端入口和状态流

| 功能点 | 页面逻辑 | 前端调用 | 成功后的状态 | 失败恢复 |
|---|---|---|---|---|
| 详情页 Watch | 非 owner 且 Component 可 Watch 时展示独立 Bell 按钮 | `watchComponent` | 乐观写入 `watching=true`，请求成功后使用返回值 | 增加详情页刷新令牌，重新读取服务端投影 |
| 详情页 Unwatch | 当前详情投影为 watching 时执行 | `unwatchComponent` | 乐观清空 Watch 投影 | 重新加载 Component，撤销错误本地状态 |
| 管理列表 | `/component-repo/watches` 首屏及筛选变化重新读取，只管理 active Watch | `listComponentWatches` | 保存 items 与 opaque `nextCursor` | 保留错误 code 渲染结果；locale 改变时重新请求 |
| 管理列表续页 | 点击“加载更多”时沿用同一筛选条件和 cursor | `listComponentWatches` | 按 `componentId` 去重并保留服务端顺序 | 当前页保留，状态转 error |
| 动态 Feed | 组件广场 `/model-plaza?tab=subscriptions` 默认最近 30 天，可选 7/30/90 天 | `listComponentWatchFeed` | 首屏使用新的 `since`；进入底部哨兵后续页仅发送 cursor | 当前已加载事件保留 |
| Feed 刷新 | 丢弃旧 cursor，以当前时间重新计算窗口起点 | `listComponentWatchFeed` | 替换当前 Feed | 显示结构化错误 |
| 管理页 Unwatch | 乐观移除管理条目；个人订阅 Feed 下次进入或刷新时按 read-time 语义重算 | `unwatchComponent` | 服务端 active period 关闭 | 请求失败时恢复管理条目 |

相关代码：

- 个人订阅 Feed：[ComponentWatchFeedPanel.tsx](../../frontend/src/componentRepo/ComponentWatchFeedPanel.tsx)
- Watch 管理页：[ComponentWatchListPage.tsx](../../frontend/src/componentRepo/ComponentWatchListPage.tsx)
- 组件广场页签：[ComponentRepoPage.tsx](../../frontend/src/componentRepo/ComponentRepoPage.tsx)、[组件广场详细设计](component_plaza.md)
- 详情页入口：[ComponentDetailPage.tsx](../../frontend/src/componentRepo/ComponentDetailPage.tsx)
- DTO 和请求适配：[componentRepoApi.ts](../../frontend/src/componentRepo/componentRepoApi.ts)
- 路由和路径：[main.tsx](../../frontend/src/main.tsx)、[appConfig.json](../../frontend/src/app/appConfig.json)
- 双语言资源：[zh-CN/componentRepo.json](../../frontend/src/i18n/resources/zh-CN/componentRepo.json)、[en-US/componentRepo.json](../../frontend/src/i18n/resources/en-US/componentRepo.json)

## 3. HTTP 接口与后端执行

### 3.1 Watch

`PUT /api/v1/components/:componentId/watch`

请求体固定为 `{ "level": "releases_only" }`。Gin Handler 只解码 Body、读取 JWT actor 和调用 Service。
`Service.Watch` 执行：

1. 校验 level 和 Component UUID；
2. 开启 serializable transaction；
3. 取得由 Component UUID 派生的 shared advisory transaction lock；
4. `GetComponentWatchTarget` 从 v24 `component_catalog_candidates` 一次读取删除边界、owner、状态、公开 Version 资格，以及 actor 当前 active period；
5. 本人 Component 返回 `component_repo.watch_own_component_forbidden`；
6. 已存在相同 active period 时直接返回原 `watchedAt`，不更新时间；
7. 首次 Watch 或 Rewatch 要求 Component 为 active 且存在非 Draft Version；
8. `CreateActiveComponentWatchPeriod` 追加 period。并发请求命中 active partial unique 后不覆盖原行，Service 重试并读取赢家；
9. transaction 最终成功或失败后记录一次低基数 mutation 指标。

### 3.2 Unwatch

`DELETE /api/v1/components/:componentId/watch`

`Service.Unwatch` 在 serializable transaction 和同一 shared activity lock 内执行 actor-scoped UPDATE：

- 仅关闭 `ended_seq IS NULL` 的当前 period；
- 同语句写 `ended_seq`、`unwatched_at` 和 `ended_reason=user_unwatched`；
- 关系不存在、已经关闭或 Component 已进入删除生命周期时返回 204；
- 不删除历史 period，也不改变 Star、Group 或 Component 权限。

### 3.3 Watch 管理列表

`GET /api/v1/component-watches?locale&limit&cursor&query&category`

`Service.List` 将 limit 限制为 1～100，query/category 分别限制为 200/128。查询从当前 actor 的 active partial
index 开始，按 `(watched_at DESC, component_id DESC)` keyset 分页。名称/ID 模糊搜索和 category 精确筛选只在
actor 的有界候选中执行；页面固定后再取 current Version 与 reviewed translation，不返回 exact count。

cursor 是 base64url JSON，包含边界和规范化后的 `locale/query/category`。续页改变任一筛选条件会返回
`request.validation_failed`，防止从不同结果集的旧边界继续。

### 3.4 动态 Feed

`GET /api/v1/component-watch-feed?locale&limit&cursor&since`

`Service.ListFeed` 默认窗口为最近 30×24 小时；首屏允许 RFC 3339 `since`。Feed cursor 冻结 `windowStart`，后续页
只从 cursor 恢复窗口，并以 `(occurred_at DESC,event_id DESC)` 继续。

SQL 先物化 actor 当前 active Watch，再从 v24 candidate projection 统一校验 Component 可见性和公开 Version 资格，并对每个 Component 使用
`(component_id,occurred_at DESC,id DESC)` 索引取得至多一页事件，做全局 Top-N 后才加载 Version、Component 和
`component_reviewed_translations`。Release Note 始终返回作者原文及 `releaseNoteLocale`。

后端代码：

- 路由与参数：[componentwatch/handler.go](../../backend-go/internal/componentwatch/handler.go)
- 业务服务与 cursor：[componentwatch/service.go](../../backend-go/internal/componentwatch/service.go)
- 请求/响应模型：[componentwatch/types.go](../../backend-go/internal/componentwatch/types.go)
- Watch 与 Feed SQL：[component_watches.sql](../../backend-go/db/queries/component_watches.sql)
- sqlc 生成代码：[component_watches.sql.go](../../backend-go/db/generated/component_watches.sql.go)（禁止手工修改）

## 4. 发布事件生产

Feed 的事件来自 `POST /api/v1/component-versions/:versionId/publish`。`component.Service.PublishVersion` 在一个
serializable transaction 中锁定 owner Draft、取得 Component exclusive activity lock、deprecated 其他 published
Version、发布目标、刷新 current version，最后插入唯一 `component.version.published.v1` 事件。任一步失败都会回滚
版本状态和事件。

事件只保存稳定标识、actor、发生时间与空 payload，不复制 Component 名称、译文或 Release Note。v21 数据库触发器
要求 user Component 的 actor 等于 owner；official Component 的 actor 等于不可变 Version `created_by`。

代码位置：

- 发布事务：[component/service.go](../../backend-go/internal/component/service.go)
- 事件 SQL：[component_domain_events.sql](../../backend-go/db/queries/component_domain_events.sql)
- v16 事件表：[00016_component_domain_events.sql](../../backend-go/db/migrations/00016_component_domain_events.sql)
- v20 Feed 索引：[00020_component_watch_feed.sql](../../backend-go/db/migrations/00020_component_watch_feed.sql)
- v21 official actor 约束：[00021_component_official_publish_events.sql](../../backend-go/db/migrations/00021_component_official_publish_events.sql)

## 5. Component 删除联动

删除事务先取得 exclusive activity lock，软删除 Component，冻结统一结束 sequence/time，并在同一事务创建
`component.relationships.cleanup` 持久任务。提交后管理列表和 Feed 因 Component 不可见而立即隐藏；Worker 再以
5,000 条为一批关闭 active Watch，并保留 closed history。该任务同时物理删除 Star，但不删除 Version、Import、
Artifact 或 Storage 历史。

相关代码：[component/service.go](../../backend-go/internal/component/service.go)、
[worker](../../backend-go/internal/worker)、[tasks.sql](../../backend-go/db/queries/tasks.sql)。

## 6. 数据、不变量与索引

| 对象 | 作用 | 关键不变量 |
|---|---|---|
| `component_watch_periods` | 保存首次 Watch、Unwatch 和 Rewatch 历史 | 同 actor+Component 最多一个 active period；closed 行不重开 |
| `component_activity_sequence` | 为 period、发布事件和删除边界分配共同顺序 | 允许回滚空洞；只比较先后，不承诺连续 |
| `component_domain_events` | 保存不可变发布事实 | 每个 Version 的发布事件唯一；UPDATE/DELETE 被数据库拒绝 |
| active actor index | 管理列表和 Feed 的入口 | closed history 不进入读取计划 |
| active component index | 删除 Worker 的批处理入口 | 支持按 actor keyset 继续 |
| Component/time/event index | Feed 的事件探测 | 与窗口、排序和 cursor 谓词完全一致 |

迁移链为 v15 Watch period、v16 domain event、v17 生命周期、v20 Feed 索引、v21 official 事件授权、v24 共享目录/翻译投影。

## 7. 权限、国际化与错误

- 所有 API 位于认证后的 `/api/v1`，actor 只来自 JWT；请求不能指定 owner。
- Watch 不扩大 Component 可见性；目标不可见时统一走 not-found/不可用契约。
- user Component 名称与 Release Note 保留原文；official 名称只选择 reviewed translation。
- UI 文案使用 typed semantic keys；level、ID、cursor、eventType 和时间是机器值。
- API 错误只返回稳定 `code + params`，前端按当前 locale 渲染；locale 切换会重新读取页面数据。
- 指标只有 `component_watch_mutation_total`、`component_watch_feed_requests_total`、
  `component_watch_feed_duration_seconds` 与发布事件计数，不带 actor、ID、查询或用户内容标签。

## 8. 测试定位

2026-09-14 的 Component 03/04/08 清理未改变 Watch HTTP/cursor/成员资格合约；Watch 管理列表和 Feed 已改读 v24
candidate/catalog/reviewed translation 共享投影，候选阶段不读取 Version 展示尺寸，迁移往返与跨模块集成通过。Python legacy 回归不再属于完成门禁。真实 Supabase
仍为 v23；本轮没有部署 v24，也不代表 Watch 浏览器流程或生产查询计划已经验收。

- Go Service/cursor 单测：[service_test.go](../../backend-go/internal/componentwatch/service_test.go)
- Component、发布、并发、分页和删除集成：[service_integration_test.go](../../backend-go/internal/component/service_integration_test.go)
- HTTP 契约：[component_integration_test.go](../../backend-go/internal/httpapi/component_integration_test.go)
- Schema/触发器：[schema_integration_test.go](../../backend-go/internal/database/schema_integration_test.go)
- 百万关系计划：[watch_list_performance_integration_test.go](../../backend-go/internal/component/watch_list_performance_integration_test.go)
- 前端状态与窗口：[ComponentWatchListPage.test.ts](../../frontend/src/componentRepo/__tests__/ComponentWatchListPage.test.ts)（Feed helper 从 `ComponentWatchFeedPanel` 导入）
- API adapter：[componentRepoApi.test.ts](../../frontend/src/componentRepo/__tests__/componentRepoApi.test.ts)
- 双语言页面：[localizedPages.test.tsx](../../frontend/src/i18n/__tests__/localizedPages.test.tsx)

## 9. 已发现的偏移与清理准备

| 编号 | 证据与问题 | 影响 | 清理前置条件 |
|---|---|---|---|
| WATCH-CLEAN-01 | shared activity lock SQL 分别放在 `component_watches.sql` 和 `component_domain_events.sql`，但 Star、Publish、Delete 都在调用 | 文件归属暗示错误，未来修改锁协议容易漏掉调用方 | 新建中性 `component_activity.sql`，只移动手写查询并重新生成 sqlc；跑并发、删除和迁移测试 |
| WATCH-CLEAN-02 | `componentwatch.displayLocale` 与 `component` 中的 locale 规范化职责重复 | 支持语言或规范变化时可能漂移 | 先冻结“严格校验”与“展示 fallback”两个契约，再提取无业务依赖的共享包 |
| WATCH-CLEAN-03（已关闭） | 旧 `mergeFeedItems` 用 `Date.parse` 重排 PostgreSQL 微秒时间 | 迁移 Feed 组件时改为保留服务端 cursor 页顺序，仅按 event ID 去重；helper 测试锁定该行为 | 2026-09-12 已关闭；后续不得在前端以毫秒时间重新排序 |
| WATCH-CLEAN-04 | `component_activity_sequence` 的 event-time recipient 用途已废止，但 period/event 仍保存 sequence | 字段真实用途比旧设计窄，维护者容易误以为 Feed 依赖它 | 先确认是否继续保留审计和统一删除边界；没有数据迁移、回滚与历史兼容方案前不得删除 |
| WATCH-CLEAN-05 | Watch 投影同时存在于 Component 列表/详情 SQL 与独立 Watch 服务 | 可见性、locale 或 active 条件变更时存在多处同步成本 | 建立投影契约测试清单；评估共享 SQL 片段/视图时必须重新执行 EXPLAIN，不能为去重牺牲查询形状 |

优先顺序建议：下一步整理 WATCH-CLEAN-01 的文件边界；02、04、05 需要先做契约决策。v21 部署属于发布验收，
不属于代码清理。
