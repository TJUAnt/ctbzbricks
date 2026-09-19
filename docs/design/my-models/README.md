# 我的模型详细设计索引

> 菜单组 ID：`myModels`
>
> 功能需求索引：[我的模型](../../requirements/my-models/README.md)

本目录按照“我的模型”菜单组的两个可点击菜单项组织当前实现设计。详情、导入、历史和工作台等下钻页面归入
Component 主设计，不提升为不存在的一级菜单。

## 菜单项

| 菜单项 | 路由 | 功能需求 | 详细设计 |
|---|---|---|---|
| 我的模型 | `/component-repo` | [个人仓库功能需求](../../requirements/my-models/component-repo/README.md) | [Component 详细设计](./component-repo/README.md) |
| 零件搜索 | `/part-search` | [Part Search 功能需求](../../requirements/my-models/part-search/README.md) | [Part Library 详细设计](./part-search/README.md) |

## Component 共享领域

- [Star 详细设计](./component-repo/star.md)
- [Star 产品与容量路线](./component-repo/star-design-and-roadmap.md)
- [Watch 详细设计](./component-repo/watch.md)
- [Watch 产品与容量路线](./component-repo/watch-design-and-roadmap.md)

Component Repo 的导入、进度、历史、Candidate、详情和 Watch 管理下钻页面，其实现入口与验证证据均由
[Component 主设计](./component-repo/README.md)及上述领域设计维护。
