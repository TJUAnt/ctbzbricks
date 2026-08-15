# G8 Component Repo 前端切换清单

> 状态：G8.1 inventory completed；G8.2/G8.3 Part preview code cutover completed；运行数据交接待执行  
> 日期：2026-08-14  
> 目标：前端直接切换到 Gin `/api/v1`，随后删除旧 FastAPI Component Repo 公共路由  
> 原则：[go_backend_migration_principles.md](./go_backend_migration_principles.md)  
> 路线：[go_component_migration_plan.md](./go_component_migration_plan.md)

## 1. 盘点结论

前端的 Component Repo 请求集中在
`frontend/src/componentRepo/componentRepoApi.ts`，由 Component Repo 四个页面和
`PartViewerPage` 使用。当前配置仍全部指向旧 `/api`，DTO 和交互也仍按 FastAPI 契约编写。

Gin 已覆盖主要领域能力，但切换不是路径前缀替换：列表分页、分组根视图、上传完成、任务轮询、
关系检测、发布校验、预览物化、下载和若干 DTO 都已经采用新的目标契约。G8 必须先收口少量
Go API 缺口，再重写单一前端 adapter；不增加兼容代理、旧 DTO wrapper 或双路请求。

2026-08-12 已切换能够在同一 Go 数据域独立闭环的能力：Component/Version 读取、上传、
Import/Task/Candidate、关系审核、connector/interface、发布校验、Component 元数据与发布、预览、
BOM、源文件下载、draft 删除、分组库查询/管理、Draft Version 元数据和 ValidationReport 读取。
2026-08-14 已删除旧 Part/Library preview 路由。Part viewer 使用冻结的
`partLibraryVersionId + ldrawPartNum`，同一个业务动作不会同时请求两套后端。真实开发环境仍需先应用
Goose v8 并执行显式 Part 数据交接，代码切换不等同于环境已可运行。

## 2. 当前使用面

| 前端流程 | 当前旧接口 | Gin 目标 | 结论 |
|---|---|---|---|
| 组件详情 | `GET /api/components/:id` | `GET /api/v1/components/:id` | 可切换；query 改为 `locale`，DTO 改用 `ownerId/subscribed/translationMissing` |
| 版本列表/详情 | `GET /api/components/:id/versions`、`GET /api/component-versions/:id` | 同资源的 `/api/v1` 版本 | 可切换；响应从数组改为 page object，`componentCandidateId` 可为空 |
| 分组树 | `GET /api/component-groups` 返回 `{root,groups}` | `GET /api/v1/component-groups` 返回 `{items}`，空仓库显式 `POST /bootstrap` | 已切换；GET 只读，adapter 仅在缺 root 时执行显式幂等 bootstrap |
| 分组搜索 | `POST .../components/search` | `GET /api/v1/.../components/search` | 已切换；query、多状态、分页、总数和状态统计由 Go 查询投影返回 |
| 分组成员 | `GET/PUT/DELETE .../components/:componentId` | GET page；POST collection body；DELETE item | 已切换；adapter 负责 method/body/page unwrap |
| 组件所属分组 | `GET /api/components/:id/groups` | `GET /api/v1/components/:id/groups` | 已切换；owner-scoped membership projection |
| 上传会话 | `POST /api/component-imports/upload-session` | `POST /api/v1/component-imports/upload-sessions` | 可直接切换路径；请求文件 spec 基本一致 |
| 上传完成 | `POST /api/component-imports/:sessionId/upload-complete` 返回 rich DTO | `POST /api/v1/component-imports/upload-sessions/:sessionId/complete` 返回 `{importId,taskId,status}` | 前端改为 Accepted Task 流程 |
| 导入状态 | `GET /api/component-imports/:importId` | `GET /api/v1/component-imports/:importId` | 可切换；使用 `taskId/candidateId/draftVersionId/failure`，不再解析 legacy metadata.processing |
| Candidate | 旧 detail 与 import-candidate 两条路由 | `GET /api/v1/component-candidates/:candidateId` | 使用 Import 返回的 `candidateId`；删除 import-candidate 适配 |
| Candidate 预览 | `POST /api/component-candidates/:id/preview` | 无 Candidate preview；Draft Version 已随 Import 物化 | 前端改用 `draftVersionId` 的 Version preview，不新增 Candidate 同义接口 |
| 关系列表 | `GET .../relations` 返回数组 | `GET /api/v1/.../relations` 返回 `{items}` | adapter unwrap |
| 关系检测 | `POST .../relations/detect` 返回关系数组 | 返回 `202 {taskId,status}` | 轮询 Task 成功后重新读取关系、connector 和 interface |
| 关系确认/拒绝 | 同路径、同步结果 | 同路径 `/api/v1` | 可切换；确认结果是 AssemblyRelation，页面只需完成信号 |
| Connector/Interface | 旧 connector-summary 合并 DTO | `/connectors` 与 `/interfaces` 两个 `{items}` 查询 | 前端并行读取并建立页面 view model |
| 发布校验 | `POST .../validate` 返回 ValidationReport | `202 {taskId,status}` + `GET /api/v1/validation-reports/:id` | 已切换；Task 只携带 report ID，前端再读取 durable report |
| 发布 | `POST .../publish` 同时提交名称、分类、版本和 release note | Draft PATCH + 无 body publish | 已切换；Component 与 owner draft Version 分别保存后执行发布状态迁移 |
| 预览读取 | 旧 `POST .../preview` 可同步物化 | `GET /api/v1/.../preview` 严格只读 | pending/failed 时显式 POST `/preview/materialize`，轮询 Task 后重新 GET |
| BOM | 旧 rich `parts` DTO | `GET /api/v1/.../parts` 返回 `{versionId,partCount,items}` | adapter 改为 `ldrawPartNum`；不得伪造 Go 未提供的 availability/image URL |
| 源文件下载 | 旧接口直接返回文件 body | `GET /api/v1/.../source` 返回短期签名 `{url,expiresAt}` | 前端先取签名，再下载对象；不把签名 URL 持久化 |
| Version 删除 | 旧接口返回 deletion result | Gin 对 owner draft 返回 `204` | 前端按成功后重新加载处理，不保留旧 componentDeleted DTO |
| Part preview | 已删除 `GET/POST /api/library-items/:type/:id/preview` | `GET /api/v1/part-library-versions/:versionId/parts/:partNum/preview` + 显式 materialize | 已切换；不可变版本资源、Go durable task、Go Worker 真实 LDraw GLB |
| Task | 前端 Component Repo 尚无统一 client | `GET /api/v1/tasks/:taskId`、`POST .../cancel` | 新增通用轮询器，按 task ID 查询；展示使用结构化 code + params |

旧 adapter 中未被页面调用的 `listComponents`、`loadFirstComponentPreview`、同步 multipart
`createComponentImport` 及部分 legacy connector helper 不迁移，直接删除。

## 3. G8.2 必须先完成的 Go 合约

以下项目不应通过前端猜测、N 次请求拼装或恢复旧 FastAPI DTO 解决：

1. **根分组初始化与根视图**
   - GET 保持只读，不能恢复 `EnsureComponentRootGroup` 写入。
   - 提供显式、幂等的 repository/bootstrap mutation，或接入明确的用户 provisioning 写路径。
   - 根视图表示当前用户可管理/订阅的组件全集；不能要求每个组件复制一条 root membership。
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

6. **Part 预览所有权（代码已完成，环境交接待执行）**
   - Goose v8 的 `part_geometries` 和 `part_previews` 分别拥有几何元数据与可重建 Artifact 状态。
   - API 以 `partLibraryVersionId + ldrawPartNum` 定位不可变 Part；GET 只读，POST 创建
     `component.part_preview.materialize` durable task。
   - Go Worker 从只读、版本固定的 `LDRAW_ROOT` 递归生成真实 LDraw GLB；HTTP handler 不做文件解析或网格计算。
   - Component preview 继续使用 Version-addressed GLB，不恢复 first/library/candidate preview 同义路由。

7. **必要列表字段**
   - Component 投影补齐 UI 仍需的 logical size；owner 判断使用 `ownerId`，不依赖旧 `createdBy="auth:..."` 字符串。
   - Group direct count 由查询投影产生。
   - 不为旧 `translationStatus`、version deletion helper、rich preview/BOM DTO 增加兼容字段；前端按新契约重建 view model。

## 4. G8.3 前端 adapter 规则

- `appConfig.componentRepoApi` 只保留实际使用的 `/api/v1` 路由模板。
- Component Repo 所有请求继续通过统一 `ApiError(code, params, traceId)` 客户端，不展示 provider、XHR 或 Storage 原始错误。
- 新增一个语言无关 Task poller：终态为 `succeeded/failed/cancelled`；轮询以 `taskId` 为准，
  `taskJobId/executionNumber` 仅用于诊断和界面状态关联。
- Task progress 使用 `tasks:<code>`，Task error 使用 `errors:<code>`；没有 code 时只显示既有通用错误。
- 上传只保留 Supabase 直传会话流程。未配置 Storage/Auth 是环境错误，不回退到旧 multipart FastAPI 上传。
- Preview 执行 `GET -> explicit materialize -> task poll -> GET`；GET 不创建任务或对象。
- Source 下载执行 `GET signed descriptor -> fetch URL/blob`，签名 URL 不写 localStorage、日志或任务 payload。
- 所有 list/page wrapper、connector/interface 合并和新旧页面展示差异只在 adapter/view model 层处理，页面不解析数据库字段。

## 5. G8.4 验收矩阵

切换完成后至少覆盖：

- 未登录请求和失效 Supabase session 使用结构化 auth code；
- 空仓库显式 bootstrap 后可以读取 root，刷新不会新增 root；
- 分组创建、移动、删除、成员增删、搜索、分页和状态统计；
- 上传 `.io/.ldr/.mpd`、直传、完成、verify/parse Task、刷新后继续轮询、失败重提；
- Candidate/Draft 加载、关系检测 Task、确认/拒绝和 connector capacity；
- 发布校验 Task 的 passing/failing report 渲染，以及 validation gate；
- Component/Draft 元数据保存后发布；
- Preview GET 零写入、显式物化、缓存丢失重建；
- BOM reviewed translation/source fallback 和 Part preview；
- 短期签名源文件下载；
- owner/cross-owner 404、Task owner 隔离和取消；
- `zh-CN`、`en-US` 下错误、任务进度、状态和用户内容边界。

浏览器或前端网络测试必须证明 Component Repo 流程只请求 `/api/v1`；随后才允许从 FastAPI
application 删除 `create_component_repo_router` 注册和仅服务旧公共 API 的 schema/service。
Parser Worker、Relation Worker 及其实际依赖的算法模块保留。

## 6. 推荐执行顺序

```text
G8.1 盘点（已完成）
  -> G8.2 Go 合约收口
  -> G8.3 前端 adapter + 页面异步流程切换
  -> G8.4 双语言浏览器/HTTP/PostgreSQL 验收
  -> G8.5 删除旧 FastAPI Component Repo 公共 API
  -> G8.6 Nginx、启动脚本和文档收口
```

G8.2 应先完成根视图、查询投影、Draft PATCH、ValidationReport GET 和 Part preview 决策；
否则前端会被迫实现临时兼容逻辑，之后还需再次迁移。
