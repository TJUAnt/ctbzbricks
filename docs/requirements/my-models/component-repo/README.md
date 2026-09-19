# 个人 Component 仓库功能需求

> 菜单路径：我的模型 / 我的模型
>
> 菜单项 ID：`myModels`
>
> 入口路由：`/component-repo`
>
> 文档状态：当前功能；部署和浏览器验收状态见“已知限制”
>
> 详细实现：[Component 详细设计](../../../design/my-models/component-repo/README.md)
>
> 关联领域：[Star](../../../design/my-models/component-repo/star.md) · [Watch](../../../design/my-models/component-repo/watch.md)
>
> HTTP 契约：[Component Repo API](../../../api.md)

## 1. 功能目标

个人 Component 仓库用于管理当前用户拥有的 Component，并提供收藏视图、目录分组、复合搜索、状态筛选、分页、
版本入口、上传导入和下钻管理页面。它不承载公共发布动态；公开浏览和个人订阅动态属于“模型广场”。

## 2. 用户与数据边界

- 页面要求登录，个人仓库与 Group 只能读取当前 actor 的数据。
- “我的组件库”只包含当前用户拥有且未删除的 Component；root Group 代表全部自有 Component。
- “我的收藏”包含当前用户 Star 且仍公开可见的非本人 Component；Star 不授予额外可见性。
- official Component 的名称、描述和标签只选择 reviewed translation；用户内容保持原文及 `contentLocale`。
- Component、Version、Import、Group、Star、Watch 的最终权限和状态由 Go API 决定，前端显示状态不能替代服务端校验。

## 3. 顶部视图与入口

页面提供三个入口：

| 入口 | 行为 |
|---|---|
| 我的组件库 | 显示当前选中 Group 的直接 Component 成员，支持 Group、状态和多条件搜索 |
| 我的收藏 | 显示当前用户收藏的公开 Component，支持名称/ID/尺寸搜索与分类筛选 |
| 我的订阅 | 进入独立的[订阅管理页面](./watch-management/README.md) |

“我的组件库”和“我的收藏”是当前页面内状态，不写入 URL；刷新页面会回到默认“我的组件库”。页面还提供：

- “导入历史”进入[导入历史页面](./import-history/README.md)。
- “上传 Component”打开上传弹窗；完成直传后进入[导入进度页面](./import-status/README.md)。
- 无自有 Component 时，空状态提供首次上传入口。

## 4. 状态概览

页面展示当前视图和筛选范围内的总数、草稿数和已发布数：

- 自有 Group 视图的状态统计与列表使用相同 Group、搜索和可见性条件。
- “草稿”对应 Component 当前展示投影为 Draft；“已发布”对应 active。
- 收藏视图只包含公开 active Component，不能把 Import/Task 的 processing、ready、failed 当成 Component 状态。
- 精确总数、总页数和列表必须使用同一候选语义，不能用固定前 N 条伪装完整集合。

## 5. Group 目录

### 5.1 层级和选择

- 每个用户拥有一个不可删除、不可改名的 root Group，表示全部自有 Component。
- 用户可在 root 或 custom Group 下创建子 Group，名称必填、去除首尾空白、最长 100 个字符。
- 最大层级深度为 5；创建或移动后超过限制时必须显示稳定冲突错误。
- custom Group 按 `sortOrder` 和创建时间显示；用户可以展开、折叠和选择目录。
- custom Group 只表示直接 membership，不自动把子 Group 成员计入父 Group 的直接数量。

### 5.2 管理操作

- 用户可以创建、改名、删除 custom Group；root Group 不提供改名或删除。
- 删除 Group 前必须确认；删除目录不能删除其中的 Component。
- 支持拖放到另一 Group 内，或移动到目标 Group 前后；不能把 Group 移入自身或后代。
- “添加子目录”和“添加 Component”收进目录的添加菜单；root 已包含全部自有 Component，不提供添加成员操作。
- Group membership 编辑支持把可用 Component 加入或移出 custom Group；同一 Component 可属于多个 custom Group。
- owner 自有、当前收藏和该 Group 既有成员组成可选候选集合；候选必须服务端分页，不能只加载固定首批后声称完整。

## 6. 自有 Component 搜索与筛选

- 每页 20 条，页面变更时显示上一页、下一页和当前页/总页数。
- 搜索输入提交后固化为条件标签；最多 8 个非空条件，条件之间按 AND 组合。
- 重复条件忽略大小写去重；清除一个标签只移除自身，其余条件继续生效。
- 普通条件匹配 Component 名称或 ID。
- 完整 `a x b` 或 `a x b x c`（兼容 `x/X/×` 和小数）按逻辑尺寸匹配；尺寸轴顺序归一化。
- 三维尺寸逐维使用严格开区间 `(目标-1, 目标+1)`；二维尺寸尝试三组平面配对。恰好相差 1 不命中。
- 缺少完整逻辑尺寸的 Component 不满足尺寸条件。
- 状态筛选提供全部、草稿、已发布；更改搜索、状态或 Group 后回到第一页。
- 输入与筛选变化后约 300 ms 发起请求；旧请求返回时不得覆盖较新的选择。

## 7. 收藏视图

- 收藏按 `starredAt` 倒序分页，每页 20 条，并返回精确总数和总页数。
- 收藏视图只有一个搜索字符串；提交新条件时替换旧条件，不沿用自有 Group 的多标签 AND 语义。
- 完整二维或三维尺寸表达式进入尺寸匹配；普通字符串匹配名称、部分 ID 或 reviewed official translation。
- 分类按规范化后的精确值筛选，最长 128 个字符；搜索和分类同时存在时按 AND 组合。
- 取消收藏后条目立即从收藏视图移除；若当前页只剩该条且不是第一页，成功后回到上一页。
- Star 失败时重新读取权威列表，不能永久保留错误的乐观状态。

## 8. 列表内容与行操作

每行展示 Component 名称、缩短 ID、逻辑尺寸、状态、上传或收藏时间，以及以下操作：

- “详情”进入[Component 详情](./component-detail/README.md)。
- 非 owner 显示 Star/Unstar 按钮和数量；owner 只显示 Star 数量，不能收藏自己。
- owner、已收藏 Component，或 custom Group 中的条目可以打开 Group membership 编辑器。
- “查看版本”展开 Version 列表，显示版本、修订号和当前/草稿状态。
- Version 更多菜单提供 Source 下载；只有服务端声明可删除的 Draft 才允许删除，current/published 历史不可删除。
- 所有写操作在处理中禁止重复提交，并显示本地化成功或错误反馈。

## 9. 加载、空状态与错误

| 场景 | 用户可观察行为 |
|---|---|
| Group 树加载 | 目录区域显示独立加载状态 |
| 列表首屏加载 | 显示列表加载状态，不展示旧 Group 的结果 |
| 自有仓库为空 | 提示上传第一个 Component，并提供上传按钮 |
| 当前筛选无结果 | 提示调整搜索词、状态或 Group |
| 收藏为空 | 提示前往可见 Component 进行收藏 |
| 收藏筛选无结果 | 提示调整收藏搜索或分类条件 |
| Version 加载失败 | 只在展开区域显示失败，主列表保持可用 |
| 写操作失败 | 显示稳定本地化错误并重新读取必要的权威状态 |

切换 locale 或手动刷新时重新读取 Group 和当前列表；错误消息不得暴露 SQL、Storage key、路径或堆栈。

## 10. 下钻页面

- [上传导入](./import/README.md)
- [导入进度](./import-status/README.md)
- [导入历史](./import-history/README.md)
- [Candidate 审核与发布](./candidate-workbench/README.md)
- [Component 详情](./component-detail/README.md)
- [订阅管理](./watch-management/README.md)

## 11. 验收条件

1. 登录用户只能在自有仓库读取和管理自己的 Group、Draft 与 Import。
2. root Group 显示全部自有 Component；custom Group 只显示直接成员，删除 Group 不删除 Component。
3. 创建、改名、拖放、删除 Group 与 membership 编辑均遵守最大深度、循环和 owner 边界。
4. 自有视图多个搜索标签按 AND 生效，状态统计、总数和页面使用相同条件。
5. 名称/ID和二维/三维尺寸搜索按当前规则工作，尺寸缺失或边界恰差 1 时不误命中。
6. 收藏视图按收藏时间倒序，搜索与分类组合生效，取消收藏后分页正确收敛。
7. owner 不显示可操作 Star，非 owner 的 Star 状态和数量在成功或失败后回到权威值。
8. Version 展开、Source 下载和 Draft 删除互不阻塞主列表；current/published Version 不能删除。
9. 页面刷新、locale 切换、快速切换 Group 或条件时，旧请求不能覆盖新状态。
10. 中文和英文界面、键盘操作、焦点、对话框、表格语义、空状态和响应式布局通过浏览器验收。

## 12. 已知限制

- 仓库已实现个人目录、Group、收藏、版本、上传与下钻主链；真实应用发布和完整浏览器视觉验收仍需与当前 schema、
  Worker 和 Storage 配置联合执行。
- “我的组件库/我的收藏”页签和当前 Group、搜索条件没有写入 URL，刷新后不能恢复现场。
- 当前 Group 移动主要依赖拖放，键盘等价排序交互尚未形成独立产品契约。
- Version 列表仍为小集合读取；容量增长到需要服务端连续分页时必须重新审查当前展开交互。
- Component 软删除会立即退出可见列表，但历史 Version、Import、Artifact 和 Storage object 按保留策略继续存在。

实现偏移、清理项与关闭条件以[Component 详细设计](../../../design/my-models/component-repo/README.md)为准；本需求文档不把仓库
代码完成、数据库迁移和生产发布写成同一状态。
