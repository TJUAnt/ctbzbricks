# 页面菜单重组 TODO 方案

目标：按照 `像素图与模型管理-3D构建.xlsx` 中的菜单结构重组前端页面信息架构，把当前分散的上传、资产列表、构建入口和结果查看入口整理成清晰的业务流程。

当前阶段只跟踪方案和任务，不修改代码。

## 目标菜单结构

```text
资产管理
  - 像素图管理
  - DEM 模型管理
  - 3D 模型管理

构建 LEGO 模型
  - 构建像素图 LEGO 模型
  - 构建山体 LEGO 模型
  - 构建 3D LEGO 模型

查看模型
  - LEGO 模型管理

查找零件
  - 零件搜索
```

## 当前页面映射

| 目标菜单 | 当前可复用页面 | 当前问题 |
| --- | --- | --- |
| 像素图管理 | `PixelArtPage`、`PixelArtProjectsPage` | 上传/编辑和项目列表是两个菜单项，应该合并为一个管理页，用 tab 切换。 |
| DEM 模型管理 | `TerrainDemPage`、`ModelAssetsPage` | DEM 在线构建和 DEM 资产列表没有形成统一管理入口。 |
| 3D 模型管理 | `DirectModelImportPage`、`ModelAssetsPage` | 3D 上传和模型列表分离，列表页也混合了多种资产类型。 |
| 构建像素图 LEGO 模型 | `LegoDesignPage` | 当前页面同时承担像素图 LEGO 和 DEM 最终设计，需要拆清入口。 |
| 构建山体 LEGO 模型 | `LegoTerrainBuilderPage`、`LegoDesignPage` | 山体 LEGO 有 heightmap 构建和 final design 两类流程，需要明确主入口。 |
| 构建 3D LEGO 模型 | 待新增页面 | 需要接入 model fitting / vehicle-8-wide 工作台。 |
| LEGO 模型管理 | 待新增或从 `LegoDesignPage` 拆出 | 当前缺少专门查看保存 LEGO 图纸和方案的管理页。 |
| 零件搜索 | `PartSearchPage` | 可以直接复用。 |

## 第一阶段：菜单与路由重组

状态：未开始。

目标：只调整导航结构和路由入口，不改变核心业务逻辑。

TODO：

- [ ] 在 `frontend/src/app/appConfig.json` 中新增目标菜单配置。
- [ ] 将菜单分组从 `frontend/src/main.tsx` 迁移到配置驱动。
- [ ] 新增一级菜单分组：资产管理、构建 LEGO 模型、查看模型、查找零件。
- [ ] 保留现有页面路由，先通过新菜单指向旧页面或新容器页。
- [ ] 调整默认首页，建议进入 `资产管理 / 3D 模型管理` 或 `构建 LEGO 模型 / 构建 3D LEGO 模型`，最终根据当前开发重心决定。
- [ ] 验证现有页面仍可通过新菜单访问。

验收标准：

- 左侧菜单结构与 Excel 一致。
- 现有页面没有丢失入口。
- `npm run build` 通过。

## 第二阶段：资产管理页整合

状态：未开始。

目标：把每类输入资产变成独立管理页，上传、生成、列表查看放在同一页面内。

TODO：

- [ ] 新增 `PixelAssetManagementPage`。
- [ ] 在像素图管理页内用 tab 承载：上传/像素化、像素图列表。
- [ ] 新增 `DemAssetManagementPage`。
- [ ] 在 DEM 模型管理页内用 tab 承载：在线构建/上传、DEM 模型列表。
- [ ] 新增 `MeshAssetManagementPage`。
- [ ] 在 3D 模型管理页内用 tab 承载：上传 GLB、3D 模型列表。
- [ ] 让模型列表支持按资产类型过滤，避免 3D、DEM、LEGO heightmap 混在一个无语义列表里。

验收标准：

- 用户能在一个页面完成同类资产的创建和查看。
- 像素图、DEM、3D 模型三类资产的入口清晰分离。
- 原有上传和列表能力不丢失。

## 第三阶段：LEGO 构建入口拆分

状态：未开始。

目标：按输入资产类型拆清 LEGO 构建流程，避免一个页面同时承担多种算法。

TODO：

- [ ] 新增 `PixelLegoBuildPage`，只负责像素图到 LEGO。
- [ ] 在 `PixelLegoBuildPage` 中承载两种像素图构建算法入口。
- [ ] 新增 `TerrainLegoBuildPage`，只负责 DEM / 山体 LEGO。
- [ ] 在 `TerrainLegoBuildPage` 中承载 surface 和 replacement 算法入口。
- [ ] 新增 `MeshLegoBuildPage`，只负责 3D model to LEGO。
- [ ] 在 `MeshLegoBuildPage` 中接入 vehicle-8-wide model fitting job。
- [ ] 把 `LegoDesignPage` 中混合的像素图/DEM 生成逻辑逐步拆到对应页面。

验收标准：

- 用户选择构建入口时，能明确知道输入资产类型和算法类型。
- 像素图 LEGO、山体 LEGO、3D LEGO 三条流程互不混淆。
- 3D LEGO 入口能选择 vehicle-8-wide 并创建后端 job。

## 第四阶段：LEGO 模型管理

状态：未开始。

目标：建立输出结果管理入口，最终承载可编辑拼搭方案。

TODO：

- [ ] 新增 `LegoModelManagementPage`。
- [ ] 定义 LEGO 模型结果列表数据来源。
- [ ] 展示保存的 LEGO 设计图纸、BOM、导出状态和创建时间。
- [ ] 支持打开已有 LEGO 设计。
- [ ] 对 3D LEGO 方案，支持进入可编辑 solution workspace。
- [ ] 明确 LEGO 模型与原始输入资产的关联关系。

验收标准：

- 用户可以从一个入口查看所有已保存 LEGO 输出。
- 用户可以继续编辑或导出已有方案。
- 3D LEGO 的可编辑拼搭方案有明确入口。

## 第五阶段：后端和数据结构补齐

状态：未开始。

目标：支持前端菜单重组后的数据过滤、结果管理和 3D LEGO 工作流。

TODO：

- [ ] 模型资产列表 API 支持按 `modelType` 过滤。
- [ ] 像素图项目列表保留独立 API，或统一到资产管理 API，二选一后删除重复入口。
- [ ] DEM 模型列表明确资产类型和来源。
- [ ] LEGO 输出结果建立统一列表 API。
- [ ] 3D model fitting job 支持前端工作台需要的查询和状态刷新。
- [ ] 3D LEGO solution placement 支持编辑保存。

验收标准：

- 前端不需要在客户端硬筛大量无关资产。
- LEGO 输出结果和输入资产关系清晰。
- 可编辑拼搭方案的数据闭环成立。

## 建议实施顺序

1. 先做菜单配置化和路由重组。
2. 再做三个资产管理容器页。
3. 再拆 LEGO 构建入口。
4. 然后补 LEGO 模型管理页。
5. 最后接入 3D LEGO 可编辑工作台。

这个顺序可以保证每一步都有可见效果，同时不强迫一次性重写业务页面。

## 风险点

- `LegoDesignPage` 当前承担像素图和 DEM 两类最终设计逻辑，拆分时需要先确定哪些状态和 API 属于公共能力。
- `ModelAssetsPage` 当前是混合资产列表，必须补资产类型过滤，否则新菜单会只是表面分类。
- 3D LEGO 构建还处在 model fitting 初期，菜单可以先落入口，但工作台需要独立跟踪。
- 中文配置文件目前需要确认编码一致性，避免页面文案出现乱码。

## 暂不做

- 暂不删除旧页面。
- 暂不重写业务算法。
- 暂不合并后端数据表。
- 暂不把 3D LEGO 工作台做成简单 demo，应该沿用后端 model fitting 和 vehicle-8-wide 设计继续推进。
