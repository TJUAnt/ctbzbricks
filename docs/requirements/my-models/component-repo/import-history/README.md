# Component 导入历史功能需求

> 所属菜单：我的模型 / 我的模型
>
> 全局路由：`/component-repo/imports`
>
> 复用位置：Component 详情的“导入历史”页签
>
> 文档状态：当前功能

## 1. 功能目标

导入历史为当前用户提供可恢复、可搜索的持久 Import 记录。全局页面显示全部 owner Import；Component 详情中的复用
列表通过 `componentId` 收窄为该 Component 的新建和更新导入。

## 2. 列表与筛选

- 每页 20 条，提供上一页、下一页和当前页/总页数。
- 搜索支持 Source 原始文件名或完整/部分 Import ID；输入变化后回到第一页。
- 状态筛选提供全部、处理中、已就绪、失败，并显示相同查询范围下的状态数量。
- 列表只读取当前 actor 的 Import；`componentId` 同时关联新建导入形成的 Component 和显式更新目标。
- Version 后续软删除不能抹去 Import 与 Component 的历史关联。

每条记录展示 Source 文件名、大小、Import ID、导入类型（新建/更新）、聚合状态、创建时间、持续时间和可选结构化
失败原因。不得返回或展示 Storage provider、bucket、object key、Task payload 或内部路径。

## 3. 状态与自动刷新

- 聚合状态只使用 `processing/ready/failed`，口径与单条 Import 状态页一致。
- 只要当前可见页面存在 processing 记录，每 5 秒刷新整页列表；文档不可见时暂停轮询。
- 没有 processing 记录时不建立定时轮询；用户仍可手动刷新。
- 刷新期间保留已有列表并设置 busy 状态，避免整表闪空。
- 状态和筛选改变后，旧请求不能覆盖新的页面条件。

## 4. 结果入口

- processing 或 failed：进入对应[导入进度页](../import-status/README.md)查看进度或失败详情。
- ready 且已有 Component：进入[Component 详情](../component-detail/README.md)。
- ready 且有 Candidate、尚未形成可用 Component 结果：进入[Candidate 工作台](../candidate-workbench/README.md)。
- 关联字段异常缺失时回到 Import 状态页，不构造猜测资源链接。

## 5. 全局页面操作

- “返回列表”回到 `/component-repo`。
- “上传 Component”进入 `/component-repo/import`。
- Component 详情内的复用列表不重复显示全局页头和上传入口。

## 6. 状态、错误和可访问性

| 场景 | 用户可观察行为 |
|---|---|
| 初次加载 | 显示导入记录加载状态 |
| 从未导入 | 显示没有导入记录 |
| 当前筛选无结果 | 显示没有匹配记录 |
| 请求失败 | 显示本地化错误并允许手动刷新 |
| 处理中 | 行状态与持续时间更新，页面可见时自动轮询 |

列表使用表格语义，筛选按钮表达当前状态，分页按钮在边界和加载时禁用。用户文件名原样显示；状态、日期、数字和错误
按当前 locale 格式化。

## 7. 验收条件

1. 用户只能看到自己的 Import，搜索、状态、componentId 和分页条件组合正确。
2. 状态数量、总数、总页数和行使用同一聚合口径。
3. processing 记录在页面可见时每 5 秒刷新，不可见或无 processing 时不持续轮询。
4. ready/processing/failed 分别进入正确结果或进度页面，不猜测缺失关联。
5. 新建和更新 Import 都能在目标 Component 详情中回溯，Version 软删除后历史仍保留。
6. 失败只显示结构化本地化信息，不泄露 Storage 或 Task 内部数据。
7. 中文、英文、表格、筛选、分页和空状态通过浏览器验收。

## 8. 当前限制

- 当前使用页码分页和精确总数；如果单 actor Import 历史接近大规模，需要重新验证深页成本或改用 keyset。
- 搜索随输入变化请求，尚未提供日期范围、导入类型或文件 MIME 筛选。
- 持续时间是基于创建/开始/完成时间的当前显示值，不是任务 CPU 时间或性能 SLO。
