# Part Library 详细设计

> 状态：当前实现文档；本次切片处于 G8 后续 Part Library / Part Search 数据与搜索契约收口
>
> 功能需求：[我的模型 / Part Search](../../../requirements/my-models/part-search/README.md) · [Part 详情](../../../requirements/my-models/part-search/part-detail/README.md)
>
> 路线与数据来源：[Studio Part Library 基准路线图](../../../go_part_library_studio_roadmap.md)
>
> 公共接口：[Component Repo API](../../../api.md)
>
> 迁移事实：[Go 后端迁移进度](../../../go_migration_progress.md)

## 1. 模块边界

Part Library 是 `/part-search` 与 `/parts/:partLibraryVersionId/:ldrawPartNum` 两个可独立访问页面所属的功能模块。
它负责把 BrickLink Studio 随附的 LDraw snapshot 离线导入 PostgreSQL，并向在线 Go API 提供稳定的 Part
身份、官方源描述、标称尺寸、几何状态、预览资产和 reviewed translation。API 与 Worker 启动不扫描 Studio
目录、不执行 DDL，也不回填数据。

核心身份是 `(partLibraryVersionId, ldrawPartNum)`。`ldrawPartNum`（例如 `3001.dat`）是机器标识，不是展示名称。
展示名称的源内容来自顶层 LDraw 文件第一条有效描述行；缺失描述时才允许退回机器标识，并将该退回作为数据质量
问题跟踪。用户可见名称优先选择请求 locale 的 reviewed `part_translations.name`，否则返回源描述和源 locale。

## 2. 本次修复前的偏移

1. 页面把描述、编号和尺寸塞入一个 `query`，用户无法明确组合筛选条件。
2. SQL 以“任一关键词命中、任一尺寸命中”解释输入，与多条件筛选预期不一致。
3. 三维尺寸把 stud 平面单位和 plate 高度一起排序，语义错误；高度不能与宽/深换轴。
4. importer 把几何 bbox 派生的近似值标记为 `derived_approximate`，搜索却按精确值使用。
5. importer v3 已从 LDraw header 读取描述，但旧 active snapshot 只有在显式重导入后才会修复历史 `xxx.dat`
   展示值；仓库代码完成不能冒充真实数据库已修复。
6. 搜索结果未使用 reviewed Part translation，和 official content 规则不一致。

## 3. 搜索契约

`POST /api/v1/parts/search` 接受以下可选筛选字段：

- `description`：人类描述，按规范化 token 全部命中；匹配源描述和请求 locale 的 reviewed translation。
- `partNumber`：LDraw 编号的规范化包含匹配，仍是机器值，不翻译。
- `widthStud`、`depthStud`：平面标称尺寸；两者都提供时允许 90° 旋转。
- `heightPlate`：独立的垂直标称尺寸，不参与宽/深换轴。
- `locale`：决定 reviewed translation 的选择；缺省规范化为 `en-US`。
- `page/pageSize`：页码从 1 开始，`pageSize` 最大 200。

所有已填写筛选条件按 AND 组合。只有 `geometry_status=ready` 且
`logical_size_derivation_status=derived_exact` 的记录可命中任一尺寸条件。没有尺寸条件时仍可返回
`derived_approximate`，但 UI 必须显示其可信度，不得把它表述成标称精确尺寸。

结果稳定排序为：描述完整匹配优先、源描述、`ldrawPartNum`。排序不依赖 locale，避免用户切换语言后分页漂移；
reviewed translation 仍参与描述筛选并用于展示。列表固定本次查询采用的
`partLibraryVersionId`；active snapshot 后续切换不会让已有详情链接漂移。

## 4. 标称尺寸派生

离线 importer 先把 LDraw 描述压缩为空白规范化文本，再按可审计规则派生尺寸：

- `Brick W x D`：`W × D stud`、高度 `3 plate`；
- `Plate W x D` 与 `Tile W x D`：`W × D stud`、高度 `1 plate`；
- 仅上述明确前缀与尺寸结构标记为 `derived_exact`；
- 其他 ready 几何保留 bbox 换算值并标记 `derived_approximate`；解析失败保持 `failed` 和空尺寸。

规则版本写入 library/Part metadata，importer 版本变化会使保留更新脚本要求显式重导入同一 manifest。重导入由
离线命令在一个事务中更新数据库；执行真实环境写入前必须确认精确数据库目标。

## 5. SQL 性能预检

| 项目 | 决策 |
|---|---|
| 驱动关系 | 从唯一 active `part_library_version_id` 对应的 `parts` 主键范围开始，再连接同版本 geometry |
| 当前基数 | 真实 Studio snapshot 24,426 Part；新 snapshot 产生新版本，在线查询只读取一个 active 版本 |
| 增长方向 | 单版本随 Studio library 增长；历史版本不会进入 active 搜索候选 |
| 过滤选择性 | 编号通常高选择性；精确尺寸中等；`plate/brick/tile` 等描述词高匹配 |
| 排序 | 相关度、源描述、唯一 `ldrawPartNum`；不随 locale 改变。当前页码深页仍可能执行有界排序，见 `PART-LIBRARY-PERF-01` |
| 分页 | 保留产品现有页码；本次只按真实 snapshot 的 24,426 条验证最深 OFFSET。单版本接近 100,000 条或实测深页超出门禁时重开 keyset |
| 总数 | UI 需要 exact total；列表与总数必须来自同一个 `REPEATABLE READ READ ONLY` 快照 |
| 翻译 | 只探测请求 locale 的 reviewed 行；列表固定后才关联预览 Artifact，避免对候选集做 Storage 工作 |
| 尺寸索引 | 使用版本 + `derived_exact` + 规范化平面尺寸 + 高度的查询专用 partial expression index |
| 描述搜索 | 当前单版本候选有界；token 包含匹配先接受 bounded scan，不声称普通 B-tree 可优化前导通配符 |

完成门禁按当前 24,426 条规划规模包含无筛选、高选择性编号、`plate` 高匹配、尺寸首屏、最深支持页的
`EXPLAIN (ANALYZE, BUFFERS, SETTINGS)`，记录 PostgreSQL 版本、数据形状、缓存条件、loops、buffers、排序与临时文件。
本地数字只证明查询形状，不作为生产 SLO。

## 6. 权限、i18n 与资产边界

- 搜索与详情要求已认证 actor，但 Part Library 是共享官方内容，不按 owner 分区。
- official Part 文案只选择 reviewed translation；draft/rejected 不得泄露。
- 源描述以 `contentLocale` 原样保存；不在线机器翻译。
- 编号、尺寸、状态、JSON 字段、API code、Artifact ID 和 hash 不翻译。
- 列表只签名当前页已 verified 的 GLB；Storage key 不出公共 API，单项签名失败降级为无缩略图。
- Preview 生成仍是 PostgreSQL 持久任务；搜索不创建任务、不读取 LDraw 源文件或对象正文。

## 7. 前端调用与关键代码

- 页面：`frontend/src/parts/PartSearchPage.tsx`
- 双语资源：`frontend/src/i18n/resources/{en-US,zh-CN}/partSearch.json`
- HTTP DTO/Handler：`backend-go/internal/workbench/types.go`、`backend-go/internal/workbench/handler.go`
- 应用服务：`backend-go/internal/workbench/service.go`
- 查询：`backend-go/db/queries/parts.sql`
- Studio 描述/尺寸派生：`backend-go/internal/partlibrary/ldraw_geometry.go`、`importer.go`
- Schema/索引：`backend-go/db/migrations/`
- 数据更新入口：`backend-go/scripts/update-studio-part-library.sh`

## 8. 本次验证与清理项

2026-09-19 仓库验证：Go unit、sqlc generation、Goose `0 -> v25 -> v24 -> v25`、重复 up、完整隔离 PostgreSQL
integration 与 API/Worker 启动 schema 不变契约通过。当前规模计划 fixture 使用 PostgreSQL 14.17、24,426 Part、
24 条 reviewed translation、`shared_buffers=128MB`、`work_mem=4MB`、`effective_cache_size=4GB`，已 ANALYZE，以下为
warm-cache 本地证据，不是生产 SLO：

| 场景 | 执行时间 | 计划结论 |
|---|---:|---|
| 无筛选首屏 | 39.955 ms | active snapshot 有界扫描；translation CTE 只扫描一次；Top-N 内存排序 |
| 高选择性编号 | 3.041 ms | 当前仍在单 snapshot 内扫描编号；无临时文件 |
| `plate` 高匹配 | 34.469 ms | 2,442 命中；reviewed translation CTE 一次物化；无临时文件 |
| `2 × 4 stud / 1 plate` 精确尺寸 | 0.528 ms | 使用 `part_geometries_exact_logical_size_idx`，244 候选，无临时文件 |
| 最深支持页 | 54.703 ms | 24,426 候选 OFFSET；external merge 约 3.6 MB，已登记延期 |
| `plate` exact count | 33.562 ms | list/count 同一只读快照；无临时文件 |

最终门禁：`backend-go make check`、`make test-postgres`（`0 -> v25 -> v24 -> v25`、重复 up、完整 integration、
API/Worker 启动 schema 不变）、24,426 Part 计划门禁、前端 `i18n:check`、25 文件/106 项测试、build 与
`git diff --check` 全部通过。本机浏览器已确认 `/part-search` 双语筛选壳层正确显示描述、编号、宽/深/高和
可信尺寸说明；当前浏览器未登录，且真实 active snapshot 未升级，因此真实数据结果验收仍归
`PART-LIBRARY-DATA-01`。仓库完成不表示 Goose v25、importer v4 或应用已经部署到真实 Supabase。

仍存在的问题：

1. `PART-LIBRARY-DATA-01`（部署阶段）：真实 active snapshot 仍可能保留旧 importer 的 `xxx.dat` 展示名和
   approximate 尺寸。关闭条件：确认精确数据库目标，应用 v25，运行保留更新脚本触发 importer v4 重导入，并核对
   `3001.dat/3023.dat/tile` 描述、状态和 API 结果；不得只以仓库测试关闭。
2. `PART-LIBRARY-SIZE-01`（S4）：exact 规则仅覆盖标准 Brick/Plate/Tile；modified/slope/round/minifig/sticker
   尚未分类。关闭条件：冻结分类规则、算法版本与代表 fixture，明确 exact/approximate/not-applicable 并通过重导入审计。
3. `PART-LIBRARY-PERF-01`（延期，产品决定）：当前 24,426 条最深页会产生约 3.6 MB external merge；本次不执行
   100,000 候选排序优化。单版本接近 100,000 条、生产 temp file/延迟异常或产品批准改变页码交互时，改用 keyset
   或权威搜索/排序投影，并重跑 first/deep/cold/warm 计划门禁。
4. `PART-LIBRARY-SEARCH-01`（容量阶段）：描述和编号包含匹配是单 active snapshot 有界扫描；没有宣称普通 B-tree
   能优化前导通配符。关闭条件：增长或指标触发后选择并验证 FTS/trigram/权威规范化投影，记录写放大和索引成本。
5. `PART-LIBRARY-I18N-01`（内容运营）：API 已严格只选 reviewed translation，但当前覆盖率未形成发布指标。
   关闭条件：建立按 active snapshot/locale 的 reviewed 覆盖率、审核责任和发布门禁，不得用 draft 或机器翻译兜底。
