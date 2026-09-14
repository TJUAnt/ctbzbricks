# ctbzbricks

A data platform for LEGO bricks.

## Mandatory architecture constraints

- Coding agents must follow [AGENTS.md](./AGENTS.md).
- Every user-visible, API, task, domain-content, or export change must start with the multilingual impact check in [I18N_CHANGE_GUARDRAILS.md](./I18N_CHANGE_GUARDRAILS.md).
- The approved system design is documented in [I18N_ARCHITECTURE.md](./I18N_ARCHITECTURE.md).
- Go backend migration work must follow the [migration principles](./docs/go_backend_migration_principles.md), [Component Repo migration plan](./docs/go_component_migration_plan.md), [Component Repo API contract](./docs/api.md), and [migration progress log](./docs/go_migration_progress.md).
- The runnable Go API/Worker scaffold is documented in [backend-go/README.md](./backend-go/README.md).
- The reviewable Linux deployment topology is documented in [Docker production deployment](./docs/deployment/docker_production.md).

## 详细功能设计

这里记录当前代码实际采用的前端调用、HTTP 接口、Go 服务、SQL、任务、权限和测试链路。功能文档描述当前实现；
路线文档继续保存产品决策、容量证据和阶段状态。修改功能前应先更新对应文档的代码索引和偏移清单，修改完成后再用
测试与迁移证据关闭清单项。

| 功能 | 当前实现文档 | 主要范围 | 状态 |
|---|---|---|---|
| Watch | [Watch 详细设计](./docs/component_repo/watch.md) | Watch/Unwatch、管理列表、动态 Feed、发布事件与删除联动 | 仓库实现和测试完成；读取已使用 v24 共享投影，真实 Supabase 仍为 v23，浏览器与生产计划验收待执行 |
| Star | [Star 详细设计](./docs/component_repo/star.md) | Star/Unstar、收藏列表、计数、尺寸筛选与删除联动 | 已实现；候选完整性、前端职责拆分及跨模块展示投影已收敛，Star 自身一致性项保留 |
| Component | [Component 详细设计](./docs/component_repo/component.md) | 目录、详情、版本、上传导入、发布、Preview GLB、BOM、Diff 与删除 | Go 主链路已实现；01～06 中已授权项及 08 已关闭，目录改为单查询 cursor，视觉验收待执行 |
| 组件广场 | [组件广场详细设计](./docs/component_repo/component_plaza.md) | 公共/个人订阅页签、Worker 派生事件图片、Watch Feed 与订阅管理入口 | 双 Feed、Cycles 优先 renderer v4 和 Docker 生产封装完成；服务器部署与浏览器验收待统一执行 |

统一接口契约以 [docs/api.md](./docs/api.md) 为准，Go 迁移事实以
[docs/go_migration_progress.md](./docs/go_migration_progress.md) 为准。专项产品与容量决策见
[Watch 路线文档](./docs/design/lego_design/component_repo_watch_design_and_roadmap.md)和
[Star 路线文档](./docs/design/lego_design/component_repo_star_design_and_roadmap.md)。
