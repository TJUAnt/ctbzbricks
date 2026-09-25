# Go 后端测试目录

Go 测试按执行边界分为三层：

- 单元测试与被测包同目录，继续放在 `internal/**`。这类测试允许验证包内不变量，并使用 Go 标准的 `testdata` fixture。
- `integration/**` 是跨 PostgreSQL、HTTP、Storage、Service 和 Worker 边界的黑盒集成测试。测试包统一采用
  `<domain>_test`，只通过公开入口使用生产代码。
- `performance/**` 是显式开启的容量与 `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` 门禁，不参与日常单元测试。

Integration 和 Performance 文件都使用 `//go:build integration`。常用命令：

```bash
make test                         # 无外部数据库的日常单元测试
make test-integration             # 使用 TEST_DATABASE_URL；未配置时用例跳过
make test-performance             # 编译性能门禁；只有对应 RUN_* 标志为 1 时执行
make test-postgres                # 新建隔离 PostgreSQL，迁移往返、全量集成、启动无 DDL 契约
```

性能门禁按领域显式开启：

| 环境变量 | 门禁 |
|---|---|
| `RUN_COMPONENT_LIST_PLAN_TEST` | Component 目录 |
| `RUN_PUBLIC_FEED_PLAN_TEST` | 公共 Feed |
| `RUN_STAR_SIZE_PLAN_TEST` | Star 容量与尺寸投影 |
| `RUN_WATCH_LIST_PLAN_TEST` | Watch 管理列表 |
| `RUN_WATCH_FEED_PLAN_TEST` | Watch Feed |
| `RUN_VERSION_PARTS_PLAN_TEST` | Version BOM Part 投影 |
| `RUN_PIXEL_PLAN_TEST` | Pixel 2D 项目列表 |
| `RUN_PART_SEARCH_PLAN_TEST` | Part Search 描述、尺寸与深页 |
| `RUN_LIVE_PART_SEARCH_PLAN_TEST` + `LIVE_PART_SEARCH_LIBRARY_ID` | 对显式 `DATABASE_URL` 与不可变 Library ID 运行只读的 Part Search 部署计划；不造数、不清表 |

`make test-postgres` 默认同时发现 `integration/**` 和 `performance/**`；未开启的性能用例会跳过但仍完成编译。
`BRICKBUILDER_TEST_PACKAGES` 只用于资源受限 runner 精确覆盖包集合，不改变迁移往返和 API/Worker 启动契约。
sqlc 生成目录 `db/generated` 只保存生成代码，不放置手写测试。
