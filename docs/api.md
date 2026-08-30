# Component Repo Go API

> 状态：Current implementation contract；目标漂移均显式标注为尚未实现
> 更新日期：2026-08-30
> 范围：`backend-go` 当前注册的认证与 Component Repo HTTP API；不包含旧 FastAPI 路由
> 长期原则：[go_backend_migration_principles.md](./go_backend_migration_principles.md)
> 任务协议：[go_task_protocol.md](./go_task_protocol.md)
> 当前进度：[go_migration_progress.md](./go_migration_progress.md)

本文描述每个接口负责的功能及服务端执行逻辑。路由事实来源是
`backend-go/internal/httpapi/router.go` 以及各领域 `handler.go`；数据库约束、sqlc query 和
Worker handler 仍是运行时行为的最终依据。接口发生行为变化时必须同步更新本文。

## 1. 全局约定

### 1.1 路由、认证与 actor

- 健康检查位于 `/health/*`，不要求认证。
- Component Repo 业务接口统一位于 `/api/v1`，全部要求
  `Authorization: Bearer <access-token>`。
- 前端调用认证 `/api/v1` 路由时统一通过 authenticated API client 注入当前 Supabase access token；
  领域页面不得直接使用无认证的通用 JSON client，以免请求在到达业务 Handler 前被认证中间件拒绝。
- JWT 支持 Supabase ES256/JWKS，以及显式配置的 legacy HS256；服务端校验签名、`exp`、
  `nbf`、`iss`、`aud`，并只接受 UUID `sub` 作为 actor ID。
- 需要 Supabase Storage RLS 的请求会继续使用已验证的用户 access token，但不会把 token
  写入响应、任务 payload 或日志。
- 跨 owner 的私有资源通常返回 `404`，避免暴露资源是否存在。

### 1.2 Trace、超时与错误

每个请求都带 `X-Trace-Id` 响应头。服务端统一应用正文大小限制、请求超时、结构化访问日志和
panic recovery。

公共错误只返回稳定 `code + params + traceId`：

```json
{
  "error": {
    "code": "component_repo.component_not_found",
    "params": {"componentId": "uuid"},
    "traceId": "req_..."
  }
}
```

常见状态：

| HTTP | 含义 |
|---|---|
| `401` | 未认证、Authorization header 无效或 session/JWT 无效 |
| `404` | 路由、资源不存在，或 actor 无权获知资源存在 |
| `405` | HTTP method 不允许 |
| `409` | 当前状态、版本、分组、connector capacity 或缓存状态冲突 |
| `422` | UUID、字段、locale/timezone、artifact 或业务输入校验失败 |
| `500` | 未知内部错误；只返回 `common.internal_error` |
| `502/503` | Storage 或依赖暂不可用 |

### 1.3 可见性与写入边界

- 用户自己的 Component、Draft、Import、Candidate、Task、Group 和 Artifact 由 owner 边界保护。
- 非 owner 只可读取 `active` Component 及其非 draft Version；Star 只表示个人收藏，不授予读取或修改权限。
- 官方 Component/Part 只选择目标 locale 下 `reviewed` 的翻译；缺失时返回源内容并标记
  `translationMissing` 或 `translationStatus=fallback/missing`。
- Component、Version、Group 等多步 mutation 使用 PostgreSQL transaction；需要并发保护的流程使用
  serializable transaction，并对 serialization/deadlock 做有限重试。
- GET 接口不得隐式创建 Group、Task、Artifact 或 Preview。

### 1.4 分页与 locale

- 通用分页参数为 `page`、`pageSize`，默认 `1/20`，`pageSize` 最大为 `100`。
- 展示 locale 规范化为 `zh-CN` 或 `en-US`；未提供或非法的只读展示 locale 当前回落到
  `zh-CN`。用户内容写入接口要求有效的 `contentLocale`。
- 异步任务创建时冻结 locale 和 IANA timezone；Worker 不读取浏览器后续语言状态。

### 1.5 异步接口通用流程

异步接口返回：

```json
{"taskId": "uuid", "status": "queued"}
```

客户端随后轮询 `GET /api/v1/tasks/:taskId`。任务状态为
`queued -> running -> succeeded|failed|cancelled`。同一 logical key 和 input hash 的
queued/running 或可复用 succeeded Execution 会被复用；失败、取消或确认缓存丢失后才创建新
Execution。

当前任务执行者：

| task type | 当前执行者 | 目标执行者 |
|---|---|---|
| `component.artifact.verify` | Go Worker | Go Worker |
| `component.import.parse` | Go Worker | Go Worker |
| `component.relations.detect` | Go Worker | Go Worker |
| `component.validate` | Go Worker | Go Worker |
| `component.preview.materialize` | Go Worker | Go Worker |
| `component.part_preview.materialize` | Go Worker | Go Worker |
| `component.part_preview.prebuild` | Go Worker | Go Worker |

Component Repo 的上述任务全部由 Go Worker 执行；不得新增 Component Repo Python task type。

### 1.6 页面刷新会话确认

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/auth/session` | Bearer token；`200 {authenticated:true,user:{id,email?}}` | 页面完整刷新后确认浏览器缓存的 Supabase session 仍可被 Go 系统后端接受。 | 认证 middleware 先执行现有 JWT/JWKS、`exp/nbf/iss/aud/sub` 校验；随后使用公开 `apikey` 和同一用户 token 请求 Supabase Auth user endpoint，并要求 provider user ID 与已验证 UUID `sub` 一致。Provider `401/403` 返回 `401 auth.session_invalid`；timeout、rate limit、`5xx` 返回 `503 auth.session_verification_unavailable`；其他 provider 非成功状态返回 `502 auth.session_verification_failed`。请求不访问 PostgreSQL，不保存或记录 token，也不返回 provider 原始 payload。普通业务 API 不执行该远程确认。 |

前端只在该接口成功后向 Header 暴露缓存用户信息。明确的 `auth.session_invalid` 会清除当前浏览器本地
session；网络或 provider 暂不可用只隐藏未经确认的用户信息并保留本地 session，下一次刷新可重试。
同一页面初始化/认证事件对相同 access token 去重，不为每个业务请求重复确认。

## 2. 健康检查

| 方法与路径 | 功能 | 成功响应 | 执行逻辑 |
|---|---|---|---|
| `GET /health/live` | 进程存活检查 | `200 {status:"ok",traceId}` | 不访问数据库或 Storage，只证明 Gin 进程能够响应。 |
| `GET /health/ready` | 依赖就绪检查 | `200 {status:"ready",checks:{database:"ok"},traceId}` | 在独立超时内 Ping PostgreSQL；失败返回 `503` 和机器状态 `database=unavailable`，不暴露连接错误。 |

## 3. Component

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/components` | Query：`page/pageSize/locale/query/category/status`；`200 {items,page,pageSize,total,totalPages}` | 查询 actor 可见的公开/自有 Component 目录。 | 过滤未删除记录，并要求至少存在一个未删除 Version；owner 可见自己的记录，其他用户只见 `active` 且存在非 draft Version 的记录；按 reviewed translation 选择展示内容，返回 `ownedByActor/starredByActor/starCount`，按 `updatedAt DESC,id` 稳定排序。`query` 同时匹配展示名称和 Component ID。查询先固定当前页，再按页内 Component ID 一次聚合 Star 数，不逐行执行收藏计数。`total/totalPages` 复用与列表相同的授权和过滤条件。`logicalSize` 投影当前发布 Version 的 Preview Box；尚未发布、`currentVersionId` 为空时投影最新 Draft，旧 `components.logical_*` 仅为历史兼容回退。公开 `status` 筛选只允许 `draft/active`；`archived` 是 soft delete 内部状态，不属于正常组件列表。 |
| `POST /api/v1/components` | Body：`name,description?,tags,category?,contentLocale`；`201 Component` | 创建用户 Component 元数据。 | 校验名称、tag 数量和 locale；生成 UUID，在事务中写入 owner/creator；初始 Component 尚无结构版本，因此创建后可按 ID 读取，但在产生首个 Version 前不会进入 Component 列表投影。 |
| `GET /api/v1/components/:componentId` | Query：`locale`；`200 Component` | 读取单个可见 Component。 | 校验 UUID，通过 actor/active 可见性查询；返回 `ownedByActor/starredByActor/starCount`，其中所有权是稳定管理权限投影，前端不得依赖浏览器缓存用户对象自行推断；官方内容只选 reviewed translation，否则返回源内容及缺失标记。Preview stale/failed 不改变 Component 可见性、所有权或删除权限。 |
| `PATCH /api/v1/components/:componentId` | Partial Body：`name,description,tags,category,contentLocale`；`200 Component` | 修改 owner 的 Component 展示元数据。 | 至少提交一个字段；`description/category` 可显式传 `null` 清空；只更新 owner、未删除的用户 Component，并返回更新后的可见投影。 |
| `DELETE /api/v1/components/:componentId` | 无 Body；`204` | 删除用户 Component 的当前产品入口。 | 执行 soft delete：写 `status=archived`、`deleted_at/deleted_by`；不物理删除 Version、Import、Artifact、Task 或 Storage object。仅 owner 的 `content_kind=user` 可执行。 |

## 4. Component Version

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/components/:componentId/versions` | Query：`page/pageSize`；`200 VersionPage` | 列出 Component 的可见版本。 | 先校验 Component 可见性；owner 可读取自己的 draft，非 owner 只读取 active Component 的非 draft Version；稳定分页。 |
| `POST /api/v1/components/:componentId/versions` | Body：`componentCandidateId,version,revision,releaseNote?,releaseNoteLocale?,metadata?`；`201 ComponentVersion` | 从已审核 Candidate 显式创建 Draft Version。 | 锁定 owner Component；沿 `Candidate -> SceneSnapshot -> Import -> Artifact` 读取服务端可信的 source/exchange artifact、parser、Part Library 和三类 hash，客户端不能直接指定这些字段；冲突由唯一约束返回稳定错误。 |
| `GET /api/v1/component-versions/:versionId` | `200 ComponentVersion` | 读取单个可见版本及 validation/preview 状态。 | 使用 actor 可见性查询；不生成 Preview，也不读取对象正文。 |
| `GET /api/v1/component-versions/:versionId/diff` | `200 VersionDiff` | 计算 owner 当前版本相对本次导入基准版本的 BOM 与实例级结构差异。 | 只认 `Version -> Candidate -> Import.base_version_id` 的声明 lineage，不按创建时间猜父版本；首个版本与空树比较。读取两侧不可变 SceneSnapshot，在 Go `componentdiff` 内同步但严格有界地展开全部 root，返回 BOM 变化、确定匹配的实例变化和歧义组；不读取 GLB/Storage、不写数据库、不创建 Task。任一侧最多 50,000 个展开实例，明细最多 10,000 条，超限使用既有 `request.validation_failed`。即使 Version 已公开，本接口当前仍只允许 Component owner。 |
| `PATCH /api/v1/component-versions/:versionId` | Partial Body：`version,revision,releaseNote,releaseNoteLocale`；`200 ComponentVersion` | 修改 owner Draft Version 的展示元数据。 | 只允许未删除 draft；release note 与 locale 必须同时设置或同时清空；结构、hash、Artifact 和 Part Library 不可通过本接口修改。 |
| `DELETE /api/v1/component-versions/:versionId` | `204` | 删除未发布的 Draft Version。 | 只对 owner 用户 Component 的非 current draft 写 `deleted_at/deleted_by`；不删除已发布/废弃/归档版本。 |
| `POST /api/v1/component-versions/:versionId/publish` | 无 Body；`200 ComponentVersion` | 直接发布 owner 的 Draft。 | serializable transaction 锁定 owner Version，deprecated 其他 published Version、发布目标 Version，并设置 Component current version。ValidationReport 是可选质量信息，不参与 API 或数据库发布门禁。 |
| `POST /api/v1/component-versions/:versionId/deprecate` | 无 Body；`200 ComponentVersion` | 将 published Version 标记为 deprecated。 | 仅 owner；只允许 `published -> deprecated`，非法状态返回 conflict。 |
| `POST /api/v1/component-versions/:versionId/archive` | 无 Body；`200 ComponentVersion` | 归档 published/deprecated Version。 | 仅 owner；允许 `published -> archived` 或 `deprecated -> archived`，不修改版本的不可变结构字段。 |

### 4.1 Component Version Diff v1

`VersionDiff.algorithmVersion` 当前为 `component-scene-diff-v1`。结构权威输入是 SceneSnapshot document，
不是 GLB mesh；`structureHash/geometryHash` 及基准 hash 用于响应诊断，不替代实际展开与比较。响应中的
Part 编号、颜色、矩阵、change kind、hash 与算法版本都是机器数据，不做翻译。

核心响应结构：

```json
{
  "versionId": "uuid",
  "baseVersionId": "uuid",
  "comparisonBasis": "import_base_version",
  "algorithmVersion": "component-scene-diff-v1",
  "summary": {
    "beforeInstances": 12,
    "afterInstances": 13,
    "unchangedInstances": 10,
    "addedInstances": 1,
    "removedInstances": 0,
    "transformChangedInstances": 1,
    "colorChangedInstances": 1,
    "replacedInstances": 0,
    "ambiguousGroups": 0
  },
  "bomChanges": [
    {"partRef": "3001.dat", "beforeQuantity": 2, "afterQuantity": 3, "delta": 1}
  ],
  "instanceChanges": [],
  "ambiguousGroups": [],
  "truncated": false
}
```

实例匹配按固定优先级执行：完全相同的 `part + color + worldMatrix`、同 Part/位置的改色、同颜色/位置的
Part 替换、同 Part/颜色且两侧都唯一的 transform 变化，最后才是新增/删除。world matrix 以 `1e-6`
归一化，避免解析期无意义浮点噪声。若同 Part/颜色在两侧剩余多个实例且不能唯一配对，返回
`ambiguousGroups`，不会按数组顺序伪造 `transform_changed`。BOM 数量差独立计算，始终覆盖完整结果；
`truncated=true` 只表示实例/歧义明细达到 10,000 条，Summary 和 BOM 仍完整。

Component 详情页按用户选择的目标 Version 调用本接口，并只读取目标/基准 Version 已由 Worker 物化的整体
GLB；页面不会为 Diff 创建 Task，也不会请求 Preview 物化。两个 GLB 使用相同的 Component 根坐标转换和一次
共同居中，以左右双栏、同步相机显示。未变化实例作为半透明上下文，新增、删除、移动、改色、替换和歧义实例
使用稳定颜色、发光轮廓与缓慢脉冲标记；系统开启 `prefers-reduced-motion` 时停止脉冲但保留静态高亮。点击实例
明细会用相同相机目标同时聚焦两侧。首版左侧显示空基准；任一所需 GLB 不可用时仅报告对比预览不可用，不会
改变 Version 或 Artifact 状态。

离线调试可复用同一纯 Go 算法，不访问 PostgreSQL 或 Storage：

```bash
cd backend-go
go run ./cmd/component-diff --before base-document.json --after head-document.json
```

省略 `--before` 时与空树比较；文件内容必须是 `scene_snapshots.document` JSON，而不是完整数据库行或 GLB。

## 5. Component Group 与 Star

### 5.1 Group

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/component-groups` | `200 {items: Group[]}` | 读取 actor 的 root/custom Group 树投影。 | 严格只读，不自动创建 root；返回 depth、sort order 和 direct component count。root 明确表示 actor 自己拥有的 Component；Star 由独立“我的收藏”视图承载。root 计数从 owner 索引取得候选，不扫描 Star 或公开 Component 全集。 |
| `POST /api/v1/component-groups/bootstrap` | `204` | 显式初始化个人仓库 root Group。 | serializable transaction 内执行幂等 `ensure root`；重复调用不创建多个 root。 |
| `POST /api/v1/component-groups` | Body：`parentGroupId?,name,contentLocale,sortOrder`；`201 Group` | 创建 custom Group。 | parent 缺省时显式确保 root；校验 owner parent、同级规范化名称唯一和最大深度 5。 |
| `PATCH /api/v1/component-groups/:groupId` | Partial Body：`name,contentLocale,sortOrder`；`200 Group` | 修改 custom Group。 | 至少一个字段；仅 owner custom Group；更新规范化名称并由唯一约束防止同级重名。 |
| `DELETE /api/v1/component-groups/:groupId` | `204` | 删除 custom Group。 | 仅 owner custom Group；root 不能删除；关联行为继续由 Goose 外键/约束控制。 |
| `POST /api/v1/component-groups/:groupId/move` | Body：`parentGroupId,sortOrder`；`200 Group` | 移动 custom Group。 | 锁定 owner group，拒绝移动到自身子树形成循环；计算 parent depth 与 subtree depth，保证整体最大深度 5，并重新检查同级名称唯一。 |
| `GET /api/v1/component-groups/:groupId/components` | Query：`page/pageSize/locale`；`200 GroupMemberPage` | 列出该 Group 的直接成员。 | 校验 owner Group；custom Group 按 membership 驱动，root 只按 actor 自有 Component 驱动；使用 Component 可见性、reviewed translation 与 Version `logicalSize` 投影规则。取消 Star 不自动删除 custom membership，当前仍可见的外部成员可继续移出分组。结果先分页，再一次聚合页内 `starCount`。 |
| `GET /api/v1/component-groups/:groupId/components/search` | Query：`page/pageSize/locale/query/status`；`query` 最多重复 8 次，`status` 可重复且只允许 `draft/active`；`200 {items,total,totalPages,statusCounts,...}` | 为仓库页面提供名称、ID 或 Box 尺寸的复合搜索、分页和状态统计。 | root Group 只表示 actor 自己拥有的 Component，custom Group 按直接 membership。每个非空 `query` 都是必须满足的独立条件，条件之间按 AND 组合并忽略大小写重复项。普通条件对名称或 Component ID 做模糊搜索；完整的 `a x b` 或 `a x b x c`（兼容 `x/X/×` 和小数）进入尺寸模式。输入与 Version `logicalSize` 都按升序归一化；三值逐维满足严格开区间 `(target-1,target+1)`，两值枚举 `ab/ac/bc` 三组配对且每维使用同一开区间，边界恰好相差 1 不命中。缺少任一 Box 尺寸的组件不能满足尺寸条件。状态统计与结果使用完全相同的候选集、复合条件、可见性及尺寸规则；结果页内 Star 数一次聚合。`logicalSize` 仍按当前发布 Version / 最新 Draft 投影。Import/Task 的处理中或失败状态不得作为 Component 状态传入。 |
| `POST /api/v1/component-groups/:groupId/components` | Body：`{componentId}`；`204` | 将可见 Component 加入 custom Group。 | 校验 owner custom Group 与 Component 可见性；以 `(owner,group,component)` 幂等写 membership。 |
| `DELETE /api/v1/component-groups/:groupId/components/:componentId` | `204` | 从 Group 移除成员。 | owner-scoped 删除 membership；记录不存在也按成功处理。 |
| `GET /api/v1/components/:componentId/groups` | `200 {componentId,groupIds}` | 查询 Component 当前所在的 custom Group IDs。 | 先校验 Component 对 actor 可见，再只返回 actor 自己的 custom Group membership，不返回其他用户分组。 |

### 5.2 Star

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/component-stars` | Query：`page/pageSize/locale/query/category/sort`；`sort` 只允许 `starred_at_desc`；`200 {items,total,page,pageSize,totalPages,relationshipTotal}` | 读取当前 actor 的个人收藏。 | 按 `starredAt DESC,componentId` 稳定排序；`query` 匹配展示名称/Component ID，完整 `axb/axbxc` 复用 Group 的轴无关 logical-size 开区间规则，`category` 精确匹配。只投影当前 `active` 且存在非 draft Version 的 Component；软删除或暂时不可见时保留关系但隐藏结果。`total` 是当前过滤后的可见数，`relationshipTotal` 只返回 actor 的关系总数以区分空状态，不暴露不可见 Component 内容。计数在一条 SQL 中返回两个值；列表先分页再一次聚合页内 `starCount`，不公开收藏者列表。 |
| `PUT /api/v1/components/:componentId/star` | `200 {componentId,starredAt}` | 收藏可见的非本人 Component。 | 使用轻量目标查询读取 Component 删除/可见性、owner、状态、非 draft Version 存在性和已有关系；不读取完整详情或收藏总数。首次创建要求目标未删除、非本人、`active` 且存在非 draft Version；已有关系直接返回原 `starredAt` 并跳过写入，并发首次收藏仍由 `(actor_id,component_id)` 唯一键收敛；不产生 Watch 通知。 |
| `DELETE /api/v1/components/:componentId/star` | `204` | 取消收藏。 | actor-scoped 删除 Star；Component 后续不可见或关系不存在时也按成功处理。 |

Goose `00014_component_stars.sql` 将旧 `component_subscriptions` 一次迁移为 `component_stars`，迁移来源写入
`source=subscription_migration`；新用户操作写入 `source=user_action`。迁移完成后不存在双写或旧 Subscription API。

## 6. 上传、Artifact 与源文件

### 6.1 上传流程

当前实现及目标链路：

```text
POST upload-sessions
  -> 前端按服务端 bucket/objectPath 直传 Supabase Storage
  -> POST upload-sessions/:id/complete
  -> component.artifact.verify（每个文件）
  -> component.import.parse（依赖全部 verify succeeded）
  -> Import + SceneSnapshot + BOM + Candidate + Draft Version
  -> preview materialize Worker -> verified ComponentVersion GLB
  -> processingStatus=ready
```

Go Backend API 拥有上传控制面：创建 upload session、生成并持久化可信对象位置、完成确认和持久任务
编排。浏览器使用当前用户 JWT 把正文直接写入 API 返回的精确 Storage 目标；INSERT RLS 只允许 actor
自己仍为 pending、未过期的 upload session key。API 不接收或缓存文件正文，不解析文件、不生成
BOM/GLB，也不等待 Worker 完成。

前端上传弹窗只覆盖“创建 session -> 浏览器直传 -> complete”三步。complete 返回 `202` 后弹窗立即
关闭并进入由 `importId` 定位的只读处理状态页；不得在上传弹窗内等待 parse/preview ready。处理状态
页可以轮询 Import 聚合投影，但该轮询只观察状态，不补发 parse、Preview 或其他 mutation。

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `POST /api/v1/component-imports/upload-sessions` | Body：`sourceFile,exchangeFile?,targetComponentId?,baseVersionId?,contentLocale,timezone`；`201 UploadSession` | 创建 API 控制的浏览器直传会话并分配可信 Storage 目标。 | 校验 `.io/.ldr/.mpd`、大小、SHA-256、locale/timezone 和 owner target/base lineage；服务端生成 Artifact UUID、bucket 和 owner-scoped object path，在事务中写 pending session/files。响应中的目标只能原样用于当前用户 JWT 直传；客户端不能指定可信 key。Storage INSERT RLS 再次按 owner、pending、expiry 和精确 key 授权。接口不接收文件正文。 |
| `POST /api/v1/component-imports/upload-sessions/:sessionId/complete` | 无 Body；`202 {importId,taskId,status}` | 声明直传完成，建立 Artifact、Import 和任务链。 | 使用用户 token 对每个对象做 Storage HEAD，核对 provider/bucket、size 和 MIME；对象不存在或 metadata 不匹配时标记 session/files failed 并尽力补偿删除对象，Storage/provider 暂不可用时返回依赖错误并保留重试可能。成功时在一个事务中创建 immutable pending Artifact、每文件 verify task、parse task 与 dependency、Import，并完成 session。返回的 `taskId` 是 parse task；SHA-256 正文校验由 Go Worker 完成。Parse Worker 在写 SceneSnapshot/BOM/Candidate/Draft 的同一事务中创建首个 Preview Logical Job/Execution、设置 Version preview task 并建立 `Preview -> Parse` dependency。重复 complete 返回既有 Import/task。 |
| `GET /api/v1/artifacts/:artifactId/download` | `200 {artifactId,url,expiresAt}` | 为 owner Artifact 创建短期下载地址。 | 只查询 owner、verified Artifact；使用用户 token 通过 Storage RLS 签名；不代理文件正文，不返回永久 URL。 |
| `GET /api/v1/component-versions/:versionId/source` | `200 {artifactId,url,expiresAt}` | 下载可见 Version 的原始 source Artifact。 | 通过 Version 可见性选择其 source Artifact；要求 verified 且 provider/bucket 与当前 Storage 一致，再生成用户身份下的短期签名 URL。 |

#### 6.1.1 Storage 写入授权

`bucket/objectPath` 是 API 生成并已写入 `upload_session_files` 的临时传输目标，不是客户端可选择的业务
字段。Supabase `storage.objects` INSERT policy 调用 `can_upload_component_session_file(name)`，只有同时
满足 provider/bucket、精确 key、file pending、session pending、owner=`auth.uid()` 且未过期才允许写入。
authenticated 客户端无 Artifact DELETE policy；失败补偿和过期对象清理由 Worker 的服务端凭据执行。

`sourceFile/exchangeFile` 结构：

```json
{
  "filename": "model.io",
  "contentType": "application/x-studioformat",
  "fileSize": 275136,
  "sha256": "64-char-hex"
}
```

Studio `.io` 接受 `application/x-studioformat` 和 `application/octet-stream`；LDraw `.ldr/.mpd`
使用 `text/plain`。exchange file 不能再次是 `.io`。

## 7. Import 与 Candidate

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/component-imports` | Query：`page/pageSize/processingStatus?/query?/componentId?`；`200 {items,total,page,pageSize,totalPages,statusCounts}` | 分页读取当前用户的持久化 Import 历史；供全局导入记录页和组件详情 Import Tab 复用。 | 严格按 `owner_id` 查询；`processingStatus` 只允许 `processing/ready/failed`。文件名或 Import ID 支持搜索。`componentId` 同时匹配更新导入的 `target_component_id` 与新建导入的 `Candidate -> Draft Version -> component_id`，因此一个 Component 的历次新建/更新 Import 都可回溯；Version 软删除后仍通过最近历史 Version 保留 Component 关联。列表聚合 parse、SceneSnapshot、Draft、Preview Task 和 verified Preview Artifact，状态口径与单条 Import 一致；返回源文件名/大小/MIME、关联 ID、结构化 failure 和时间，不返回 Storage provider/bucket/key 或 Task payload。 |
| `GET /api/v1/component-imports/:importId` | `200 Import` | 查询上传解析与 GLB 生成的 durable 聚合状态。 | owner-scoped 联表读取 Import、Candidate/SceneSnapshot、Draft Version、Preview Task 和 Preview Artifact，返回 `processingStatus`、`previewTaskId` 及结构化 failure。只有 Import succeeded、Snapshot/BOM/Draft 均存在、Version preview ready 且 Preview Artifact verified 时返回 `ready`；parse succeeded 单独不启用预览。客户端可在刷新后恢复轮询。 |
| `GET /api/v1/component-candidates/:candidateId` | `200 Candidate` | 读取待审核 Candidate 及其权威 SceneSnapshot。 | owner-scoped 联表读取 Candidate、Import、SceneSnapshot、BOM、parse issues、三类 hash、目标 Component/Draft Version；不重新解析文件。`component-repo-v2` document 使用有序 `rootInstances[]` 表达场景入口，`rootModelId` 只保留普通单主模型的投影。 |

### 7.1 上传处理投影

`GET /api/v1/component-imports/:importId` 是刷新后可恢复的上传处理入口，并提供稳定机器字段
`processingStatus`：

| 值 | 判定 | 前端行为 |
|---|---|---|
| `processing` | verify/parse/preview 任一必要阶段仍在 queued/running，或 parse 已成功但 verified GLB 尚未 ready | 只显示本地化处理状态；不挂载 Viewer，不请求 Preview URL |
| `ready` | Import/SceneSnapshot/BOM/Draft 均已持久化，且 Draft Version 的 Preview Artifact 已生成并 verified | 可以读取 Version BOM 和 Preview，并挂载 Viewer |
| `failed` | 任一必要阶段不可恢复地 failed/cancelled，或必要 Artifact 无效 | 展示结构化 `failure.code + params`；不展示旧/局部 Preview |

响应同时返回恢复结果读取所需的 `draftVersionId`，并返回 `previewTaskId` 供诊断/细粒度进度查询。
`importId` 是页面恢复主句柄；前端不应拼装 task 状态来推断一个更宽松的 ready 条件。

进入 `ready` 后，Candidate 结果页默认并发读取 Draft Version 的 Preview 与 BOM，并分别处理两者的
成功或失败；页面不会因为其中一项失败而隐藏另一项。relation、connector 和 interface 不在默认读取
集合中，只有用户开启“加载连接信息”开关后才读取对应 Candidate 投影。关闭开关只隐藏高级工作台，
不会创建、修改或删除 connector 数据。

公开 Component 详情的读取矩阵与 Candidate 审核页不同：非 owner 可以读取已发布 Version、整体 Preview、
冻结 BOM 和按 Version 可见性授权的 ValidationReport，但不得请求 Candidate-scoped relation、connector 或
interface；这些接口继续由 Workbench `ownedCandidate` 边界保护。前端以 `ownedByActor` 决定是否发起这组请求，
不能把 404 降级当作正常的公开详情加载流程。

## 8. Durable Task

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/tasks/:taskId` | `200 Task` | 查询 actor 自己的任务状态。 | 返回 logical job ID、execution number、状态、result、result Artifact、冻结 locale/timezone、attempt、progress、error 和时间；不返回内部 payload、lease owner、SQL 或异常正文。 |
| `POST /api/v1/tasks/:taskId/cancel` | `200 Task` | 请求取消任务。 | terminal task 幂等返回原状态；queued task 立即变为 cancelled 并传播依赖终态；running task 只写 cancel request，由 Worker heartbeat 协作停止并提交最终 cancelled。 |

## 9. Relation、Connector 与 Interface

本节接口均属于上传完成后的按需审核能力。Candidate 结果页初次进入不会调用这些读取接口；用户开启
连接信息开关后，前端才并发读取 relation、connector 与 interface。关系检测仍必须由显式 mutation
触发，单纯开启或关闭开关不会调度检测任务。

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/component-candidates/:candidateId/relations` | `200 {items: RelationCandidate[]}` | 读取关系检测候选和审核状态。 | owner-scoped 读取已物化 relation candidates；不触发检测。 |
| `POST /api/v1/component-candidates/:candidateId/relations/detect` | `202 AcceptedTask` | 调度关系、connector 和 external interface 检测。 | 要求 Candidate 绑定冻结且 `relation_ready=true` 的 Part Library，并存在 draft Version；input hash 覆盖 structure/geometry、snapshot schema/parser、Part Library ID/source hash、connector source hash/parser version 和 detector version；复用相同 Logical Job，并把 task 关联回 Candidate。Go Worker 从冻结 connector definitions 计算关系，原子写入 relation candidates、connector analysis、external interfaces 和 Candidate/Draft interface signature；不修改 SceneSnapshot transform。 |
| `POST /api/v1/component-candidates/:candidateId/relations/:relationId/confirm` | `200 AssemblyRelation` | 确认关系并占用对应 connector。 | serializable transaction 锁定 owner RelationCandidate；已确认时幂等返回 AssemblyRelation；拒绝已 rejected relation；创建 AssemblyRelation，由数据库 connector slot/capacity 约束防止冲突，将已占用 connector 标为 internal，删除对应 external interface，重新计算 Candidate 与 Draft interface signature。 |
| `POST /api/v1/component-candidates/:candidateId/relations/:relationId/reject` | `200 RelationCandidate` | 拒绝未确认的关系候选。 | 锁定 owner relation 并更新状态；已经生成 AssemblyRelation 的候选不能再拒绝。 |
| `GET /api/v1/component-candidates/:candidateId/connectors` | `200 {items: Connector[]}` | 读取 Candidate 的标准化 connector 分析。 | owner-scoped 查询 connector 世界坐标、类型、性别、状态、capacity/occupied/available 和 eligibility；不重新计算 connector。 |
| `GET /api/v1/component-candidates/:candidateId/interfaces` | `200 {items: Interface[]}` | 读取当前 external interface 投影。 | owner-scoped 查询尚暴露的 connector interface、机械/业务角色、requirements 和 review status；确认关系后已内部占用的 connector 不再出现在 external interface 中。 |

注意：Part Library 的 `status=active` 只表示生命周期，不能替代能力判断。Part preview 与关系检测
分别使用 `preview_ready`、`relation_ready`；关系接口不会仅凭 active 状态调度任务。

## 10. Validation 与 BOM

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `POST /api/v1/component-candidates/:candidateId/validate` | `202 AcceptedTask` | 为 Candidate 当前关联的 Draft 或 Published Version 调度可选质量验证。 | 要求 owner Candidate 关联有效 Draft/Published Version；input hash 覆盖 interface/structure/geometry、Part Library source hash 和 validator version；创建或复用 `component.validate` Logical Job，由 Go Worker 写 durable ValidationReport，并把最近一次通过或失败报告关联到 Version。接口不发布版本，也不在 HTTP 请求内执行验证。 |
| `GET /api/v1/validation-reports/:reportId` | `200 ValidationReport` | 读取结构化校验报告。 | Draft 报告只允许 owner；active Component 的非 Draft Version 报告沿用版本公开可见性。返回 candidate/version、level、passed、checks、issues 和 validator version；checks/issues 保存机器 `code + params`，不保存最终译文。 |
| `GET /api/v1/component-versions/:versionId/parts` | Query：`locale`；`200 VersionParts` | 读取 Version 的冻结 BOM 展示投影及各 Part 的预览几何可用状态。 | 从可见 Version 的 SceneSnapshot 读取解析期持久化 BOM，不在 GET 中读取源文件或重新展开 Scene；BOM 由 Go parser v2 对全部显式 `rootInstances[]` 递归展开后生成：同一模型的多个 root/子模型实例分别计数，未被入口引用的 model definition 不计入。接口按 `ldrawPartNum` 排序，使用 Version 冻结的 Part Library 选择 reviewed Part translation，缺失时返回 source fallback/missing；再以同一冻结 Part Library LEFT JOIN `part_geometries`，返回 `ready/failed/missing`。 |

`VersionParts` 响应：

```json
{
  "versionId": "uuid",
  "partLibraryVersionId": "uuid",
  "partCount": 4,
  "items": [
    {
      "ldrawPartNum": "3001.dat",
      "quantity": 4,
      "name": "Brick 2 x 4",
      "contentLocale": "en-US",
      "translationStatus": "reviewed",
      "geometryStatus": "ready"
    }
  ]
}
```

`partCount` 是所有叶子 Part 实例数量之和，不是 Part 种类数。`ldrawPartNum`、`quantity`、
`partCount` 和 `geometryStatus` 是稳定机器数据；`geometryStatus=ready` 表示冻结库存在可用于整体
GLB 的几何，`failed` 表示几何导入失败，`missing` 表示没有几何记录；后两者仍保留在 BOM，但整体
GLB 会跳过相应实例。`name/contentLocale/translationStatus` 是独立的官方内容展示投影。
parser v1 / snapshot v1 已有记录保持不可变，不在 GET 中静默改写；需要新计数语义的旧开发版本应从
原始 Artifact 重新导入为 parser v2 / snapshot v2。

## 11. Component Preview

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `GET /api/v1/component-versions/:versionId/preview` | `200 Preview` | 只读查询 Version Preview 状态和短期 URL。 | 查询 actor 可见 Version；generator 版本过期时返回 `status=stale`；只有 ready、generator 当前且 Artifact 存在时才通过用户 token 签名 URL。GET 不创建任务、不写 Artifact。 |
| `POST /api/v1/component-versions/:versionId/preview/materialize` | `202 AcceptedTask` | 显式重建或恢复 ComponentVersion 整体 GLB。 | 仅 owner Version；若 ready cache object 存在，直接返回既有 succeeded task；pending/running 复用任务；failed、generator stale 或 Storage object 丢失时增加 generation 并 force new。input hash 绑定 Version、SceneSnapshot、structure/geometry、冻结 Part Library/source hash 和 generator version，由 Go Worker 生成 GLB。Worker 对递归展开后的全部 Root、全部实际渲染实例逐顶点应用 world matrix，合并 LDraw 世界坐标 AABB，并在 Artifact upsert 与 Version ready 的同一事务中写 `preview_bbox_*`、stud/plate 逻辑尺寸及完整性。冻结库中 `geometry_status` 非 ready 或没有 geometry 的 Part 被跳过，任务结果和 Artifact metadata 记录稳定排序的 `omittedPartRefs` 与 `complete=false`；此时 Box 描述实际 GLB，`preview_bounds_complete=false`，BOM 不删减。全部实例均无可用几何时仍允许生成空场景 GLB，但 Version Box 保持空值。已标记 ready 的本地 source 缺失、哈希漂移或递归解析失败仍使任务失败。普通上传主链不由浏览器调用本接口；首个任务由 Parse Worker 事务性串联。 |

### 11.1 Preview Box 与历史回填

- `preview_bbox_min/max` 是 ComponentVersion 的派生事实，坐标单位为 LDraw 世界单位；不能由异步完成的
  Draft 任务直接覆盖 Component 当前发布版本的尺寸。
- `logicalWidthStud=(maxX-minX)/20`、`logicalDepthStud=(maxZ-minZ)/20`、
  `logicalHeightPlate=(maxY-minY)/8`，统一保留四位小数。
- 生成器 `component-preview-studio-ldraw-glb-v4` 开始产出上述字段。历史 ready Preview 通过
  `backend-go/scripts/backfill-component-preview-bounds.sh` 受控调度新的 durable execution；脚本先核对精确
  数据库目标并执行 Goose，再由 Go Worker 重建，不在维护进程中同步解析文件或直接写尺寸。

普通上传客户端流程：

```text
POST upload complete -> 202
  -> 上传弹窗立即结束，导航到 /component-repo/imports/:importId
  -> 状态页只读轮询 Import/processing projection
  processing -> 仅显示本地化“解析中”，不挂载 Viewer、不请求预览 URL
  ready      -> 并发读取 BOM 和 Preview，分别展示；连接数据保持未加载
              -> 用户开启连接信息开关后，按需读取 relation/connector/interface
  failed     -> 使用结构化 code + params 展示失败，不展示旧/局部预览
```

显式 materialize 保留给派生缓存丢失、生成器升级和受控重建，不作为正常上传的浏览器副作用。

## 12. Part Search、Part Library 与 Part Preview

这些接口仍位于认证 `/api/v1` group，但读取不是 owner 私有资源；任何通过认证的用户都使用相同的
不可变 `partLibraryVersionId + ldrawPartNum` 定位 Part。

| 方法与路径 | 输入与响应 | 负责功能 | 执行逻辑 |
|---|---|---|---|
| `POST /api/v1/parts/search` | Body：`{query,page,pageSize}`，默认 `page=1/pageSize=50`，本接口 `pageSize` 最大 `200`；`200 PartSearchPage` | 在当前 active Studio Part Library 中搜索可预览 Part，并返回本次查询绑定的 `partLibraryVersionId`。前端通过共享 authenticated API client 携带当前 Supabase Bearer token。 | 将 `query` 按空格、中英文逗号分段；完整 `axb`/`axbxc`（兼容 `x/X/×` 与小数）作为精确尺寸候选，其余片段作为源名称或 LDraw 编号关键词。至少命中一个关键词、至少命中一个尺寸候选，两个集合同时存在时按 AND 组合；二维尺寸允许平面旋转，三维尺寸按升序精确匹配。只返回 `geometry_status=ready`，排除源名称中的 sticker/decal；按命中关键词数、源名称、编号稳定排序。查询只读取 PostgreSQL，不读取 `LDRAW_ROOT`、不解析文件、不访问 legacy `public`、不创建 Task。结果名称来自 `parts.source_name` 并标记 `translationStatus=source`。若该 Part 已绑定当前 `part-preview-ldraw-meshopt-glb-v2` 的 ready/verified Artifact，item 额外返回 `previewModel={artifactId,format,compression,url,sha256,byteLength}`；Storage key 不出 API。Go 对当前页全部对象执行一次服务端批量签名，单个对象失败只令该 item 的 `previewModel=null`，整批 Storage 故障也降级为无预览的正常搜索结果。`imageUrl` 暂时保留为 `null`，不再代表列表缺少预览能力。 |
| `GET /api/v1/part-library-versions/active` | `200 PartLibraryVersion` | 发现当前 runtime 默认 Part Library Version 及其能力。 | 读取唯一 active library 的 ID、source name/hash、status、`previewReady/relationReady`、connector/collider source count 和 created time；不存在返回 `part_library_not_found`。`colliderCount` 是已验证输入定义数，不保证逐行存入 PostgreSQL；存储模式由 library metadata 审计。该接口不改变 active 状态；能力字段来自数据库显式门禁，不由 `status` 推断。 |
| `GET /api/v1/part-library-versions/:partLibraryVersionId/parts/:ldrawPartNum/preview` | Query：`locale`；`200 PartPreview` | 查询不可变 Part 的 geometry、名称翻译和 GLB 状态。 | 规范化 part number，拒绝路径字符；读取 Part、geometry 和 preview state；只选 reviewed translation，否则 source fallback。仅当前 `part-preview-ldraw-meshopt-glb-v2` ready Artifact 使用服务端 Storage 签名 URL；旧 generator 只投影为 pending，不把旧 GLB 暴露给前端。GET 不创建任务。 |
| `POST /api/v1/part-library-versions/:partLibraryVersionId/parts/:ldrawPartNum/preview/materialize` | Body：`{locale,timezone}`；`202 AcceptedTask` | 显式生成单个 Part GLB。 | 要求 Part geometry ready 且 source hash 存在；当前版本 ready cache 存在时复用 succeeded task，pending/running 复用活动任务，failed、旧 generator 或缓存丢失时递增 generation。input hash 覆盖 Part Library source hash、Part source file hash 和 generator version。Go Worker 从只读 `LDRAW_ROOT` 递归展开 LDraw type 1/3/4，将坐标烘焙为项目 Y-up/stud 单位，生成折角法线与索引，再由原生 gltfpack 输出 `EXT_meshopt_compression`。最终 GLB 按 SHA-256 存入同一 Storage bucket 的 `component-repo/part-library-assets/glb/{generator}/{sha前缀}/{sha}.glb`；Artifact 为全局无 owner、不可变、内容寻址资源，`part_previews` 负责 Part 到 Artifact 的版本绑定。 |

全库预生成没有公共 HTTP 路由。`backend-go/scripts/prebuild-part-previews.sh` 先显示数据库、bucket、prefix
和待处理数量；只有设置精确 `CONFIRM_DATABASE_TARGET` 与 `PART_PREVIEW_PREBUILD_EXECUTE=1` 才调度
`component.part_preview.prebuild` durable task。单个坏 Part 记录结构化失败并继续，其余 Part 独立提交；重复执行只选择
缺失或 generator 过期条目。

### 12.1 旧 fitting candidate recall 功能盘点与迁移范围

旧 `POST /api/fitting/candidates/recall` 是 Python fitting 算法域的通用候选画像接口，不只是
`/part-search` 页面接口。原功能点及本次 Go 迁移处理如下：

| 旧功能点 | 原执行逻辑 | 当前 Go Part Search 处理 |
|---|---|---|
| Candidate 类型 | 支持 `part/submodel/component`，读取 `fitting_candidate_profiles`。 | 当前页面只请求 `part`；Go 新接口是专用 Part resource，不接受 candidate type。Component/Submodel 召回仍属于其他 fitting 算法调用者，不进入 Component Repo Go API。 |
| Profile 状态与 irregular | 默认 `ready`，可选择 failed `non_grid_dimension` 异常 Part，并施加 penalty。 | 页面原本固定 `includeIrregular=false`；Go 只返回 active library 中 geometry ready 的 Part，不暴露 irregular 开关。 |
| 搜索框解析 | 空格/中英文逗号拆分；`axb/axbxc` 为精确尺寸，其余为名称关键词。 | 已迁移；同时允许关键词匹配稳定 LDraw 编号。名称关键词仍是“至少一个命中”，尺寸候选也是“至少一个命中”。 |
| 显式 bbox / logicalSize | 可指定 LDU bbox、stud/plate logical size、tolerance 和 planar rotation。 | 当前页面不传这些独立字段；Go 页面契约只保留 query 内精确尺寸，二维允许旋转。若 fitting 业务需要显式 bbox/tolerance，应在其自身 Go 路线中设计，不扩张本接口。 |
| Connector / category / color | 对画像 JSON 的 connector count、分类和颜色摘要做过滤并加分。 | 当前页面不传；未迁移到 Part Search。Part Library 已有 connector definitions，但不能把 relation 数据直接等同于旧画像评分。 |
| `key` 模糊名称与评分 | `SequenceMatcher` 阈值、bbox/尺寸距离、过滤 bonus/irregular penalty 组成 score；再按 score/type/id 排序。 | 当前页面只传 `query`；Go 使用可解释的关键词命中数和稳定名称/编号排序，不复刻未被页面使用的算法 score。 |
| 图片补全 | 从 legacy `rb_part_images/xref_part_numbers` 选择图片 URL。 | 不迁移 legacy 图片表。Go 基于当前版本化 Part GLB Artifact 返回可选 `previewModel`；前端进入视口附近后下载 GLB，通过单一共享 WebGL renderer 生成静态 256px WebP，并按 Artifact ID/SHA 缓存在内存与 IndexedDB。列表不创建 20 个常驻 3D Viewer/RAF，也不向 Storage 写 24k 份缩略图对象；生成或加载失败时仅显示既有占位图。 |
| 分页 | 全量过滤和评分后进行页码分页，最大 200。 | 已迁移为 PostgreSQL count + stable page query，最大 200；响应绑定实际 `partLibraryVersionId`。 |

Studio importer v3 在离线导入期从顶层 LDraw 文件头读取源语言描述并写入 `parts.source_name`；API
不会在请求时读取本机 Studio。已有 importer v2 active snapshot 需要通过受控
`backend-go/scripts/update-studio-part-library.sh` 重新导入后，`tile/plate` 等名称搜索才具备完整数据。
脚本会比较 importer version，不会因 manifest hash 相同而错误 no-op；API/Worker startup 不执行该更新。

## 13. 端到端主链路

### 13.1 新建 Component

```text
创建 upload session
  -> 浏览器使用用户 JWT 直传 API 已登记的精确 Storage key
  -> complete session -> 202（本次前端写交互结束）
  -> artifact verify task
  -> import parse task
  -> SceneSnapshot + BOM + Candidate + Draft Version
  -> component preview materialize task
  -> BOM + verified Component GLB ready
```

后续可选工作台流程与普通上传主链分离：

```text
GET Candidate / Draft Version
  -> relation detect task
  -> confirm/reject relation
  -> publish Draft Version（不要求 ValidationReport）
  -> 用户可在发布前或发布后独立触发 validation task + ValidationReport
```

### 13.2 API 与 Worker 的责任边界

- Go Backend API 负责认证、授权、输入校验、可信 Storage key 分配、完成确认、可见性查询、短事务、
  持久任务编排和短期 URL；浏览器只使用当前用户 JWT 向 API 已登记的精确目标直传正文。
- Worker 负责正文 hash、Studio/LDraw 解析、关系检测、可选质量验证和 GLB 生成。
- 普通上传的必要派生任务由服务端串联；客户端只读轮询，不负责触发解析或首次 GLB 生成。
- PostgreSQL 是 Component、Import、Candidate、Task、ValidationReport 和 Artifact metadata 的事实来源。
- Object Storage 是上传源文件和大型派生 Artifact 正文的事实来源。
- API/Worker 启动不执行 Goose migration、DDL、数据修复或 Studio snapshot 导入。

## 14. 当前明确未提供的接口

- 不提供旧 `/api` FastAPI 兼容路由、代理或双写。
- 不提供同步 multipart Component 导入；上传必须走直传 session。
- 不提供 Candidate Preview；Import 已物化 Draft Version，Preview 以 Version 为地址。
- 不提供 GET 隐式 materialize。
- 不提供在线 hard purge；Component DELETE 当前为 soft delete。
- 不提供通用 `library-items` Part Preview alias。
- 不提供公共 Worker claim/heartbeat/complete HTTP API；Worker 直接使用 PostgreSQL 持久化协议。
