# BrickBuilder 多语言实施路线图

> 更新日期：2026-07-18  
> 架构依据：[I18N_ARCHITECTURE.md](./I18N_ARCHITECTURE.md)

## 1. 状态说明

| 状态 | 含义 |
|---|---|
| ✅ 已完成 | 已实现并通过当前自动化验证 |
| 🚧 进行中 | 已开始但尚未达到验收标准 |
| ⬜ 待开始 | 尚未实施 |
| ⛔ 阻塞 | 存在明确外部依赖或决策阻塞 |

当前总体进度：多语言基础设施、业务迁移、服务端产物及治理体系（M0～M6）已全部完成。

## 2. 里程碑总览

| 里程碑 | 目标 | 状态 | 依赖 |
|---|---|---|---|
| M0 前端基础设施 | 页面、配置、语言切换和格式化 | ✅ 已完成 | 无 |
| M1 前端质量收口 | 统一调用方式、伪语言、视觉回归 | ✅ 已完成 | M0 |
| M2 API 错误契约 | 后端只返回稳定 code + params | ✅ 已完成 | M0 |
| M3 异步任务与验证结果 | 任务、解析、验证不再保存最终译文 | ✅ 已完成 | M2 |
| M4 动态领域内容 | 官方组件/零件内容支持多语言存储 | ✅ 已完成 | M2 |
| M5 导出与服务端产物 | 按任务 locale 生成稳定产物 | ✅ 已完成 | M2、M3 |
| M6 治理与新增语言 | 翻译流程、监控和第三语言验证 | ✅ 已完成 | M1-M5 |

## 3. M0：前端基础设施

目标：所有当前页面展示文案基于当前语言渲染，不保留旧文案兼容层。

| ID | 工作项 | 状态 | 验收结果 |
|---|---|---|---|
| I18N-001 | 引入 i18next、React 集成和浏览器语言检测 | ✅ | `zh-CN`、`en-US` 可切换 |
| I18N-002 | 保存用户语言选择并同步 HTML `lang` | ✅ | 使用 `brickBuilder.locale` |
| I18N-003 | 建立按 locale / namespace 拆分的资源目录 | ✅ | 当前 10 个 namespace（M3 新增 `tasks`） |
| I18N-004 | 配置展示字段改为稳定语义 key | ✅ | 5 组前端配置已迁移 |
| I18N-005 | 建立配置展示字段运行时拦截 | ✅ | 非语义 key 直接报错 |
| I18N-006 | 迁移页面硬编码展示文案 | ✅ | TS/TSX 中文硬编码扫描通过 |
| I18N-007 | 日期和数字绑定当前 locale | ✅ | 当前相关格式化点已接入 |
| I18N-008 | 建立资源完整性测试 | ✅ | 中英文当前各 740 个 key，集合一致 |
| I18N-009 | 生产构建验证 | ✅ | 测试与构建通过 |

完成标准：已满足。

## 4. M1：前端质量收口

目标：让多语言能力具备长期可维护性，并覆盖布局和复杂语言规则。

| ID | 工作项 | 状态 | 依赖 | 验收标准 |
|---|---|---|---|---|
| I18N-101 | 统一 `useAppTranslation` 与非 React 翻译调用规范 | ✅ | M0 | 规范见 `frontend/src/i18n/README.md`，React 与非 React 边界已统一 |
| I18N-102 | 为 key 和插值参数生成 TypeScript 类型 | ✅ | I18N-101 | `i18n:types` 生成，`i18n:check` 检查漂移 |
| I18N-103 | 增加 `en-XA` 伪语言 | ✅ | I18N-101 | 开发环境自动生成且生产构建排除 |
| I18N-104 | 增加关键页面双语言组件测试 | ✅ | I18N-101 | 首页及六个关键业务页面已覆盖 |
| I18N-105 | 增加浏览器视觉回归 | ✅ | I18N-103 | 1280px 与 390px 实机验证；修复移动端登录按钮越界 |
| I18N-106 | 建立复数、插值、相对时间测试 | ✅ | I18N-102 | `languageRules.test.ts` 覆盖语言规则和格式化 |
| I18N-107 | 评估 namespace 懒加载 | ✅ | I18N-104 | 结论为继续 eager load，指标见 `frontend/src/i18n/PERFORMANCE.md` |

M1 完成标准：已满足。

- 关键页面双语言自动化覆盖。
- 伪语言下无严重布局问题。
- 新增或删除 key 会触发类型或 CI 错误。

## 5. M2：API 错误契约

目标：API 不再把英文异常文本当作用户界面协议。

| ID | 工作项 | 状态 | 依赖 | 验收标准 |
|---|---|---|---|---|
| I18N-201 | 定义 `DomainError(code, params, http_status)` | ✅ | M0 | `backend/src/api/errors.py` 已实现结构化领域错误 |
| I18N-202 | 定义统一错误响应 Pydantic schema | ✅ | I18N-201 | OpenAPI 为 400～502 公共错误展示统一 schema |
| I18N-203 | 增加 FastAPI 全局异常处理器和 traceId | ✅ | I18N-202 | 响应体与 `X-Trace-Id` 一致，未知异常统一脱敏 |
| I18N-204 | 规范化 Pydantic 请求校验错误 | ✅ | I18N-203 | 422 返回字段 path、稳定 code 和安全 params |
| I18N-205 | 将后端配置 `errors` 从句子改为 code | ✅ | I18N-201 | 公共及嵌套错误配置均已改为机器 code |
| I18N-206 | 迁移 auth 路由和鉴权错误 | ✅ | I18N-203 | 后端鉴权与 Supabase 前端错误均不展示原始英文文本 |
| I18N-207 | 迁移 pixel-art、terrain、model-assets、mesh API | ✅ | I18N-203 | 公共响应不再返回 `str(error)` |
| I18N-208 | 迁移 lego-design、DEM design、model-fitting API | ✅ | I18N-203 | 同步业务错误均为 code + params |
| I18N-209 | 迁移 component-repo、part-search API | ✅ | I18N-203 | 全部公共错误经统一处理器输出 |
| I18N-210 | 建立前端统一 API client / `ApiError` | ✅ | I18N-202 | API 模块不再解析 `detail`、原始 text 或 statusText |
| I18N-211 | 新增 `errors` namespace 和错误资源 | ✅ | I18N-205 | 中英文各 203 个错误资源，支持当前语言延迟解析 |
| I18N-212 | 增加 API 契约与错误资源覆盖测试 | ✅ | I18N-206~211 | 后端契约、资源覆盖和前端客户端测试均已加入 |

建议实施顺序：201 → 202 → 203 → 210/211 → 206~209 → 204/205/212。

M2 完成标准：已满足。

- `rg "detail=str\(error\)|detail=\"" backend/src/api` 不再发现公共用户错误。
- 前端 API 模块不直接向 UI 抛出响应原文。
- OpenAPI 中所有业务错误符合统一 schema。

## 6. M3：异步任务、解析与验证结果

目标：持久化结构化错误和 issue，任务进度可按当前语言显示。

| ID | 工作项 | 状态 | 依赖 | 验收标准 |
|---|---|---|---|---|
| I18N-301 | 任务进度改为 `{percent, code, params}` | ✅ | M2 | Terrain/LEGO 轮询响应由前端 `tasks` namespace 本地翻译 |
| I18N-302 | `error_message` 改为 `error_code + error_params_json` | ✅ | M2 | 模型拟合任务只保存机器 code 与参数 |
| I18N-303 | `parse_error`、`resolve_error`、`expand_error` 结构化 | ✅ | M2 | LDraw/Shadow 解析、引用解析和展开错误已拆为 code + params |
| I18N-304 | `profile_error` 和几何错误结构化 | ✅ | M2 | 零件、候选轮廓及 DEM 坡度目录不保存原始异常文案 |
| I18N-305 | 组件验证 issue 统一 schema | ✅ | M2 | parse issue 与 validation issue/check 均使用 code、severity/status、params、path |
| I18N-306 | DEM/LEGO 设计失败结果结构化 | ✅ | M2 | Terrain/LEGO job error 使用结构化 message，前端按当前语言渲染 |
| I18N-307 | 增加任务 locale 和 timezone 字段 | ✅ | M2 | 创建任务时规范化并冻结 locale/timezone，模型拟合任务持久化 |
| I18N-308 | 增加任务错误与进度端到端测试 | ✅ | I18N-301~307 | 中英文使用同一数据对象并得到不同本地化展示，持久化列契约受测试保护 |

M3 完成标准：已满足。数据库和公共任务响应只保存或返回机器 code、参数及任务语言上下文，不保存或返回最终用户译文。

## 7. M4：动态领域内容

目标：官方维护的组件和零件可按 locale 查询；用户内容保持原文。

| ID | 工作项 | 状态 | 依赖 | 验收标准 |
|---|---|---|---|---|
| I18N-401 | 对领域字段进行“机器/用户/官方内容”分类 | ✅ | M2 | `I18N_FIELD_CLASSIFICATION.md` 明确字段边界和展示规则 |
| I18N-402 | 设计 `component_translations` 表 | ✅ | I18N-401 | `(component_id, locale)` 唯一，独立审核状态与审计字段 |
| I18N-403 | 设计 `part_translations` 表 | ✅ | I18N-401 | `(ldraw_part_id, locale)` 唯一，源内容不随语言扩列 |
| I18N-404 | API 增加 `contentLocale` 和 locale 查询逻辑 | ✅ | I18N-402/403 | 组件查询与零件搜索显式传入请求语言并返回实际内容语言 |
| I18N-405 | 用户内容增加 `contentLocale` 元数据 | ✅ | I18N-401 | Component、PixelArtProject、ModelAsset 写入时必须记录原文语言，不自动翻译 |
| I18N-406 | 建立术语表和翻译审核状态 | ✅ | I18N-402/403 | `i18n_glossary.json`；仅 `reviewed` 翻译参与查询 |
| I18N-407 | 增加缺失官方翻译的可观测指标 | ✅ | I18N-404 | `/api/i18n/metrics` 可按实体、请求 locale 和回退 locale 统计命中 |

M4 完成标准：已满足。新增语言只增加翻译记录，不增加实体主表语言字段；官方内容与用户原文边界由模型和测试共同约束。

## 8. M5：导出与服务端生成内容

目标：异步导出和下载文件具有确定、可复现的语言。

| ID | 工作项 | 状态 | 依赖 | 验收标准 |
|---|---|---|---|---|
| I18N-501 | 导出请求接受规范化 locale | ✅ | M2、M3 | LEGO job 与 DEM 设计创建时冻结规范化 locale/timezone |
| I18N-502 | 导出标题、说明和字段名使用服务端资源 | ✅ | I18N-501 | LDraw、设计计划和 DEM 报告由 `export_resources` 中英文资源渲染 |
| I18N-503 | 记录 translation catalog version | ✅ | I18N-502 | `catalogVersion` 写入 job/DEM `exportContext` 和产物元数据 |
| I18N-504 | 文件名使用 locale 安全模板 | ✅ | I18N-501 | 参数清洗并输出 ASCII fallback + RFC 5987 `filename*` |
| I18N-505 | 导出快照测试 | ✅ | I18N-502 | `test_export_i18n.py` 覆盖 BOM、设计图、DEM 报告与版本拒绝 |

M5 完成标准：已满足。异步导出只读取任务冻结上下文；DEM 产物读取设计生成时冻结的 `exportContext`，不读取下载时的浏览器语言。JSON 机器字段保持稳定，仅本地化文档元数据、章节/字段标签与步骤名称。

## 9. M6：治理、监控和新增语言

目标：形成稳定的新增文案与新增语言流程。

| ID | 工作项 | 状态 | 依赖 | 验收标准 |
|---|---|---|---|---|
| I18N-601 | 建立术语表、风格指南和翻译负责人 | ✅ | M1、M4 | `I18N_GOVERNANCE.md`、所有者登记和 PR checklist 已建立 |
| I18N-602 | CI 增加插值参数与无效 HTML 检查 | ✅ | M1 | 动态检查 locale/key/参数集合、语义 key、HTML 与 content hash |
| I18N-603 | 监控未知 key、未知 API code、locale 回退 | ✅ | M2、M4 | `/api/i18n/metrics` 提供总量/小时趋势，Dashboard 展示健康度 |
| I18N-604 | 建立翻译资源版本与发布说明 | ✅ | M5 | catalog SHA-256、不可复用版本及 `I18N_RELEASE_NOTES.md` |
| I18N-605 | 选择第三种语言做扩展验证 | ✅ | M1-M5 | `ja-JP` 验证通过；资源加载和 locale resolver 均为 catalog 驱动 |
| I18N-606 | RTL 技术评估 | ✅ | I18N-605 | HTML `dir` 已由 catalog 决定，风险和上线清单已形成 |

M6 完成标准：已满足。未审核语言不会进入生产 catalog；资源漂移会在 CI 失败；未知翻译事件具备有界采集、小时趋势和 Dashboard 展示。

## 10. 建议迭代安排

以下是依赖顺序，不是固定日期承诺：

| 迭代 | 建议范围 | 主要产出 |
|---|---|---|
| Iteration A | M1 + I18N-201~204 | 前端质量门禁、统一错误基础设施 |
| Iteration B | I18N-205~212 | 所有 API 错误迁移完成 |
| Iteration C | M3 | 异步任务和验证结果结构化 |
| Iteration D | M4 | 官方动态内容翻译模型 |
| Iteration E | M5 + M6 基础项 | 导出、监控、协作治理 |

每个迭代结束必须运行：

```bash
cd frontend
npm test
npm run build

cd ../backend
python -m pytest
```

同时执行多语言静态检查和关键页面双语言验收。

## 11. 风险与控制措施

| 风险 | 影响 | 控制措施 |
|---|---|---|
| key 语义不稳定 | 文案重复和维护成本增加 | namespace 所有者评审，禁止原文 key |
| 后端泄露内部异常 | 安全和体验问题 | 全局异常处理器、未知错误统一 code |
| 状态值被误翻译 | 业务判断失效 | 机器值与展示映射分层、契约测试 |
| 异步任务语言漂移 | 导出结果不可复现 | 创建任务时冻结 locale 和 catalog version |
| 用户内容被错误翻译 | 数据语义被改变 | 用户内容默认原样保存 |
| 长英文造成布局溢出 | 页面不可用 | 伪语言与视觉回归 |
| 翻译资源持续增大 | 首屏性能下降 | 达到阈值后 namespace 懒加载 |

## 12. 进度更新规则

- 完成工作项时，将状态改为 `✅ 已完成`，并在验收列补充测试或提交证据。
- 工作项开始时标记 `🚧 进行中`，不要同时开启过多跨里程碑任务。
- 阻塞时标记 `⛔ 阻塞`，写明依赖的决策、数据或外部系统。
- 新发现的工作项使用所属里程碑的下一个编号，避免复用 ID。
- 架构发生变化时先更新设计文档，再调整路线图和实现。
