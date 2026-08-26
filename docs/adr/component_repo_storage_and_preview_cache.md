# ADR: Component Repo Storage 与预览缓存边界

日期：2026-07-23；2026-08-03 修订；2026-08-23 上传控制面与异步链修订

## 状态

Accepted

## 背景

Component Repo 同时处理三类性质不同的数据：

1. 用户上传的 `.io/.ldr/.mpd` 原始文件；
2. 解析后写入 PostgreSQL 的场景快照、候选组件和版本；
3. 根据场景快照和 Part Library 生成的 GLB/meshopt 预览缓存。

原始上传链路采用 Supabase publishable key、用户 JWT 和 userId-first Storage 路径。2026-08-23
确认保留 API 控制的浏览器直传：API 生成并持久化精确 key，Storage RLS 校验该 key 对应仍有效的
pending upload session；浏览器只承担正文数据传输。初版 GLB 缓存绕过了原链路：预览路由没有传播
用户 JWT，路径也没有用户 ID，同时把 GLB 放进了用户上传类型白名单。
结果是 Storage RLS 拒绝写入，并被 API 映射成 502。

## 代码框架

```text
frontend/src/componentRepo/
├── componentRepoApi.ts
│   ├── 创建 upload session
│   ├── 使用 Supabase SDK + 用户 JWT 直传源文件
│   ├── 提交 parse 命令
│   └── 使用 POST 幂等生成预览缓存，加载签名 GLB URL
└── 页面组件

backend/src/api/routes/component_repo.py
├── HTTP 契约与鉴权上下文
├── code + params 错误映射
├── 应用流程编排
└── 将 CurrentUser 传入 Storage 和缓存服务

backend/src/component_repo/services.py
├── upload session
├── HEAD/object-info 完成校验
├── 源文件单次下载、SHA-256 校验和解析
└── 原始/交换制品元数据

backend/src/component_repo/component_service.py
├── Candidate / ComponentVersion
├── 场景快照与官方内容选择
└── locale-neutral 预览装配数据

backend/src/component_repo/preview_model_service.py
├── ComponentVersion -> GLB artifact 直接关联
├── version-addressed artifact ID / Storage key
├── GLB/meshopt 生成
├── generatorVersion 失效检查
└── 已关联模型签名 URL

backend/src/component_repo/storage.py
├── ArtifactStorage port
├── Supabase REST adapter
└── Local adapter（仅测试和离线开发）
```

## 核心决策

### 1. 认证和 Storage 权限

- 浏览器直传和用户作用域 HEAD/签名使用 Supabase publishable key + 当前用户 JWT。
- Go Worker 的服务端对象读取、派生写入、失败补偿和过期清理必须使用 server-only service-role/secret；
  该凭据不得进入浏览器、数据库、task payload 或日志。
- `apikey` header 使用 publishable key。
- `Authorization` header 必须使用当前请求的用户 JWT。
- API 路由负责解析 `CurrentUser`；Storage adapter 只接收已经验证的 token。
- 用户作用域的 Storage 读写不得把 publishable key 当作用户 Bearer token。
- 后端代表用户执行 Storage 操作时，必须显式传播同一个 JWT。

### 2. 对象路径

所有用户私有对象都使用以下前缀：

```text
{auth.uid()}/component-repo/...
```

当前路径分类：

```text
{userId}/component-repo/uploads/{uploadSessionId}/{role}/{artifactId}.{ext}
{userId}/component-repo/previews/{versionId}/{generatorVersion}/{artifactId}.glb
```

服务端不得接受客户端提交的完整 Storage 路径。路径由后端根据已验证的
用户 ID、机器类型和服务端 ID 构造。

现有数据库仍有少量 `component-repo/...` 历史对象。迁移期只保留 legacy
SELECT policy，且必须通过 `component_artifacts.uploaded_by` 验证
`auth:{current_user}` ownership；禁止继续向旧路径 INSERT。历史对象迁移到
owner 路径后必须删除该兼容函数和读取策略。

### 3. 源制品与派生制品

`allowed_types` 只表示用户可上传并可作为 ComponentVersion 来源的类型：

```text
studio_io
ldraw_ldr
ldraw_mpd
```

GLB 是内部派生缓存，属于 `derived_types`：

```text
component_preview_glb
```

派生类型不得出现在上传控件、源格式选择、发布源制品校验或用户组件类型中。
缓存丢失可以重建，源制品丢失不能用缓存替代。

### 4. 上传与解析数据流

```text
POST upload-session
  -> API 生成并持久化 session/file ID 与精确 userId-first Storage key
  -> 后端返回该会话的 bucket/objectPath
  -> 前端使用当前用户 JWT 直传；INSERT RLS 复核 pending session/owner/expiry/精确 key
  -> POST upload-complete
  -> API 使用用户 JWT HEAD 确认 metadata 并建立 durable task chain，返回 202
  -> Verify Worker 流式读取并校验 SHA-256
  -> Parse Worker 解析同一不可变 Artifact
  -> 同一事务写入场景快照/BOM/Candidate/Draft，并创建 Preview Task 与 Parse dependency
  -> Parse succeeded 后 Preview Worker 生成 GLB
  -> 写入 preview_artifact_id 与 generatorVersion
  -> Import processingStatus=ready
```

Backend API 上传 handler 负责认证、授权、大小限制、可信 key 分配和上传 metadata；不接收或缓存整个
文件，不解析 Studio/LDraw，不计算 BOM/GLB。SHA-256 的权威验证由 Verify Worker 完成。浏览器只使用
自身 JWT，不持有服务端 Storage 凭据，也不能自行拼接可写路径。

### 5. HTTP 语义

- `GET .../preview` 只按 `version_id -> preview_artifact_id` 读取模型状态并创建签名 URL，不写数据库或 Storage。
- `POST .../preview` 是幂等的 materialize 命令；版本没有有效 artifact 时生成，存在时直接复用。
- 新解析在业务事务中持久创建首个 Preview Task；前端不负责预热缓存。
- 旧版本可以通过 POST 补建关联；独立 Part 和未绑定 Candidate 仍使用内容派生的临时预览路径。
- 版本预览接口只返回模型状态和签名 GLB URL，不返回场景或 mesh JSON。
- locale-aware 零件清单通过独立版本 BOM 接口并行加载，不阻塞 GLB。

状态改变不能隐藏在 GET 中。以后新增其他派生资产也应使用显式命令、任务或
发布阶段生成。

### 6. 一致性边界

- PostgreSQL 场景快照是组件结构的权威数据。
- Supabase Storage 中的 GLB 是可重建缓存。
- 缓存失败不得删除或伪造已成功解析的场景快照。
- ComponentVersion 使用 `preview_artifact_id` 直接关联当前 GLB，不得为了查找缓存先读取场景、零件或 mesh。
- 查找身份是 `version_id`；`generatorVersion` 只负责判断关联 artifact 是否过期，不参与运行时内容 hash。
- artifact ID 对同一 `version_id + generatorVersion` 保持确定性，Storage key 保留创建者 owner scope。
- 组件所有者和订阅者通过受限 Storage RLS 函数读取版本关联的 GLB；源文件 owner-only 策略不放宽。
- 对同一版本的 materialize 必须保持幂等。

### 7. API 与国际化

- API 错误始终返回稳定 `code + params + traceId`。
- Storage provider、bucket、object path、artifact type、version ID、生成状态、SHA-256
  都是机器字段，不翻译。
- Component/Part 名称继续遵循现有 `contentLocale` 与 reviewed translation 规则。
- 不向客户端返回 Storage SDK 原始错误、SQL、路径异常或堆栈。

### 8. Schema 与启动边界

- 正式数据库的表、索引、RLS 和回填必须通过版本化 migration 管理。
- API 进程启动不得执行生产 DDL、全表扫描或数据回填。
- `ensure_*_table` 只保留给 SQLite 测试和明确的离线开发流程。
- migration 应在部署阶段独立执行；失败时阻止新版本启动，而不是让首个 API
  进程承担迁移。
- 数据库 schema 生命周期由 `database_schema_lifecycle.md` 统一约束。
- 已配置数据库已按完整 ORM 契约审计，并在新增组件分组关系后升级至
  `20260725_0015`；API 启动只校验 revision，不再执行 `ensure_*`、DDL 或回填。
- ComponentVersion 预览关联由 migration `20260803_0021` 管理；历史版本首次 POST 时补建。
- 当前还有 8 个 legacy Storage 对象需要迁移到 owner 路径；迁移完成后删除
  `component artifacts legacy owner select` policy。

## 禁止的实现方式

- 在用户请求链路中要求或暗中依赖 service-role key；
- 丢弃已经到达 API 的 JWT，再用 publishable key 充当 Bearer token；
- 创建不以用户 ID 开头、却依赖 owner-only RLS 的对象路径；
- 把缓存格式加入用户上传类型白名单；
- 在 GET 中首次生成并写入派生文件；
- 为判断版本 GLB 是否存在而读取完整场景、组装 mesh 或计算内容 cache key；
- 为 HEAD、hash 和 parse 分别下载同一个源对象；
- 用 local provider 掩盖正式 Supabase 鉴权错误；
- 在已配置 Supabase 的环境中静默回退到旧 multipart 路径，从而掩盖 RLS 错误；
- 让前端自行拼接可信 Storage 路径。
- 仅按 `{auth.uid()}/component-repo/**` 前缀允许 INSERT，而不校验 API 已登记的 pending session 精确 key；
- 让 authenticated 客户端删除已完成或已关联 Artifact 的对象。

## 新增 Storage/派生资产功能检查清单

每个新功能合入前必须回答：

1. 这是权威源数据，还是可重建派生数据？
2. 谁拥有对象，owner ID 从哪个已验证身份取得？
3. 路径是否满足现有 RLS，是否有自动测试？
4. publishable key 和用户 JWT 是否分别放在正确 header？
5. HTTP 方法是否准确表达读操作或状态改变？
6. 缓存丢失、重复请求和部分失败时能否安全重试？
7. 是否避免重复下载和重复 hash？
8. 类型是否进入了正确的 source/derived 分类？
9. API 错误是否仍为稳定 `code + params`？
10. 是否覆盖 Local 测试和真实 Supabase JWT 两种 adapter 行为？
11. schema/RLS 变化是否有 migration，且没有进入 API startup 热路径？

## 后续演进

- 已发布组件的跨用户预览通过版本 artifact 关系和订阅/管理权限读取策略完成；
  不得通过放宽私有源文件的 owner-only RLS 来实现。
- GLB materialize 已是可观察、可重试的持久派生任务；后续缓存重建继续复用同一 Logical Job、input hash
  和 owner/path 规则。
- 如果派生资产种类继续增加，应引入专门的 derived artifact/cache repository，
  避免源制品表承担所有生命周期语义。
