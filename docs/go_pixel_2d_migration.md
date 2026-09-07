# 2D 像素化与拼接方案 Go 迁移记录

> 2026-09-06 / P2D-0～P2D-3 / 代码迁移与本地验收完成；真实环境发布待执行
> 总原则：[go_backend_migration_principles.md](go_backend_migration_principles.md)
> 总进度：[go_migration_progress.md](go_migration_progress.md)

## 范围与阶段

用户授权迁移图片像素化、项目保存/编辑/列表、LEGO 拼接生成、BOM、可选底座、LDraw 和 JSON 设计计划导出。DEM 与 GLB 不在本次范围；不清空或重写任何既有开发数据库。

| 阶段 | 内容 | 完成门禁 |
|---|---|---|
| P2D-0 | Python 功能 inventory、目标契约、golden 输入输出 | 三种像素算法、预处理、编辑、拼接、底座和导出逐项可追溯 |
| P2D-1 | Go 像素算法、Goose/sqlc 存储、持久任务 | PostgreSQL 所有权/并发/恢复、源与派生资产测试 |
| P2D-2 | Go 拼接、颜色/零件元数据、导出 | 覆盖不重叠、BOM、坐标/旋转、冻结语言与输入快照测试 |
| P2D-3 | 前端 /api/v1 切换、停止 Python 入口 | Go-only 链路、SQL 计划、完整测试与构建 |

## 迁移前事实

- `backend/src/pixel_art/quantization.py`：photo_illustration、logo_text、side_mixed_plate_brick_pixel；RGB/alpha、裁剪、预处理、BOX 缩放、加权 K-means 众数颜色、侧面混合元数据。
- `pixel_art_service.py`：原 public 项目表无 actor 隔离，PNG 存数据库，更新像素不重建预览。
- `lego_design.py`：线程 + 进程内 dict/lock；重启丢失任务。`lego_design_service.py` 同时服务 2D 和归档 DEM，不能整文件删除。
- 2D 使用真实 Plate 几何、颜色映射、最大矩形填充及合并，导出含可选白底/黑连接层和分步说明。

## 目标边界

- 新领域 schema `pixel_2d` 由 Goose 独占；legacy `public` 对象和 Alembic 历史保持冻结，不双写、不自动搬移无 owner 的历史项目。
- Task 继续使用现有共享 `component_repo.tasks/task_jobs` 协议，新增 `pixel_2d.*` Go consumer；API/Worker 启动无 DDL。
- 所有项目、任务与下载按 JWT actor 校验。源图和大型派生产物进入对象存储，数据库仅存状态、定位、哈希和冻结输入。
- 项目生成/更新和拼接为持久任务；拼接冻结项目修订、元数据版本、算法版本、locale/timezone/catalogVersion。
- 资源使用已有 code/params 与版本化服务端词典，不翻译用户名称和机器字段。

## SQL 性能设计预检

- 新域项目数没有产品批准的硬上限；按最多 1,000 用户、总量 100,000 及极端单 actor 100,000 条评估增长。
- 列表从 `(owner_id, created_at DESC, id DESC)` 权威所有权索引开始；无可选搜索/翻译/聚合筛选，选择性由 actor 分布决定。
- 保留现有页码与精确总数交互；在 100,000 单 actor 的最深页实测后记录风险，不能把导航变更当作性能修复。rows/total 使用单 SQL 语句同一快照，先定页，再签名页内预览。
- 元数据读取使用固定版本目录，不从每个列表项目逐行查询 Part/Color；任务冻结元数据后可脱离后续目录变化运行。
- 计划门禁：EXPLAIN (ANALYZE, BUFFERS, SETTINGS)，空 actor/少量 actor/高占比 actor、首/中/末页；记录 PostgreSQL 版本与缓存条件。

## 验证与未关闭事项

### 2026-09-06 实施记录

1. P2D-0：固化旧 Python 输出，保留独立离线生成脚本 `backend-go/scripts/pixel2d-golden.py`。21 组覆盖三种算法、透明通道、颜色渐变、非整除裁剪、增强、局部对比度。Go 测试读取固化文件，不启动 Python。
2. P2D-1：`backend-go/internal/pixel2d` 实现 PNG/JPEG/WebP、裁剪、预处理、BOX、确定性 K-means 与侧面元数据。Goose v19 新建 `pixel_2d`；sqlc 查询实现 owner 隔离、当前修订 CAS、不可变完成修订和目录、同事务持久任务。编辑会重新生成 palette/PNG；旧父修订返回 409。
3. P2D-2：真实矩形 Plate 覆盖、颜色映射、BOM、底座/连接层、分步 JSON/LDraw 全部由 Go Worker 生成。四种语言/底座组合与 Python 固化输出完整对照通过。修复窄网格底座负坐标边界；拼接须等待像素任务成功。目录和修订冻结后，后续编辑不会改变已排队设计。
4. P2D-3：前端调用认证后的 `/api/v1/pixel-art` 与 `/api/v1/lego-design`；写请求返回 202，页面轮询并能从项目/任务 URL 恢复。移除 FastAPI 2D 路由注册及进程内设计队列；旧像素算法和服务归档至 `backend/archive/pixel2d`。DEM 共用的拼接代码保留，不参与 Go 2D 运行。

### 验证结果

- `go test ./...` 通过；算法 21 组以及设计/BOM/双语言 JSON 和 LDraw 对照通过。
- `RUN_PIXEL_PLAN_TEST=1 ./scripts/test-postgres.sh` 通过：隔离 PostgreSQL v19 up/down/up、API/Worker 重复启动无 DDL、现有集成测试与 Go-only 2D 工作流。覆盖跨 owner 拒绝、服务重建后消费、重复任务复用、旧修订并发拒绝、编辑预览再生、冻结设计输入、导出访问控制、对象写失败不创建项目、不可变修订拒绝修改。
- `frontend`: i18n 检查通过（2 locales/10 namespaces），测试 75 项；生产构建通过。`backend`: pytest 296 项通过（6 个既有警告）。构建仍有大 chunk 提示。
- SQL 证据：[完整计划](evidence/pixel_2d_pg14_plans.txt)。PostgreSQL 14.17/Homebrew/aarch64；100,000 项目与 100,000 修订归属于一个高占比 actor，另有单项目 actor 和空 actor。修订共用测试任务，任务表规模不构成此次性能证据；无官方翻译探测。
- 本地 VACUUM ANALYZE 后缓存状态下，12 条一页：首 6.948ms、中 OFFSET 49,992 为 13.393ms、末 OFFSET 99,996 为 20.174ms；空 actor 0.037ms、单项目 actor 0.061ms。索引选择 ownership 范围，定页后按 revision 主键补充；无排序落盘。时间只证明本地查询形状，不能作为生产 SLO。

### 真实环境发布步骤（2026-09-06 已执行迁移和目录导入）

2026-09-06 已对配置指定的 Supabase PostgreSQL 17.6 执行 v18 → v19 和真实目录导入；未清库、未迁移历史用户项目。可重复查验步骤：

1. 备份并确认目标数据库，`cd backend-go` 后运行 `go run ./cmd/migrate status`，再 `go run ./cmd/migrate up`；v19 仅新增 Go 所属 schema。API/Worker 不代替发布命令执行迁移。
2. 使用旧环境的只读元数据连接，从仓库根运行 `.venv-app/bin/python backend-go/scripts/export-pixel2d-catalog.py --ldraw-root "$LDRAW_ROOT" --output /tmp/pixel2d-catalog.json`。它只导出真实 Plate/Color，不导出用户项目。审查目录后，在 Go 目标数据库运行 `go run ./cmd/pixel2d-catalog --metadata /tmp/pixel2d-catalog.json`，记录返回哈希。测试 fixture 禁止充当生产目录。
3. 配置现有 Supabase Storage bucket、key prefix 和服务端密钥。派生产物键为 owner/kind/内容哈希；临时 source/input 额外包含独立 blob UUID，避免相同图片任务互相清理。预览使用 15 分钟签名 URL。密钥不能暴露给前端。
4. 启动 Go API 与 `WORKER_TASK_TYPES=pixel_2d.generate,pixel_2d.edit,pixel_2d.design` 的 Go Worker；纯 2D Worker 不要求 LDraw 文件库或 GLTFPack。部署前端新路径，停止 Python 2D 消费入口。Python DEM/GLB 边界不变。
5. 在真实认证和对象存储中验证上传、刷新恢复、编辑、拼接、双语言下载和跨账号拒绝；用目标 PG 版本重新运行列表计划，并记录环境与目录哈希。

### 未关闭门禁与已知差异

- **P2D-RELEASE-01 / P2D-3**：真实上传、编辑、拼接任务与浏览器结果已验证；双语言下载、第二身份实测及修复后照片预览浏览器验收仍未关闭。关闭条件为上述发布步骤实测及证据，不以 mock Storage 或隔离 PG 代替。
- **P2D-SQL-01 / P2D-3 运行维护**：保留页码和精确 total 的既有交互，OFFSET/count 仍为 O(N)。当前本地 100,000 行证据通过；接近单 actor 100,000 项目或提高容量包络前，必须重评生产 SLO。改变为 cursor/非精确 total 需用户批准。
- **P2D-DATA-01 / 历史数据迁移**：legacy public 项目无可靠 owner，不能自动分配给当前用户。原数据保留；新 Go 列表只显示明确归属的 Go 项目。需要历史项目时，应另行确定 owner 映射或重新上传。
- **P2D-STORAGE-01 / P2D-3 运行维护**：先登记 blob reservation 再写对象，失败保留定位与哈希，可重试复用；尚无自动孤儿删除。上线前纳入存储容量监控，清理必须证明无项目/修订/任务引用，不能仅按时间删除。
- 算法对照是固定样本证据，不声称所有图像与 Pillow 字节级等价；编码器生成的 PNG/JPEG/WebP 解码边界可能不同。`preserveLightDetails` 与原算法一致未引入新处理分支。


### 2026-09-06 真实运行与卡顿排查（P2D-3）

- v19 已于 17:05 完成，未执行 reset。迁移前保存 Goose 账本、版本和业务计数的只读快照，SHA-256 `4cd7fafecdfe5dc3d0b8df33693e56bb658299cd29c090dece8ad804e9c14eb0`；这不是全库备份。
- 真实元数据为 227 色和 27 种普通 Plate，目录哈希 `e262c86e2ffcb3f2346789c0ab3333f81b4cee246244acd44a9872554df03b8c`。旧表已无 Plate，维护导出器改为从本地 LDraw 标题识别最多 256 个候选，再校验 active Go library 的 ready 几何和 source_file_hash；不以测试数据填充生产目录。Plate 含凸点 bbox 可为 1.5 plate，逻辑拼接厚度仍为 1。
- 默认开发拓扑为 Go API + Go Worker + Vite，Python 8000 未启动。DEM/3D 工具导航、主页卡片和旧路由全部关闭；归档源文件保留。通用 Worker 的 gltfpack 可读取已有 `.tools/meshoptimizer-v1.2/gltfpack`。Go 启动脚本先编译再 exec，避免停止 go run 父进程后残留子进程占端口。
- 真实任务均为一次 attempt 成功：generate 排队 4.635s / 执行 14.314s，edit 排队 3.517s / 执行 6.654s，design 排队 6.016s / 执行 19.157s。一次上传/建任务 HTTP 为 9.730s；项目 GET 约 0.9–4.5s。执行时间包含远程读写，不能直接当作量化 CPU 时间。
- 浏览器已显示 64×48、16 色、864 个零件、156 种零件/颜色组合的拼接结果；Go 重启后同一 job 可恢复显示。真实存储已有 source/project/preview/design/plan/ldraw 对象。浏览器验收发现完成进度缺少 `params.percent`，已补齐。
- 本地预览曾在主线程逐像素处理，并在邻域内反复读取本地化 Proxy。现在数字配置直接读取 JSON；增强计算使用 Web Worker + transferable buffer，最长预览边 640 像素，rAF 合并 resize，参数变化终止过期 Worker；固定 canvas CSS 高度避免 backing 尺寸/ResizeObserver 反馈。上传原图和 Go 最终算法不变。Worker 错误使用双语言资源提示。
- 可复现基准：`node frontend/scripts/benchmark-pixel-preview.cjs`，320×240 合成图、sharpness=1.4/localContrast=0.6，相同输出缓冲区逐字节一致；本机旧 Proxy 1567.56ms，普通配置 14.94ms（单次 Node 测量，只证明配置访问开销，不是端到端提速承诺）。
- 项目恢复、生成与编辑等待支持 AbortSignal；离开页面停止 HTTP 轮询，数据库任务继续执行。Worker 日志新增 `read_input`、`compute_pixels`、`persist_outputs` 阶段耗时，不含照片、名称和存储路径。
- 修复后前端 79 项测试、多语言校验和生产构建通过；Python 296 项回归通过，保留 6 个既有警告。浏览器自动文件选择在 chooser 阶段超时，尚未完成修复后照片预览的浏览器复测，不能把计算基准等同于该门禁已通过。
- **P2D-LATENCY-01 / P2D-3**：下一次真实生成需采集新增阶段计时，区分算法与跨区域 PG/Storage 等待，再确定服务端优化；本次未宣称服务端端到端延迟已解决。

- 最终复核：Go 全包测试和隔离 PostgreSQL v19 migration/startup/task 集成通过（含进度插值断言）；前端 79 项及构建再次通过。已有大 chunk 构建提示未在本次处理。

### 2026-09-07 异步页面与输入生命周期（P2D-3）

- 产品确认项目不长期保存原始照片。源图和编辑输入仅作为持久任务的临时正文：任务可以跨页面、API/Worker 重启重试；修订产物完成后，Worker 删除输入对象。数据库保留文件名、哈希和 owner-scoped 定位用于审计，不提供原图读取入口。
- 清理发生在不可变项目 JSON 与预览 PNG 完成之后。若删除失败，本次 attempt 返回可重试失败；重试检测到修订已经物化后只重试幂等删除，不重新运行像素算法。达到最大重试次数的失败输入仍由 **P2D-STORAGE-01** 的终态/孤儿清理门禁负责。
- 上传请求返回 202 后，前端立即把 `projectId` 写入 URL，并通过 owner-only `/api/v1/tasks/:taskId` 轮询。任务成功后只读取一次完整项目，避免每秒下载项目 JSON或生成预览签名 URL。
- 页面展示上传、排队、处理、完成和失败阶段。任务未提供真实百分比时使用不确定进度条，不伪造百分比；完成显示 100%。离开页面只中止 HTTP 等待，不取消 PostgreSQL 任务。“已保存像素图”会显示未完成项目并提供恢复入口。
- 新增 zh-CN/en-US 语义资源，目录版本 `frontend-2026.09.07.1`、内容哈希 `369c7fe3189d1643ced79283c52eea375718f7fb515eaa5cbba7e7e724aa58c2`。
- 验证：前端 i18n 检查、79 项测试和生产构建通过；Go `./...` 通过；隔离 PostgreSQL v19 migration/startup/task 集成通过，包含成功后输入删除与相同图片并发任务互不干扰；Python 回归 296 项通过（6 个既有 pytest 警告）。
