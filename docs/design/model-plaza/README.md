# 模型广场详细设计索引

> 菜单组 ID：`modelPlaza`
>
> 功能需求索引：[模型广场](../../requirements/model-plaza/README.md)

“模型广场”菜单组当前只有一个同名菜单项。公共动态与个人订阅属于同一页面中的页签，不拆成虚构的侧边菜单项。

| 菜单项 | 路由 | 功能需求 | 详细设计 |
|---|---|---|---|
| 模型广场 | `/model-plaza` | [模型广场功能需求](../../requirements/model-plaza/model-plaza/README.md) | [组件广场详细设计](./model-plaza/README.md) |

公共 Feed 的事件窗口、成员资格和分页 SQL 仍由[公共 Feed 专项设计](../../component_repo/public_feed.md)维护；Watch
关系及个人订阅窗口由[Watch 详细设计](../my-models/component-repo/watch.md)维护。
