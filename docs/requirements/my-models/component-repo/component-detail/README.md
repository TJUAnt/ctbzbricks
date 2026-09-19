# Component 详情功能需求

> 所属菜单：我的模型 / 我的模型
>
> 路由：`/component-repo/components/:componentId`
>
> 文档状态：当前功能；逐步拼搭说明书不在当前能力内
>
> 详细实现：[Component 详细设计](../../../../design/my-models/component-repo/README.md#32-详情)

## 1. 功能目标

Component 详情页为 owner 和有权读取公开 Component 的用户提供版本化 3D Preview、BOM、验证结果、Source 下载、
Version/Import 历史和详情操作。owner 还可以发布 Draft、验证、比较版本及删除 Component；非 owner 可以 Star 和 Watch。

连接点、relation 和 external interface 属于 Candidate 审核信息，详情页不请求也不展示。

## 2. 可见性与版本选择

- owner 可读取自己的未删除 Component 及 Draft/非 Draft Version。
- 非 owner 只可读取 active Component 的非 Draft Version；不可见资源统一返回 not-found，不泄露是否存在。
- 页面优先选择比 current Version 更新的 Draft；否则选择 current Version；都不存在时使用首个可见 Version。
- Component 和 Version 是主数据。Preview、BOM、ValidationReport 和 Group 是可独立降级的附加区域。
- owner 才读取私有 Group tree 和 membership；公开详情不得探测他人的目录结构。

## 3. 顶部操作权限

| 操作 | owner user Component | 非 owner 可见 Component |
|---|---|---|
| Star/Unstar | 不显示 | 显示并允许乐观切换 |
| Watch/Unwatch | 不显示 | 显示 `releases_only` Watch 切换 |
| 下载图纸源文件 | 当前 Version 可见时显示 | 当前 Version 可见时显示 |
| 验证 | Draft 或 published 且有关联 Candidate 时显示 | 不显示 |
| 发布 | 当前选中 Version 为 Draft 时显示 | 不显示 |
| 删除 Component | 放在发布右侧“…”更多菜单 | 不显示 |

- 所有写操作以服务端 `ownedByActor` 和资源状态为准，不能只依赖浏览器用户 ID。
- Star/Watch 使用即时反馈，失败后重新读取完整详情恢复权威状态。
- 下载必须由 API 校验 Version 可见性与 Artifact owner/provider/bucket/key 后签发短期 URL，不暴露永久地址。

## 4. 3D Preview 与概览

- 页面读取当前 Version 已有、当前 generator 且 verified 的 GLB，不通过 GET 隐式创建 Preview。
- Preview 支持拖动旋转、滚轮缩放和重置视角，并使用统一 Studio 摄影棚材质和灯光。
- Preview loading/stale/failed 只影响预览区域，不能隐藏主数据或 owner 操作。
- 页面显示 Component 名称、Version、状态、验证通过状态和 owner 自定义 Group 标签。
- 概览至少展示冻结 BOM 的 Part 实例总数；Part count 是叶子实例总量，不是 Part 种类数。

## 5. BOM 与 Part 下钻

- BOM 读取解析时冻结的数据，不在详情 GET 中重新解析 Source。
- 每种 Part 展示 reviewed 官方名称或源名称、LDraw 编号、数量、geometry 状态和可选缩略图。
- 卡片进入视口附近后才下载 ready Part GLB，通过共享 renderer 生成静态缩略图；失败回退占位，不阻断 BOM。
- `failed/missing` geometry 的 Part 仍保留在 BOM，并明确显示几何不可用。
- 存在冻结 `partLibraryVersionId` 时，点击卡片进入对应不可变[Part 详情](../../part-search/part-detail/README.md)。

## 6. 验证

- owner 可为 Draft 或 published Version 触发验证；验证任务与发布保持独立。
- 已有关联 ValidationReport 时显示总状态和每项结构化检查结果。
- ValidationReport 读取失败只隐藏/降级验证区域，不影响已发布内容、Preview 或 BOM。
- 未验证或验证未通过不是强制发布门禁；页面不得暗示验证一定阻止发布。

## 7. Version Diff

- 只有 owner 可以比较 Version 与其 Import 冻结的 `baseVersionId`；首个 Version 与空基线比较。
- 后端从两侧 SceneSnapshot 计算 BOM 与实例变化，不读取 GLB、不写数据库、不创建任务。
- 前端只读加载已有前后 Preview，使用三维叠加展示 added、removed、moved、color changed、replaced 和 ambiguous。
- 显示变化统计、图例和最多前 100 条可聚焦变化；更多变化明确提示未显示数量。
- Diff 结果被后端截断时必须警告；Preview 缺失时显示独立错误，不生成新 Preview。
- 切换 Component 或关闭比较时取消/废弃旧请求和聚焦状态，避免把旧 Diff 投影到新页面。

## 8. Version 与 Import 历史

详情下方提供两个页签：

- Version 历史：显示版本号、ID、状态；owner 可比较每个 Version；更多菜单可下载 Source，并仅在服务端允许时删除 Draft。
- Import 历史：复用 owner-scoped [导入历史](../import-history/README.md)，只显示与当前 Component 关联的记录。

current Version、published/deprecated/archived 历史不可通过当前删除入口删除。删除唯一 Draft 允许，但必须使用更明确的
确认文案；删除 Version 保留共享 Artifact。

## 9. Component 删除

- 仅 owner 的 user Component 可删除；入口收进“…”菜单，避免成为与发布同等级的主操作。
- 删除前显示确认对话框，明确 Component 将退出可见列表但历史 Artifact 按策略保留。
- 成功后返回个人仓库；失败关闭进行状态并显示本地化错误。
- 服务端执行软删除并创建关系清理任务；公开列表、详情、Star 和 Watch/Feed 立即按可见性隐藏，后台再关闭 Watch、删除 Star。
- 删除不物理删除 Version、Import、Artifact、普通历史 Task 或 Storage object。

## 10. 状态、错误与多语言

- 主数据加载失败显示页面级错误；Preview、BOM、Validation、Diff 和 Import 历史各自独立降级。
- 用户名称、描述和发布说明保持原文；official Component/Part 只选择 reviewed translation。
- ID、Version、revision、hash、状态和尺寸是机器值，不翻译；日期和数字按 locale 格式化。
- 所有按钮、菜单、对话框、页签和 3D 状态必须使用 typed semantic key 与可访问语义。
- API 错误只使用稳定 `code + params`，不展示 SQL、Storage key、内部路径或堆栈。

## 11. 验收条件

1. owner 和非 owner 只看到权限允许的 Version 与操作；公开详情不读取 owner Group 或 Candidate 连接分析。
2. Preview、BOM 或验证任一失败时，其他区域和主数据仍可用。
3. BOM 显示名称、编号、数量、geometry 状态和缩略图，并链接到冻结库 Part 详情。
4. 非 owner 可 Star/Watch，owner 不显示自己的 Star/Watch；失败后恢复权威状态。
5. 图纸 Source 下载使用短期授权 URL，不能通过猜测 Version ID 绕过可见性。
6. owner 可发布 Draft、执行可选验证，并只删除服务端允许的 Draft Version。
7. Version Diff 使用声明基线，正确显示统计、三维变化、截断和缺失 Preview 状态。
8. Component 删除位于更多菜单并二次确认，成功后退出详情且关系清理异步进行。
9. Version/Import 页签切换不丢失 Component 主数据，Import 列表只包含当前 Component。
10. 中文、英文、键盘、焦点、对话框、3D、缩略图和响应式布局通过浏览器验收。

## 12. 当前限制

- 当前“图纸源文件”是 Studio/LDraw Source 下载，不是逐步拼搭说明书；说明书生成仍是明确清理项。
- Diff 当前只允许 owner，即使 Version 已公开也不向非 owner 提供。
- 前端最多展示 100 条 Diff 变化；后端还有 50,000 展开实例和 10,000 明细硬边界。
- 历史 Preview generator 过期时读取为 stale，普通详情不会自动重建。
