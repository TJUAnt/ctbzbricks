# DEM 页面归档

2026-09-06：DEM 采集与地形拼搭页面退出正式导航和路由，源码保留于本目录。

- `TerrainDemPage.tsx`：原 DEM 页面；导出的共享预览仍供资产查看器使用。
- `LegoTerrainBuilderPage.tsx`：原地形高度图流程。
- `LegacyLegoDesignPage.tsx`：保留原图片 / DEM 混合设计实现。正式 2D 路由使用默认 `enableDem=false`，不展示 DEM 选择器、不请求 DEM 资产。需要恢复时显式启用并重新登记路由。

共享算法、API、配置、资源和后端代码保持原目录，不删除历史资产。模型资产旧链接仍可访问，但不出现在主导航。GLB 拼接方案生成尚未实现，本次只重组已有入口。

## 验证

- `npm run i18n:check` 通过，资源版本 `frontend-2026.09.06.1`。
- `npm test`：15 个文件、72 项测试通过，包含广场与管理入口隔离、DEM 入口隐藏和双语言页面检查。
- `npm run build` 通过，保留既有大 bundle 提示。
- 在 backend 使用 `.venv-app` 的 Python 执行 `python -m pytest`：295 项通过，6 项既有测试返回值警告。
- 本次不改 Go 后端、SQL、API、存储或任务契约，不推进 Go 迁移阶段。
