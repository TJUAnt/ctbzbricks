# 2D Python 历史参考

2D 正式 API 与持久 Worker 已迁往 `backend-go/internal/pixel2d`。此目录只保留迁移前算法和 legacy persistence 作为测试参考，FastAPI 不导入或挂载它们。

2D 与 DEM 共用的 `lego_design_service.py` / `lego_pixmap_strategy.py` 暂留原目录供归档 DEM 使用，不构成 2D 运行时 Python 依赖。

旧 public 项目没有 actor 归属，新 Go 域不自动认领、同步或删除这些历史数据。详见 `docs/go_pixel_2d_migration.md`。
