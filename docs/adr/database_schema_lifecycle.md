# ADR: Database Schema 生命周期

日期：2026-07-25

## 状态

Accepted

## 背景

历史上 FastAPI 在模块导入时调用多个 `ensure_*` 函数。每个进程启动都会
通过远程数据库检查表和列，部分 helper 还会执行 `ALTER TABLE`、创建索引或
全表回填。结果是：

- API 启动时间取决于生产数据库的 DDL 和扫描耗时；
- 多个 worker 可能并发执行 schema 变更；
- 代码版本与数据库版本没有一个可审计的对应关系；
- 本地存在的 Alembic revisions 被 `.gitignore` 忽略，部署无法复现；
- 模型已增加字段、生产表却没有对应 migration 时，只会在业务写入时报
  `UndefinedColumn`。

## 决策

### 1. Schema authority

生产数据库的表、列、索引、约束、RLS、函数和数据回填只由版本化 Alembic
migration 管理。revision 文件必须进入版本控制，按单一线性 head 发布。

`backend/src/model/models.py` 是运行时 ORM 契约，但不能替代 migration。
修改持久化模型时，同一个变更必须包含 migration 和 schema contract 测试。

### 2. 部署顺序

```text
备份/恢复点
  -> alembic upgrade head
  -> schema 只读审计
  -> 启动新 API 版本
  -> smoke test
```

仓库提供独立入口：

```bash
scripts/migrate-backend.sh
scripts/start-backend.sh
```

Windows 使用对应的 `.ps1`。`start-backend` 不会隐式调用 migration。

部署阶段 migration 失败时不得启动新 API。API 进程不获得“自动修表”的
职责，也不以吞掉 schema 错误的方式继续服务。

已存在但没有 `alembic_version` 的数据库必须先执行只读 schema 审计；只有
确认表、列、索引和安全策略与目标 revision 一致后，才能执行一次性 stamp。
禁止仅根据文件名或日期猜测 revision。

### 3. API startup

API 启动只读取 `alembic_version`，并要求它严格等于本代码声明的单一
`EXPECTED_DATABASE_REVISION`。不一致时进程 fail fast，内部日志记录稳定的
机器状态：

```text
database.schema_revision_unavailable
database.schema_revision_mismatch
```

这些是运维诊断，不通过公共 API 返回，也不进入前端翻译资源。

### 4. 测试与离线开发

`ensure_*_table` 和 SQLAlchemy `create_all` 只允许用于：

- SQLite 单元测试；
- 明确执行的离线开发初始化；
- 一次性数据导入工具。

它们不得从 `src.api.main`、请求路由或后台任务入口调用。离线初始化只创建
开发所需结构，不能冒充已执行生产 RLS/函数 migration，也不能自动 stamp
生产 revision。

### 5. Migration 内容规则

- DDL 与回填在同一 revision 中必须可审计、可重试，并尽量缩短锁时间。
- 大表回填分批执行或拆成独立部署步骤，不放进 API startup。
- 历史异常正文只用于离线判断，不复制到公共 `params`；持久化错误仍为
  `code + params`。
- 用户内容迁移必须保留原文，并补充 `content_locale`，不得机器翻译。
- 任务记录必须冻结规范化 `locale/timezone`。
- Supabase `storage` schema 专属 migration 必须先检测目标对象是否存在，
  以便普通 PostgreSQL 和 SQLite 环境安全跳过。
- downgrade 不得被当作生产数据恢复方案；破坏性回滚前必须使用备份。

## 本次 baseline

`20260725_0014` 补齐了现库与 ORM 间最后一组已知漂移：

- LDraw 文件、引用及 Shadow 表的结构化错误列；
- `pixel_art_projects.content_locale`；
- `model_fitting_jobs.locale/timezone/error_code/error_params_json`。

现有 34 个 Pixel Art 项目按当时产品默认语言记录为 `zh-CN`；内容本身保持
原样。现库没有 Model Fitting Job，因此任务上下文列无需猜测历史值。
LDraw reference 的两条历史失败使用稳定
`ldraw.reference_not_found + {reference}` 重建，不保存原始异常正文。

`20260725_0015` 新增个人组件仓库的分组树、组件多分组关系和订阅关系表，
并为这三张只允许后端访问的表启用 RLS、撤销浏览器角色的直接表权限。

## 后续变更检查清单

1. 是否修改了 ORM 持久化字段、索引、约束、RLS 或函数？
2. 是否有对应的线性 Alembic revision？
3. migration 是否包含明确的数据分类和回填策略？
4. 是否避免把异常正文、SQL、路径或凭据写入公共字段？
5. 是否更新 `EXPECTED_DATABASE_REVISION`？
6. 是否证明 API startup 没有 DDL/回填调用？
7. 是否在 SQLite 测试和目标 PostgreSQL 上验证？
8. 是否记录备份、升级、审计和 smoke test 结果？
