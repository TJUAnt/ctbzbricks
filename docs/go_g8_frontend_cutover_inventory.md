# G8 Component Repo 前端切换清单

> 状态：主要前端 adapter、上传主链与全部任务 consumer 已切到 Go；保留 legacy 对照列仅供删旧审计
> 日期：2026-08-24
> 目标：前端只访问 Gin `/api/v1`，删除 Component Repo Python 公共路由并完成 Worker Go-only
> 原则：[go_backend_migration_principles.md](./go_backend_migration_principles.md)  
> 路线：[go_component_migration_plan.md](./go_component_migration_plan.md)
> Studio Part Library 路线图：[go_part_library_studio_roadmap.md](./go_part_library_studio_roadmap.md)

## 1. 盘点结论

初始盘点时，前端的 Component Repo 请求集中在
`frontend/src/componentRepo/componentRepoApi.ts`，由 Component Repo 四个页面和
`PartViewerPage` 使用，配置仍指向旧 `/api`。截至 2026-08-22，Component Repo adapter
配置已全部切到 `/api/v1`；下表的旧接口列用于保留迁移基线，不表示当前仍在调用。

Gin 已覆盖主要领域能力，但切换不是路径前缀替换：列表分页、分组根视图、上传完成、任务轮询、
关系检测、可选版本验证、预览物化、下载和若干 DTO 都已经采用新的目标契约。前端单一 adapter 已按
目标契约重写；不增加兼容代理、旧 DTO wrapper 或双路请求。

2026-08-12 已切换能够在同一 Go 数据域独立闭环的能力：Component/Version 读取、上传、
Import/Task/Candidate、关系审核、connector/interface、可选版本验证、Component 元数据与发布、预览、
BOM、源文件下载、draft 删除、分组库查询/管理、Draft Version 元数据和 ValidationReport 读取。
2026-08-14 已删除旧 Part/Library preview 路由。Part viewer 使用冻结的
`partLibraryVersionId + ldrawPartNum`，同一个业务动作不会同时请求两套后端。2026-08-15
真实开发库已执行 Goose v8/v9、legacy Part 数据交接和 legacy Rebrickable external ID
交接；随后 Studio LDraw snapshot 已导入并切换为 active Part Library。当前剩余项以
[进度台账](./go_migration_progress.md) 为准。

## 2. 迁移使用面

| 前端流程 | 旧 FastAPI 基线 | Gin 目标 | 结论 |
|---|---|---|---|
| 组件详情 | `GET /api/components/:id` | `GET /api/v1/components/:id` | 可切换；query 改为 `locale`，DTO 改用 `ownerId/subscribed/translationMissing` |
| 版本列表/详情 | `GET /api/components/:id/versions`、`GET /api/component-versions/:id` | 同资源的 `/api/v1` 版本 | 可切换；响应从数组改为 page object，`componentCandidateId` 可为空 |
| 分组树 | `GET /api/component-groups` 返回 `{root,groups}` | `GET /api/v1/component-groups` 返回 `{items}`，空仓库显式 `POST /bootstrap` | 已切换；GET 只读，adapter 仅在缺 root 时执行显式幂等 bootstrap |
| 分组搜索 | `POST .../components/search` | `GET /api/v1/.../components/search` | 已切换；query、多状态、分页、总数和状态统计由 Go 查询投影返回 |
| 分组成员 | `GET/PUT/DELETE .../components/:componentId` | GET page；POST collection body；DELETE item | 已切换；adapter 负责 method/body/page unwrap |
| 组件所属分组 | `GET /api/components/:id/groups` | `GET /api/v1/components/:id/groups` | 已切换；owner-scoped membership projection |
| 上传会话 | `POST /api/component-imports/upload-session` | `POST /api/v1/component-imports/upload-sessions` + API 控制的浏览器直传 | 已切换；Go API 生成并持久化 bucket/objectPath，浏览器仅使用当前用户 JWT 向该精确目标直传 Storage；RLS 校验 pending、owner、expiry 和精确 key |
| 上传完成 | `POST /api/component-imports/:sessionId/upload-complete` 返回 rich DTO | `POST /api/v1/component-imports/upload-sessions/:sessionId/complete` 返回 `{importId,taskId,status}` | `202` 后上传弹窗立即退出并进入 Import 状态页；前端不得等待 Worker 或触发 parse/首次 Preview 物化 |
| 导入状态 | `GET /api/component-imports/:importId` | `GET /api/v1/component-imports/:importId` | 已切换；使用 BOM + verified Preview 的聚合 `processing/ready/failed` 投影恢复处理状态 |
| Candidate | 旧 detail 与 import-candidate 两条路由 | `GET /api/v1/component-candidates/:candidateId` | 已切换；ready 结果页默认并发读取 Version BOM 与整体 GLB，relation/connector/interface 由开关按需加载 |
| Candidate 预览 | `POST /api/component-candidates/:id/preview` | 无 Candidate preview；Draft Version 已随 Import 物化 | 前端改用 `draftVersionId` 的 Version preview，不新增 Candidate 同义接口 |
| 关系列表 | `GET .../relations` 返回数组 | `GET /api/v1/.../relations` 返回 `{items}` | adapter unwrap |
| 关系检测 | `POST .../relations/detect` 返回关系数组 | 返回 `202 {taskId,status}` | 轮询 Task 成功后重新读取关系、connector 和 interface |
| 关系确认/拒绝 | 同路径、同步结果 | 同路径 `/api/v1` | 可切换；确认结果是 AssemblyRelation，页面只需完成信号 |
| Connector/Interface | 旧 connector-summary 合并 DTO | `/connectors` 与 `/interfaces` 两个 `{items}` 查询 | 前端并行读取并建立页面 view model |
| 可选版本验证 | `POST .../validate` 返回 ValidationReport | `202 {taskId,status}` + `GET /api/v1/validation-reports/:id` | 已切换；Task 只携带 report ID，前端再读取 durable report；发布不依赖报告 |
| 发布 | `POST .../publish` 同时提交名称、分类、版本和 release note | Draft PATCH + 无 body publish | 已切换；Component 与 owner draft Version 分别保存后执行发布状态迁移 |
| 预览读取 | 旧 `POST .../preview` 可同步物化 | `GET /api/v1/.../preview` 严格只读 | 普通上传只轮询服务端处理链；`ready` 前不挂载 Viewer。显式 POST 仅用于缓存重建/恢复，不是首次上传客户端流程 |
| BOM | 旧 rich `parts` DTO | `GET /api/v1/.../parts` 返回 `{versionId,partCount,items}` | 已切换；item 使用 `ldrawPartNum/quantity/geometryStatus`，`ready/failed/missing` 为机器状态；页面对非 ready Part 标注“缺少预览几何” |
| 源文件下载 | 旧接口直接返回文件 body | `GET /api/v1/.../source` 返回短期签名 `{url,expiresAt}` | 前端先取签名，再下载对象；不把签名 URL 持久化 |
| Version 删除 | 旧接口返回 deletion result | Gin 对 owner draft 返回 `204` | 前端按成功后重新加载处理，不保留旧 componentDeleted DTO |
| Part preview | 已删除 `GET/POST /api/library-items/:type/:id/preview` | `GET /api/v1/part-library-versions/:versionId/parts/:partNum/preview` + 显式 materialize | 已切换；不可变版本资源、Go durable task、Go Worker 真实 LDraw GLB |
| Task | 前端 Component Repo 尚无统一 client | `GET /api/v1/tasks/:taskId`、`POST .../cancel` | 新增通用轮询器，按 task ID 查询；展示使用结构化 code + params |

旧 adapter 中未被页面调用的 `listComponents`、`loadFirstComponentPreview`、同步 multipart
`createComponentImport` 及部分 legacy connector helper 不迁移，直接删除。

## 3. G8.2 已实现的 Go 合约

以下项目已经由 Go 合约承担；继续开发时不得退回前端猜测、N 次请求拼装或旧 FastAPI DTO：

1. **根分组初始化与根视图**
   - GET 保持只读，不能恢复 `EnsureComponentRootGroup` 写入。
   - 提供显式、幂等的 repository/bootstrap mutation，或接入明确的用户 provisioning 写路径。
   - 根视图只表示当前用户拥有的组件；Star 使用独立“我的收藏”，custom Group 继续使用显式 membership。
   - 分组树返回稳定 root、custom groups 和 direct count。

2. **组件库查询投影**
   - 使用 GET query 提供 `groupId/query/status/page/pageSize/locale`。
   - 返回 `items + total + page + pageSize + totalPages + statusCounts`，排序稳定。
   - 状态允许多值过滤；查询仍保持 actor/owner 和 reviewed translation 边界。

3. **组件所属分组投影**
   - 增加 owner-scoped `GET /api/v1/components/:componentId/groups`，只返回 group IDs 或明确 membership DTO。

4. **发布前 Draft 元数据**
   - Component 的名称和分类使用现有 PATCH。
   - 增加只允许 owner draft 的 Version PATCH，用于 version label、revision、release note、releaseNoteLocale；发布接口继续无业务编辑 body。

5. **ValidationReport 读取**
   - 增加 owner/version/candidate 约束的报告 GET；返回既有结构化 checks/issues。
   - Task result 只携带 report ID 和 passed，不把报告全文复制进 Task。

6. **Part 预览所有权（代码、Studio-based 数据基准与 ComponentVersion GLB 已实现）**
   - Goose v8 的 `part_geometries` 和 `part_previews` 分别拥有几何元数据与可重建 Artifact 状态。
   - API 以 `partLibraryVersionId + ldrawPartNum` 定位不可变 Part；GET 只读，POST 创建
     `component.part_preview.materialize` durable task。
   - Go Worker 从只读、版本固定的 `LDRAW_ROOT` 递归生成真实 LDraw GLB；HTTP handler 不做文件解析或网格计算。
   - Component preview 继续使用 Version-addressed GLB，不恢复 first/library/candidate preview 同义路由。
   - active Part Library 已改由 Studio manifest 创建；legacy `public.ldraw_parts` 不再作为
     新版本 membership 基准。

7. **必要列表字段**
   - Component 投影补齐 UI 仍需的 logical size；owner 判断使用 `ownerId`，不依赖旧 `createdBy="auth:..."` 字符串。
   - Group direct count 由查询投影产生。
   - 不为旧 `translationStatus`、version deletion helper、rich preview/BOM DTO 增加兼容字段；前端按新契约重建 view model。

8. **上传处理聚合投影与服务端 continuation**
   - upload complete 的 `202` 只表示 Storage 确认和持久任务编排成功，不表示可预览。
   - Parse 成功后由服务端持久、幂等地调度 Draft Version 的 `component.preview.materialize`；前端不承担首次物化。
   - API 提供可在刷新后恢复的 `processing | ready | failed` 投影；只有 BOM 与 verified Component GLB
     同时可用时才返回 `ready`，不能将 parse task succeeded 直接映射为 ready。

9. **Storage 上传所有权**
   - Go API 生成并持久化 owner-scoped bucket/object key，浏览器不能提交或拼接可信 key。
   - 浏览器只使用当前用户 JWT 向 API 返回的精确目标直传；Storage INSERT RLS 校验 pending
     file/session、owner、expiry 和精确 key。service-role token 不得返回前端。
   - API 只负责会话、可信 metadata、完成确认和任务编排，不接收正文、不解析 Studio/LDraw、
     不计算 BOM/GLB。

## 4. G8.3 前端 adapter 规则

- `appConfig.componentRepoApi` 只保留实际使用的 `/api/v1` 路由模板。
- Component Repo 所有请求继续通过统一 `ApiError(code, params, traceId)` 客户端，不展示 provider、XHR 或 Storage 原始错误。
- 新增一个语言无关 Task poller：终态为 `succeeded/failed/cancelled`；轮询以 `taskId` 为准，
  `taskJobId/executionNumber` 仅用于诊断和界面状态关联。
- Task progress 使用 `tasks:<code>`，Task error 使用 `errors:<code>`；没有 code 时只显示既有通用错误。
- 上传控制面只请求 Go `/api/v1`：创建 session、取得 API 已持久化的精确 Storage 目标、直传正文、
  完成 session。前端不得自行拼接 bucket/objectPath；Storage SDK 只能使用当前用户 JWT，INSERT 由
  pending upload session 精确 key RLS 限制。未配置 Storage 是结构化环境错误，不回退到旧 FastAPI。
- upload complete 返回 `202` 后页面只执行只读状态/BOM/Preview 查询；不得调用 parse 或首次 Preview
  materialize mutation。显式 materialize 只用于用户明确触发的重建/恢复动作；GET 仍不创建任务或对象。
- 上传弹窗的 loading 生命周期只覆盖 session 创建、Storage 直传和 complete；收到 `202` 后必须立即关闭。
  后续轮询只能位于可刷新恢复的 `/component-repo/imports/:importId` 状态页，不能继续锁住上传弹窗。
- 聚合状态不是 `ready` 时不挂载 Viewer、不请求签名预览 URL，也不显示旧或尚未验证的中间模型；页面使用 typed
  semantic key 显示处理状态（中文可渲染为“解析中”，但 TS/TSX 不得硬编码最终译文）。
- Component 列表只展示 `draft/active` 对应的“草稿/已发布”；Import 的 `processing/ready/failed` 不再
  伪装为 Component 状态。全局 `/component-repo/imports` 与 Component 详情 Import Tab 复用 owner-scoped
  持久化历史查询；只有当前页存在 processing 记录且页面可见时才周期刷新。
- `ready` GLB 可以是受控 partial preview：BOM 中 `geometryStatus=failed/missing` 的 Part 仍完整列出并
  标注，GLB 省略对应实例；前端不得把 omissions 隐藏成完整几何。
- Candidate ready 页默认只读取并展示整体 GLB 与 Version BOM，两项独立显示和失败；relation、connector
  和 interface 只有在用户开启连接信息开关后才请求，开关本身不得触发关系检测 mutation。
- Source 下载执行 `GET signed descriptor -> fetch URL/blob`，签名 URL 不写 localStorage、日志或任务 payload。
- 所有 list/page wrapper、connector/interface 合并和新旧页面展示差异只在 adapter/view model 层处理，页面不解析数据库字段。

## 5. G8.4 验收矩阵

切换完成后至少覆盖：

- 未登录请求和失效 Supabase session 使用结构化 auth code；
- 空仓库显式 bootstrap 后可以读取 root，刷新不会新增 root；
- 分组创建、移动、删除、成员增删、搜索、分页和状态统计；
- Component 列表状态只包含草稿/已发布；全局 Import 历史和 Component 关联 Import Tab 的分页、搜索、
  聚合状态、owner 隔离、新建/更新关联与失败本地化；
- 上传 `.io/.ldr/.mpd`、API 控制的浏览器直传 Storage、完成、`202` 后不再发起写请求、上传弹窗立即
  关闭并进入 Import 状态页、verify/parse/preview Task、刷新或关闭页面
  后服务端继续处理、失败可恢复；
- Candidate/Draft 默认只加载 BOM + GLB；网络记录证明开关关闭时无 relation/connector/interface 请求，
  开启后才读取连接投影；关系检测 Task、确认/拒绝和 connector capacity；
- Draft/Published 上显式触发验证、passing/failing report 渲染，以及无报告直接发布；
- Component/Draft 元数据保存后发布；
- Preview GET 零写入；BOM + GLB ready 前 Viewer 未挂载且无预览 URL 请求；缓存丢失可通过显式维护动作重建；
- partial preview 中缺失 Part 在 BOM 明确标注，其他几何正常渲染，单个缺件不导致整体 GLB 失败；
- BOM reviewed translation/source fallback 和 Part preview；
- 短期签名源文件下载；
- owner/cross-owner 404、Task owner 隔离和取消；
- `zh-CN`、`en-US` 下错误、任务进度、状态和用户内容边界。

浏览器或前端网络测试必须证明 Component Repo 流程只请求 `/api/v1`；随后才允许从 FastAPI
application 删除 `create_component_repo_router` 注册和仅服务旧公共 API 的 schema/service。
Parser 与 Relation Worker 均已迁移到 Go；原 Python relation Worker/adapter/launcher 已删除。

## 6. 推荐执行顺序

```text
G8.1 盘点（已完成）
  -> G8.2 Go 合约收口（已完成）
  -> G8.3 前端 adapter + 页面异步流程切换（已完成）
  -> G8.4 双语言浏览器/HTTP/PostgreSQL 验收（核心上传/BOM/partial GLB 已验证，其余矩阵继续）
  -> G8.5 删除旧 FastAPI Component Repo 公共 API
  -> G8.6 `component.relations.detect` Go Worker 迁移与 Python Worker 删除（已完成）
  -> G8.7 Nginx、启动脚本和文档收口
```

当前剩余主项是完成 G8.4 尚未覆盖的授权/双语言/维护场景，并删除旧 FastAPI Component Repo 公共
router。不得因为 legacy router 尚在仓库中，就让新前端或新功能重新依赖它。
