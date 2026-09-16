# Component Repo Star：收藏能力落地与迭代路线跟踪文档

> **主要用途**：定义 Component Repo 的 Star（收藏）产品语义、UI、API、数据与授权方案，并作为从现有 Subscription 半成品迁移到正式收藏能力的实施路线和验收台账。  
> 状态：Implementation in progress / STAR-1、STAR-2 核心闭环、删除生命周期与首轮查询性能修正已验证  
> 日期：2026-09-04  
> 当前系统阶段：G8 进行中；Component Repo 已建立 Go-only API/Worker 主链  
> 配套文档：[`Watch 设计与路线`](./component_repo_watch_design_and_roadmap.md)、[`Fork 设计与路线`](./component_repo_fork_design_and_roadmap.md)、[`docs/api.md`](../../api.md)

## 1. 文档目标

本文解决以下问题：

1. Star 在 BrickBuilder 中到底表示什么；
2. Star 与 Watch、Fork、Component Group 的边界；
3. 如何处理当前已有的 `component_subscriptions` 表和 API；
4. Component 列表、详情、个人仓库应如何呈现收藏关系；
5. 如何保证幂等、授权、计数一致性和软删除后的隐私边界；
6. 如何分阶段上线，并记录每一阶段的实际完成证据。

本文是设计与路线跟踪文件，不代表文中数据库迁移、API、UI 或资源已经实现。只有完成对应验收门槛并补充证据后，路线项才可标记完成。

## 2. 产品定义

### 2.1 一句话定义

> Star 是用户对一个公开 Component 建立的轻量个人收藏关系，用于稍后访问、个人整理和公开热度表达；它不发送通知、不复制内容，也不授予额外权限。

### 2.2 用户价值

- 在公共 Component 目录中快速保存有价值的模型；
- 在“我的收藏”中集中浏览，不必反复搜索；
- 将收藏的 Component 加入自己的自定义 Group；
- 通过收藏数量判断一个 Component 的社区关注度；
- 为未来热门、趋势等可解释的聚合统计提供权威关系数据。

### 2.3 明确不表示什么

Star 不表示：

- 订阅新版本通知；
- 拥有或共同编辑 Component；
- 获得 Draft、Import、Candidate、Task 或 owner-scoped Artifact 的读取权限；
- 创建派生组件；
- 接受许可证或自动获得再创作权；
- 将 Component 永久保存为用户可控制的副本。

这些能力分别属于 Watch、协作权限和 Fork。

## 3. 术语与跨功能边界

| 关系 | 中文产品名称 | 是否产生新 Component | 是否发通知 | 是否授予修改权 |
|---|---|---:|---:|---:|
| Star | 收藏 | 否 | 否 | 否 |
| Watch | 订阅更新 | 否 | 是 | 否 |
| Fork | 创建派生 | 是 | 可选，且需另行 Watch | 仅对新 Component |
| Group Membership | 加入分组 | 否 | 否 | 否 |

跨功能不变量：

- Star 不自动创建 Watch；
- Watch 不自动创建 Star；
- Fork 成功后不自动 Star 或 Watch 上游，UI 可以提供显式勾选；
- 取消 Star 不取消 Watch，也不影响 Fork；
- 删除 Fork 不影响其来源 Component 的 Star；
- Group 只是个人整理关系，不改变 Component 的公开性和授权。

## 4. 实施前系统基线

### 4.1 实施前已存在能力

Star 实施前的 `component_repo` 已包含：

- `component_subscriptions(owner_id, component_id, subscribed_at)`；
- `PUT /api/v1/components/:componentId/subscription`；
- `DELETE /api/v1/components/:componentId/subscription`；
- Component DTO 的 `subscribed` 布尔投影；
- `(owner_id, component_id)` 主键和幂等写入；
- 禁止订阅自己的 Component；
- Component 可见性与 owner 边界；
- Component Group 可以容纳 actor 可见的 Component。

### 4.2 实施前缺口

- 前端没有完整收藏/取消收藏入口；
- 没有“我的收藏”独立视图；
- 没有 `starCount`；
- 数据和 API 使用 Subscription 命名，但没有通知能力；
- 根 Group 文案表示“上传或订阅”，当前查询语义更接近 actor 可见全集；
- 没有 Star 与 Watch 的产品边界；
- 没有针对归档、不可见和硬删除的计数语义；
- 没有社交关系的滥用限流与观测指标。

### 4.3 基线结论

现有 Subscription 是一个可迁移的关系数据基础，但不应继续作为最终机器契约。由于当前开发迁移策略允许 Go `/api/v1` 直接收敛目标契约，建议建立正式 Star 资源并迁移现有行，而不是长期保留“数据库叫订阅、UI 叫收藏”的双重语义。

## 5. 功能范围

### 5.1 MVP 范围

- 收藏公开可见的非本人 Component；
- 取消收藏；
- Component 卡片和详情页显示 actor 是否已收藏；
- Component 详情显示收藏数量；
- “我的收藏”列表支持分页、搜索和现有展示 locale；
- 收藏的 Component 可以加入 actor 的自定义 Group；
- API 幂等、服务端授权和并发一致性；
- 从现有 Subscription 数据迁移；
- 双语言 UI、稳定错误 `code + params`；
- 基础指标、审计和限流。

### 5.2 MVP 不包含

- 新版本通知；
- 邮件、推送或站内信；
- 谁收藏了该 Component 的公开用户列表；
- 收藏夹公开分享；
- 批量导入第三方平台 Star；
- 付费排名或通过 Star 解锁权限。

### 5.3 后续能力

- 热门、趋势和时间窗口统计；
- 个人收藏导出；
- 作者侧匿名聚合分析；
- 公开收藏列表和隐私开关；
- 防刷分和信誉加权统计。

## 6. 业务规则

### STAR-R01 可收藏对象

actor 只可收藏满足以下条件的 Component：

- Component 未软删除；
- Component 对 actor 可见；
- Component 为 `active`；
- 至少存在一个可公开读取的非 Draft Version；
- Component 不是 actor 自己拥有的 Component。

Official Component 可以收藏。用户自己的 Component 不需要收藏，因为它天然存在于“我的组件”。

### STAR-R02 幂等

- 首次 Star 创建关系并固定 `starred_at`；
- 重复 Star 返回已有关系，不修改原始时间；
- Unstar 不存在的关系仍返回成功；
- 并发 Star 最终只能保留一条关系；
- HTTP 重试不得导致计数增加两次。

### STAR-R03 权限

Star 只表示 actor 对 Component 的关系。所有资源读取继续执行原 Component、Version、Artifact 可见性规则，禁止通过 Star 绕过 owner 边界。

### STAR-R04 Component 状态变化

- Component 从 `active` 归档或软删除后，提交时立即从收藏列表隐藏；
- 删除事务必须原子创建持久关系清理任务，由 Go Worker 分批物理删除该 Component 的全部 Star；
- Star 是当前收藏状态，不是审计账本；归档后不保留关系，未来若重新激活也不自动恢复原 Star；
- 真正物理删除时通过外键级联删除 Star；
- `starCount` 只统计未删除、可公开存在的 Component 上的有效关系。

### STAR-R05 隐私

MVP 只公开聚合 `starCount`，不公开收藏者列表。作者不能获得收藏者身份。管理员审计属于单独权限域。

### STAR-R06 Group

- actor 可把已 Star 的可见 Component 加入自己的 custom Group；
- Unstar 不自动移除 custom Group membership；
- 若 Component 不再可见，Group 查询必须隐藏它；
- 根 Group 不应继续承担公共发现目录职责。

## 7. 信息架构与 UI 设计

### 7.1 导航建议

Component Repo 顶层建议拆成：

```text
发现
我的组件
我的收藏
我的订阅
自定义分组
```

“我的订阅”只有 Watch 上线后显示。Fork 属于“我的组件”，并可以额外使用“派生”筛选。

### 7.2 公共列表卡片

每张 Component 卡片展示：

- Star 图标按钮；
- actor 已 Star 时使用选中态；
- 收藏数；
- Fork 数由 Fork 功能提供；
- 按钮有明确 `aria-label`、键盘焦点和 loading 状态。

Star 成功采用乐观 UI，但失败时必须回滚并显示结构化错误。为避免重复点击，单卡片 mutation 进行中时禁用按钮。

### 7.3 Component 详情页

标题区建议：

```text
[组件名称]                         ☆ 收藏 128   创建派生 9
[作者/Official] [版本] [分类]
```

actor Star 后：

```text
★ 已收藏 129
```

自己的 Component 不显示 Star 按钮，可以显示“这是你的组件”。

### 7.4 我的收藏

支持：

- 按收藏时间倒序；
- 名称/Component ID 搜索；
- category 筛选；
- logical size 筛选复用现有规范；
- 加入/移出 custom Group；
- 批量取消收藏属于后续增强，MVP 可不做。

空状态应区分：

- 尚未收藏任何 Component；
- 搜索没有结果；
- Component 删除已提交、关系清理尚在异步收敛的短暂状态。

第三种不是保留收藏的产品状态，不向用户泄露 Component 内容；清理任务完成后关系总数必须收敛。

### 7.5 公共发现与个人仓库

必须避免根 Group 自动包含全部公共 Component。建议：

- “发现”调用公共可见目录；
- “我的组件”只查询 `ownedByActor=true`；
- “我的收藏”只查询 Star relation；
- custom Group 继续查询显式 membership；
- root Group 若保留，只表示 actor 管理的个人集合，不再作为公开目录别名。

## 8. API 方案

### 8.1 推荐接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `PUT` | `/api/v1/components/:componentId/star` | 幂等收藏 |
| `DELETE` | `/api/v1/components/:componentId/star` | 幂等取消收藏 |
| `GET` | `/api/v1/component-stars` | actor 的收藏列表 |

`PUT` 成功建议返回：

```json
{
  "componentId": "uuid",
  "starredAt": "2026-08-29T10:00:00Z"
}
```

`DELETE` 成功返回 `204`。

`GET /api/v1/component-stars` 支持：

```text
page
pageSize
locale
query
category
sort=starred_at_desc
```

### 8.2 Component DTO

Component 列表与详情增加或规范化：

```json
{
  "starredByActor": true,
  "starCount": 128
}
```

字段是机器数据，不翻译。前端使用 typed semantic key 生成展示文案。

### 8.3 兼容与迁移

推荐直接收敛目标契约：

1. Goose 创建 `component_stars`；
2. 将 `component_subscriptions` 现有数据迁入；
3. Go Service 和查询切换到 Star；
4. 前端切换到 Star API；
5. 删除旧 Subscription API 和旧表；
6. 同一次切片更新 `docs/api.md` 与 `docs/go_migration_progress.md`。

不建议长期双写，也不建议建立 Subscription → Star 兼容代理。若产品决定保留 Watch，则 Watch 使用新的独立表，不复用旧关系含义。

### 8.4 错误 code 草案

```text
component_repo.component_not_found
component_repo.star_own_component_forbidden
component_repo.star_component_unavailable
request.validation_failed
auth.authentication_required
common.rate_limited
common.internal_error
```

响应只包含 `code + params + traceId`，不得暴露 SQL、路径或最终翻译文本。

## 9. 数据模型

### 9.1 `component_stars`

```text
actor_id       uuid        NOT NULL
component_id   uuid        NOT NULL
starred_at     timestamptz NOT NULL DEFAULT now()
source         text        NOT NULL DEFAULT 'user_action'
PRIMARY KEY (actor_id, component_id)
FOREIGN KEY component_id -> components(id) ON DELETE CASCADE
```

建议索引：

```text
(actor_id, starred_at DESC, component_id)
(component_id, actor_id)
```

`source` 是稳定机器值，为未来导入或运营迁移保留；MVP 只允许 `user_action` 和 `subscription_migration`。

### 9.2 收藏计数

MVP 推荐以 `component_stars` 为权威，通过索引聚合得到 `starCount`：

- 详情查询直接 COUNT；
- 分页列表使用一次聚合 JOIN，避免 N+1；
- 不在 `components.metadata` 保存计数；
- 不用前端乐观值作为权威；
- 只有观察到明确性能问题后，再增加事务一致的统计投影表。

如果以后增加 `component_social_stats`，其数据必须可从关系表重建，并有一致性审计，不能成为无法校验的唯一事实源。

## 10. Go 模块边界

建议仍在 Component Repo 模块化单体中实现：

```text
internal/componentstar/
  handler.go
  service.go
  types.go
  errors.go

db/queries/component_stars.sql
db/migrations/<next>_component_stars.sql
```

职责：

- Handler：解析 ID、认证、有限请求校验和响应；
- Service：可见性、own-component 禁止、幂等事务；
- sqlc Query：owner/actor 显式条件、列表分页和计数；
- 不创建异步 Task；
- 不访问对象存储；
- 不引入 Python consumer。

是否最终独立为 `componentstar` package，可在实现前根据现有 `component` service 大小决定；不能因此引入微服务或业务网关。

## 11. i18n 与内容治理

### 11.1 分类

| 内容 | 分类 | 处理方式 |
|---|---|---|
| `starredByActor`、`starCount`、API 路径、错误 code | 机器数据 | 不翻译 |
| 收藏/取消收藏/我的收藏 | 系统 UI 内容 | typed semantic key |
| Component 名称、说明 | 用户或官方内容 | 保持既有 `contentLocale`/reviewed translation |
| Star 时间 | 时间数据 | 前端按 locale/timezone 格式化 |

### 11.2 资源要求

实现 UI 时必须：

- 使用独立 `componentRepo` 语义 key；
- 同时补齐 zh-CN/en-US；
- 更新 catalog version、content hash 和 `I18N_RELEASE_NOTES.md`；
- 不添加 `defaultValue` 或源码文本 fallback；
- API 不返回最终翻译句子。

## 12. 安全、滥用和可观测性

### 12.1 安全

- 只使用认证 actor 创建关系；
- 所有查询显式带 actor；
- 跨 owner 私有 Component 返回 `404`；
- Star 不可换取源 Artifact signed URL；
- CSRF/认证策略沿用现有 API；
- 不向 Component owner公开 actor 列表。

### 12.2 滥用

- 对高频 Star/Unstar 做 actor 级速率限制；
- 聚合趋势时排除异常抖动；
- 不把 Star 数直接作为安全或授权判断；
- 未来防刷策略不能修改历史用户关系的权威性。

### 12.3 指标

```text
component_star_mutation_total{action,result}
component_star_request_duration_seconds{action}
component_star_list_request_duration_seconds
component_star_rate_limited_total
component_star_count_query_duration_seconds
```

日志只记录 actor/component 的安全标识、结果 code 和 traceId，不记录 token 或用户输入全文。

## 13. 验收标准

### 13.1 功能验收

- 非 owner 可以 Star 一个 active Component；
- 重复 Star 不产生第二行且时间不变化；
- Unstar 不存在关系返回成功；
- actor 不能 Star 自己的 Component；
- actor 不能 Star 不可见、Draft-only 或已删除 Component；
- `starredByActor` 与实际关系一致；
- `starCount` 在并发写入后正确；
- 我的收藏分页稳定且无重复/漏项；
- Unstar 不自动删除 custom Group membership；
- Star 不授予 Version Draft 或 Artifact 权限。

### 13.2 UI 验收

- 卡片与详情按钮状态一致；
- 乐观更新失败会回滚；
- 键盘和屏幕阅读器可操作；
- loading 状态防止重复 mutation；
- zh-CN/en-US 不缺 key；
- 自己的 Component 不显示误导性 Star 操作。

### 13.3 性能验收

性能阈值不在设计阶段拍脑袋固定。STAR-0 先用真实规模建立基线，再冻结：

- 列表 P50/P95；
- 详情计数 P50/P95；
- 并发 Star/Unstar；
- 10 万、100 万关系量级下的索引与查询计划。

## 14. 测试策略

### 14.1 数据库与 Service

- Goose Up/Down 权威边界；
- sqlc generate/vet；
- 现有 Subscription 数据迁移完整性；
- 并发幂等；
- owner/非 owner/official/归档授权矩阵；
- 分页稳定性；
- 计数正确性；
- soft delete 后不泄露。

### 14.2 API

- UUID、认证、状态码和错误 code；
- PUT/DELETE 重试；
- 详情和列表投影；
- 不存在资源使用 404；
- rate limit；
- traceId。

### 14.3 前端

- adapter 契约；
- 乐观更新与失败回滚；
- 列表筛选；
- 卡片和详情一致；
- custom Group 交互不受影响；
- i18n check、单元测试和构建。

## 15. 关键决策记录

| ID | 决策 | 推荐 | 状态 |
|---|---|---|---|
| STAR-D01 | Star 是否发送通知 | 不发送，通知属于 Watch | 已采用 |
| STAR-D02 | 是否允许 Star 自己的 Component | 不允许 | 已采用 |
| STAR-D03 | 是否公开收藏者身份 | MVP 不公开，只显示计数 | 已采用 |
| STAR-D04 | 旧 Subscription 如何处理 | 一次迁移为 Star，删除旧契约 | 已采用 |
| STAR-D05 | 根 Group 是否等同公开发现 | 否，二者拆开 | 已采用 |
| STAR-D06 | 归档/删除 Component 的关系 | 提交后立即隐藏，持久 Worker 分批物理删除；不恢复原 Star | 已采用；Goose v17 |

## 16. 实施路线与跟踪

状态定义：

- `[ ]` 未开始；
- `[~]` 进行中；
- `[x]` 已完成且有证据；
- `[!]` 阻塞，必须记录阻塞条件。

### STAR-0：产品语义与基线

目标：冻结 Star/Watch/Group 边界和真实性能基线。

- [x] 已确认当前存在 `component_subscriptions` 数据表与 PUT/DELETE API；证据：Goose baseline、`docs/api.md`。
- [x] 已确认当前 DTO 返回 `subscribed`；证据：Component Go/TS DTO。
- [x] 已确认前端尚未形成完整收藏交互；证据：Component Repo 前端调用盘点。
- [x] 确认 STAR-D01～D06；证据：Goose v14、v17 关系生命周期、Go Service 授权和当前 UI 信息架构均按决策实现。
- [ ] 盘点生产/开发环境现有 Subscription 行数与数据质量；
- [x] 对根 Group、公开发现与“我的收藏”的查询语义形成修订决策；证据：根 Group 只查 owned，Star 视图只查关系，社区目录独立调用 `/components`。
- [ ] 建立列表和详情查询性能基线；
- [x] 冻结 API 命名与错误 code；证据：`docs/api.md` 与双语言 Star error resources。

阶段门槛：决策全部确认，迁移数据量可测，API/UI 术语无歧义。

### STAR-1：PostgreSQL 与 Go API

目标：建立正式 Star 权威数据与 API。

- [x] 新增 Goose migration；证据：`00014_component_stars.sql` 可从 0 升级到 v14 并通过 down/up 演练。
- [~] 迁移旧 Subscription 数据并验证行数/hash；迁移 SQL 和隔离库升级已验证，真实目标库行数核对仍待发布前执行。
- [x] 新增手写 sqlc queries；证据：sqlc generate/vet 通过。
- [x] 新增 Star Service 和 Handler；证据：Go 全量测试通过。
- [x] Component DTO 切换为 `starredByActor/starCount`。
- [x] 新增我的收藏分页。
- [x] 删除旧 Go Subscription API/查询/表；旧错误资源只因遗留 Python 静态治理测试暂留，不构成 Go 路由或双写。
- [x] 补齐 integration/API tests；覆盖跨用户、自有组件拒绝、Draft-only/删除对象拒绝、并发幂等、原时间保留、计数、列表和个人 root。
- [x] 更新 `docs/api.md` 与 `docs/go_migration_progress.md`。

阶段门槛：Go API、PostgreSQL integration、sqlc generate/vet 全部通过；无双写、无 Python 路径。

### STAR-2：前端与个人仓库

目标：完成用户可见闭环。

- [x] 公共卡片 Star 按钮；社区目录已启用，并包含 loading、选中态与失败回滚。
- [x] Component 详情 Star 按钮与计数。
- [x] “我的收藏”视图。
- [x] 收藏时间、category、logical size 与三类空状态；logical size 复用轴无关开区间规则，删除清理过渡态只返回数量诊断。
- [x] 根 Group/发现目录信息架构修订。
- [x] custom Group 仍可管理收藏的 Component；继续复用 actor-visible membership 授权。
- [x] typed semantic keys 和双语言资源。
- [~] adapter/interaction/accessibility tests；adapter 契约和 Go 集成测试已补齐，页面级交互测试仍待增强。
- [x] i18n check、前端 test/build。

阶段门槛：两种 locale、键盘操作、失败回滚和多页面状态一致性全部通过。

### STAR-3：计数、性能与发布

目标：在真实量级下稳定上线。

- [x] 关系量级压力测试；已按 1,000 actor × 每人 1,000 Star 构造 1,000,000 总关系。
- [x] 列表与尺寸查询计划审查；actor 候选物化、Version 候选索引探测、页后展示投影和页内聚合均已通过当前容量包络的 `EXPLAIN ANALYZE` 门禁。
- [ ] actor 级限流；
- [ ] metrics/logging/dashboard；
- [ ] 数据迁移回滚演练；
- [ ] 灰度观察 Star/Unstar 错误率；
- [ ] 完成发布验收和文档收口。

阶段门槛：达到 STAR-0 冻结的 SLO，无计数漂移和授权回归。

### STAR-4：可选增强

- [ ] 趋势统计；
- [ ] 作者匿名分析；
- [ ] 公开收藏列表与隐私设置；
- [ ] 可重建统计投影。

## 17. 进度记录模板

每次实施后在本节追加，不覆盖历史记录：

```text
### YYYY-MM-DD / STAR-N / 切片名称

完成事实：
- ...

变更边界：
- API：...
- DB：...
- UI/i18n：...

验证证据：
- command / test / result

未完成与风险：
- ...
```

## 18. 当前结论

Star 第一版应是一项简单、同步、强授权边界的收藏关系。最重要的工作不是增加一个星形按钮，而是把当前 Subscription 的模糊命名正式收敛、把公共发现和个人仓库拆开，并确保 Star 永远不会被解释为通知、Fork 权限或资源访问授权。

## 19. 2026-08-30 / STAR-1～STAR-3 / 资格检查与列表查询性能修正

完成事实：

- `Star()` 改用最小目标投影，只检查未删除/可见、owner、状态、非 Draft Version 和已有 Star；重复 PUT 直接返回原 `starredAt`，不再加载 Component 完整详情或计算 `starCount`。
- root Group 的列表、搜索、状态统计和直接计数收敛为 actor 自有 Component；Star 使用独立视图，custom Group 继续由 membership 驱动，不再从全部 Component 以 `owner OR Star EXISTS` 过滤。
- Component 目录、收藏列表、Group 成员和 Group 搜索均先固定当前页，再按页内 Component ID 一次聚合收藏数；详情仍按设计直接 COUNT。
- PostgreSQL integration 增加 Draft-only、已删除、自有对象、并发首次收藏、重复收藏时间不变和计数为一的契约。

变更边界：

- API：路径、请求/响应和错误 code 不变；仅收敛内部执行逻辑。
- DB：无新 migration、表或索引；继续使用 v14 两个既有 Star 索引。
- UI/i18n：无用户可见或 locale-sensitive 变化，资源与 catalog 不变。

验证证据：

- `go tool sqlc generate`、`go tool sqlc vet`：PASS。
- `make check`：PASS（Go 全量测试、go vet、sqlc vet）。
- `make test-postgres`：PASS；隔离 PostgreSQL 完成 Goose `0 -> 14 -> down/up`，Component/Group/Star integration 全部通过。
- `frontend npm run i18n:check / npm test / npm run build`：PASS（2 locales、15 files / 69 tests、production build）。

未完成与风险：

- STAR-3 的 10 万/100 万关系规模压力测试、真实查询计划/SLO、限流和指标仍未完成，不能仅凭本次查询形状修正宣告发布性能验收完成。

## 20. 2026-08-30 / STAR-2～STAR-3 / UI 契约补齐与 10 万关系查询计划复核

完成事实：

- root Group 改为 owned-only，“我的收藏”不再混入“我的组件”；取消收藏不删除 custom membership，分组行与候选合并保证外部组件仍可被移出。
- 公开详情不再请求 owner-only relation/connector；已发布 Version Preview、BOM 和可见 ValidationReport 保持公开读取。
- 收藏页新增 category、logical size、固定 sort 校验、`starredAt` 列、末页回退，以及“从未收藏 / 筛选无结果 / 删除关系异步收敛中”三类空状态；第三种不是长期保留收藏。
- 社区目录名称查询补齐 Component ID；收藏计数同时返回过滤可见总数和关系总数，不增加第二次数据库往返。
- translation LATERAL 的 `content_kind` 条件移入子查询，避免用户 Component 逐行空探测；收藏计数仅在尺寸条件存在时读取当前版本尺寸。

10 万关系隔离基线（本机临时 PostgreSQL、每个 Component 一个 published Version，`EXPLAIN ANALYZE`，仅作为查询形状证据）：

- 收藏首页 20 条：约 `0.37 ms`，命中 `component_stars_actor_time_idx`，页内 Star 聚合只访问 20 个 Component；
- 无筛选精确计数 + `relationshipTotal`：约 `139 ms`，较修正前约 `279 ms` 降低约一半；
- category 命中 5 万条计数：约 `57 ms`；
- logical size 命中 10 万条计数：约 `364 ms`，仍需逐关系读取当前 Version 尺寸；
- OFFSET 99,980 的 20 条深分页：约 `215 ms`，说明页码深分页仍是明确扩展风险。

验证证据：

- `go tool sqlc generate/vet`、`make check`、`make test-postgres`：PASS；
- `frontend npm run i18n:check / npm test / npm run build`：PASS；
- 10 万关系临时库迁移到 Goose v14、插入/ANALYZE、五组真实计划：PASS。

未完成与风险：

- 100 万关系、多 actor 分布、冷热缓存、真实官方翻译占比和生产参数的基线仍未完成；上述毫秒值不能直接视为生产 SLO。
- exact COUNT、leading-wildcard 名称/ID 搜索、computed logical size 和深 OFFSET 都随 actor 关系数增长；STAR-3 需评估 cursor/keyset、搜索索引/投影和尺寸规范化索引，不能只追加通用 B-tree。

## 21. Review comments 跟踪记录：Star hardening 后续整改与关闭条件

本节是 2026-08-30 第二次实现复核的权威问题清单。第 20 节的测试数字是问题证据，不代表下列问题已关闭；
任何条目只有在“关闭条件”全部满足且验证结果回写本路线文档与 `docs/go_migration_progress.md` 后，才可改为完成。

| ID | 优先级 | Review comment 与证据 | 方案方向与关闭条件 | 所属阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `STAR-PERF-01` | P1 | 收藏列表仍使用页码 `OFFSET`；历史 10 万关系实验中 `OFFSET 99,980 LIMIT 20` 约 `215 ms`，跳过成本随关系数线性增长。 | 2026-09-04 产品决定保留现有页码交互，不实施 cursor 改造。按单 actor Star 不超过 1,000 的容量包络验证首页与最深页；若产品批准改变交互、容量包络提高或观测数据接近 1,000，重新开启 keyset 方案。 | STAR-3 | Deferred |
| `STAR-PERF-02` | P1 | logical-size 过滤仍需逐关系读取当前 published Version 的尺寸并现场规范化；历史 10 万全命中计数约 `364 ms`。 | Goose v18 已建立当前公开 Version 的事务一致规范化尺寸投影；发布与晚完成 Preview 均维护该投影，Star 过滤不再读取 Version 尺寸。1,000 actor × 1,000 Star 已覆盖无过滤、选择性/高/零命中和首/最深页计划。 | STAR-3 | Completed |
| `STAR-CONSISTENCY-01` | P2 | Service 曾先执行 Count、后执行 List，两个独立的默认 `READ COMMITTED` 语句可能在并发 Star/Unstar 时读取不同快照，造成一次响应中的 `total/items` 暂时不一致。 | 2026-09-16 已冻结为响应内一致：唯一 List SQL 用窗口计数返回 exact `total`，Service 在 `REPEATABLE READ READ ONLY` 快照内执行；越界空页复用同一 SQL 探测第一页总数。`relationshipTotal` 已退出公共 API。越界页、删除隐藏与百万关系实际 SQL 计划均通过。 | STAR-3 | Completed |
| `STAR-UI-01` | P2 | custom Group 批量成员弹窗曾只各取 owned、Star、当前成员的前 100 条，超过上限的组件会静默消失。 | owned、Star 与现有成员已分别分页搜索、合并去重并显示续页，完整 membership 独立逐页加载；`ComponentGroupControls.test.tsx` 覆盖第 101 条候选和成员。 | STAR-2 hardening | Completed |
| `STAR-A11Y-01` | P2 | Star 图标按钮曾缺少显式 `aria-label`；可访问名称可能只剩收藏数，`title` 不能替代稳定的按钮名称。 | 列表、详情和公共 Feed 统一使用 `ComponentStarButton`，复用 Star/Unstar typed semantic key，保留原生 button 的 Enter/Space 语义；双 locale、双状态语义测试通过。 | STAR-2 hardening | Completed |

设计复盘结论：

- 本轮问题的共同根因是把“SQL 语义正确、功能测试通过”误当成了“查询在目标量级可发布”；后续必须同时审查执行器实际 loops、buffers 和增长阶数。
- LATERAL/可选条件的门控必须在子查询内部生效，并由 `EXPLAIN ANALYZE` 证明未启用分支为零执行；不能仅凭 JOIN `ON` 或 SQL 文本顺序推断短路。
- computed filter、exact COUNT 和深 `OFFSET` 是三个独立成本中心，必须分别设计数据投影、总数语义和分页模型，不能用追加通用 B-tree 代替方案设计。
- 前端 first-N 限制属于完整性和扩展性契约，必须与服务端分页共同设计；不能等出现大量数据后再视为纯 UI 优化。
- 上述结论已同步固化到仓库根 `AGENTS.md` 的 Mandatory SQL performance preflight and review，作为后续智能体实施和 review 的强制规约。

## 22. 2026-09-04 / STAR-3 / P1 修复预检与容量决策

本切片只修复 `STAR-PERF-02`，不改变 Star API、页码分页或前端交互。`STAR-PERF-01` 按产品决定延期。

SQL 设计预检：

- 容量包络：用户总量不超过 1,000；单 actor Star 不超过 1,000；总 Star 关系按最多约 1,000,000 评估，
  但单次列表/计数始终从 actor 关系索引驱动，最坏候选为 1,000。
- 候选与分布：`component_stars(actor_id,starred_at,component_id)` 是权威候选源；验证空 actor、稀疏 actor
  与 1,000 条热点 actor。尺寸过滤覆盖零命中、选择性命中与全部命中。
- 查询契约：排序继续为 `starred_at DESC,component_id`；保留 page/pageSize 与 `OFFSET`，最深可规划页只跨越
  单 actor 的 1,000 条关系。响应继续需要 exact `total/relationshipTotal`；Count/List 的跨语句一致性仍由
  `STAR-CONSISTENCY-01` 单独跟踪，本切片不改变其语义。
- 投影方案：Component 保存当前公开 Version 的升序规范化尺寸；Version 发布以及当前 Version 的 Preview Box
  后置完成时，在原事务内刷新投影。Star 尺寸计数与筛选不再逐候选读取 Version 或执行
  `LEAST/GREATEST`。
- 索引决策：现阶段不增加尺寸索引。actor 候选由现有复合索引限制在 1,000 内；新尺寸索引无法同时服务
  actor 关系顺序和三组二维配对，未经计划证明只会增加发布写放大。若容量包络提高，必须重新评审持久化
  search projection 与谓词专用索引。
- 快照：本切片不改变两条 `READ COMMITTED` 语句，因此 rows/total 不承诺同一快照；该风险不借尺寸投影
  修复名义隐式扩大范围。

规模数字是规划包络，不自动成为 API 拒绝阈值；新增 1,000 条硬限制及相应错误交互需要另行产品决策。

实施与验证结果：

- Goose v18 新增 `components.current_logical_size_a/b/c`，约束为全空或全有、非负且升序；升级只回填当前
  active Component。原始有方向宽/深/高继续由 ComponentVersion 保存。
- `SetComponentCurrentVersion` 在发布事务切换 current Version 时计算投影；`MarkVersionPreviewReady` 在
  Preview 晚于发布完成时，只为仍是 current 的 Version 原子刷新投影。集成测试分别固定发布前已有 Box 和
  发布后才产生 Box 两条路径。
- Star Count/List 先物化 actor 的权威关系候选，再对候选 Component 和非 Draft Version 做有界探测；尺寸谓词
  直接使用投影，最终页展示仍可读取 current Version 的原始宽/深/高。没有新增尺寸索引，因为单 actor 候选
  已由现有关系索引限制为最多 1,000。
- 隔离 PostgreSQL 14.17 使用 1,000 actor × 每人 1,000 Star，总计 1,000,000 条关系；配置为
  `shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB`，数据已 ANALYZE。warm-cache 计划中，
  无筛选约 `1.154 ms`，三维选择性命中 10 条约 `0.407 ms`，高命中 990 条约 `1.493 ms`，零命中约
  `0.193 ms`，空 actor 约 `0.011 ms`，首页约 `1.423 ms`，最深支持页约 `1.484 ms`。所有场景均通过 actor
  索引读取至多 1,000 条关系；Version 只按候选索引探测，空 actor 下 Component/Version 分支均未执行；没有
  `component_stars` 或 `component_versions` 全表扫描、sort spill 或 temp file。这些时间仅证明本机查询形状，
  不是生产 SLO。
- `RUN_STAR_SIZE_PLAN_TEST=1 make test-postgres` 是显式规模门禁；普通集成测试不隐式承担百万行成本。

2026-09-05 再次以 `RUN_STAR_SIZE_PLAN_TEST=1 RUN_WATCH_LIST_PLAN_TEST=1 make test-postgres` 运行组合门禁；
Star 仍为 1,000 actor × 1,000 关系，单 actor 候选、筛选命中分布、首页和最深页查询形状均通过。该次本地
warm-cache 时间约为无筛选 1.130 ms、选择性 0.468 ms、高匹配 1.556 ms、零命中 0.203 ms、首页
1.428 ms、最深页 1.407 ms；这些数字仅用于证明计划形状，不是生产 SLO，也不替代包络变化后的复测。

结论：`STAR-PERF-02` 关闭。`STAR-PERF-01` 仍按产品决定延期，本次没有修改 API、页码模型、前端交互、
用户文案或 i18n 资源。真实 Supabase 尚未执行 v18。

## 23. 2026-09-16 / STAR-2～STAR-3 / 已知偏移清理预检

本切片处理 `STAR-CONSISTENCY-01`、`STAR-A11Y-01` 以及详细设计中的 `STAR-CLEAN-07`。冻结以下产品与
查询契约后再实施：

- 收藏页继续使用页码并需要筛选后的 exact `total`；`items` 与 `total` 必须来自同一个一致性读快照。
  `relationshipTotal` 只描述删除清理完成前的内部残留关系，不是用户可操作的收藏状态，也不再进入公共 API
  或 UI。删除后不可见的 Component 不会因恢复公开而自动恢复 Star。
- 容量包络仍为最多 1,000 用户、每 actor 最多 1,000 条 Star；总关系向 1,000,000 增长，但单次请求必须从
  `component_stars(actor_id,starred_at,component_id)` 的 actor 索引驱动。验证空 actor、稀疏 actor 与 1,000
  条热点 actor，筛选覆盖无筛选、选择性、高匹配和零匹配。
- category 是可选精确筛选；完整尺寸表达式使用事务维护的规范化尺寸投影；普通名称/ID 搜索仍是 actor 有界
  候选内的 leading-wildcard 匹配。official translation 只在当前 locale 投影或搜索需要时探测 reviewed
  translation，用户内容保持原文。
- 排序固定为 `starred_at DESC,component_id`，页码 `OFFSET` 在 1,000 条包络内保留。首、最深支持页都要复核；
  当单 actor 关系接近 700、容量包络提高或产品批准改变交互时，重新开启 keyset 设计。该规划数字不是 API
  拒绝阈值。
- SQL 只保留一份可见性、translation、category、搜索和尺寸谓词；分页行通过窗口精确计数获得 `total`。
  越界空页在同一个 `REPEATABLE READ READ ONLY` 事务中复用同一查询读取第一页元数据，因此不引入第二份
  Count 谓词，且不会跨快照拼接行与总数。普通非空页只执行一次查询。
- 不新增索引。actor 候选已被当前容量约束在 1,000 内；任何搜索或尺寸索引都必须有谓词与排序对应的真实
  计划证据，不能以通用 B-tree 替代。
- Star/Unstar 按钮继续使用原生 `button` 的 Enter/Space 键盘语义，并复用现有 typed `starComponent` /
  `unstarComponent` 双语 key 作为随状态变化的 `aria-label`；不新增 locale 分支。

关闭前必须完成：Go 单元与 PostgreSQL 集成测试、前端 i18n/test/build、1,000 actor × 1,000 Star 的
`EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` 规模门禁，并把实际计划、版本和 warm/cold-cache 限制回写本节。

实施与验证结果：

- `CountStarredComponents` 及重复谓词已删除。`ListStarredComponents` 在筛选结果上执行 `WindowAgg` 后分页；
  非空页一次 SQL 同时得到 items/total，越界空页在同一个 `REPEATABLE READ READ ONLY` 事务中复用该查询读取
  首页元数据。集成测试固定了 page=2、pageSize=1、total=1、items 为空的越界页契约。
- `relationshipTotal` 从 Go/TypeScript DTO、页面状态和 `/api/v1/component-stars` 响应删除。删除提交后不可见
  Component 只留下待 Worker 物理删除的内部关系，不再驱动 UI 空态；与该错误语义关联的双语资源已删除，目录
  升级为 `frontend-2026.09.16.1`。
- 页内 `starCount` 首次实际 SQL 计划发现会为 20 个卡片顺序扫描全部 1,000,000 Star，约 77 ms；已改为固定
  页面后逐项使用 `component_stars_component_idx` 聚合，计划不再出现 Star 全表扫描。该发现说明页级聚合必须以
  实际 loops/buffers 验证，不能仅从 SQL JOIN 文本判断驱动方向。
- 扩展 fixture 包含 100,000 Component、1,000 actor × 每人 1,000 Star（共 1,000,000）、单 actor 1,000
  候选、90% user / 10% official Component，以及 100 条 zh-CN reviewed translation。PostgreSQL 14.17，
  `shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB`，已 ANALYZE。warm-cache 实际权威 SQL
  计划中：无筛选约 10.087 ms、尺寸选择性 10 条约 32.851 ms、尺寸高匹配 990 条约 9.569 ms、零命中约
  0.447 ms、reviewed translation 选择性 1 条约 2.348 ms、高匹配 100 条约 10.585 ms、首页约
  10.650 ms、最深 OFFSET 980 页约 7.405 ms。所有场景从 actor 关系索引驱动，没有 Component、Version 或
  Star 全表扫描，没有外部排序或临时文件；页内计数按 Component 索引访问。
- 上述为本机 warm-cache 查询形状证据，未单独测量 cold-cache，也不是生产 SLO。OFFSET 仍按当前 1,000/actor
  包络条件延期；接近 700 条、提高容量或批准交互改变时重开 keyset 设计。
- `backend-go make check`、`make test-postgres`、`RUN_STAR_SIZE_PLAN_TEST=1 make test-postgres`、前端
  `npm run i18n:check`、`npm test`（24 files / 104 tests）和 `npm run build` 均通过。

结论：`STAR-CONSISTENCY-01`、`STAR-A11Y-01`、`STAR-CLEAN-03/06/07` 关闭；`STAR-PERF-01` /
`STAR-CLEAN-04` 保持有客观重开条件的 Deferred，不以当前容量决定新增 API 硬限制。
