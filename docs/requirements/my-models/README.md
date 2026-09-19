# 我的模型

> 菜单组 ID：`myModels`
>
> 当前菜单配置：`frontend/src/app/appConfig.json`

“我的模型”是当前系统管理个人 Component 和查找共享 Part Library 的一级菜单组。

## 菜单项

| 菜单项 | 路由 | 功能需求状态 |
|---|---|---|
| 我的模型 | `/component-repo` | [已记录](./component-repo/README.md) |
| 零件搜索 | `/part-search` | [已记录](./part-search/README.md) |

菜单项下钻出的详情、导入、历史记录等页面，应归入所属菜单项目录继续分层，不提升为不存在的一级菜单。

## 下钻页面索引

| 所属菜单项 | 页面 | 路由 | 功能需求 |
|---|---|---|---|
| 我的模型 | 上传导入 | `/component-repo/import` | [上传导入](./component-repo/import/README.md) |
| 我的模型 | 导入进度 | `/component-repo/imports/:importId` | [导入进度](./component-repo/import-status/README.md) |
| 我的模型 | 导入历史 | `/component-repo/imports` | [导入历史](./component-repo/import-history/README.md) |
| 我的模型 | Candidate 工作台 | `/component-repo/candidates/:candidateId` | [Candidate 工作台](./component-repo/candidate-workbench/README.md) |
| 我的模型 | Component 详情 | `/component-repo/components/:componentId` | [Component 详情](./component-repo/component-detail/README.md) |
| 我的模型 | 订阅管理 | `/component-repo/watches` | [订阅管理](./component-repo/watch-management/README.md) |
| 零件搜索 | Part 详情 | `/parts/:partLibraryVersionId/:ldrawPartNum` | [Part 详情](./part-search/part-detail/README.md) |
