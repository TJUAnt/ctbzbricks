# Component Candidate 工作台功能需求

> 所属菜单：我的模型 / 我的模型
>
> 路由：`/component-repo/candidates/:candidateId`
>
> 文档状态：当前功能
>
> 详细实现：[Component 详细设计](../../../../design/my-models/component-repo/README.md#43-candidate-到-draft-version)

## 1. 功能目标

Candidate 工作台承接完成的 Import，供 owner 查看 Draft Version 的整体 Preview 和 BOM，按需加载连接审核数据，
执行关系检测、确认/拒绝、可选验证，编辑 Component/Version 发布信息并发布。工作台也允许针对现有 Component 上传新图纸。

## 2. 权限与上下文

- Candidate、Import、Draft Version、连接分析和验证报告仅 owner 可读写。
- 页面以 candidateId 读取 Candidate，并使用服务端返回的 componentId、draftVersionId 和冻结 Snapshot，不重新解析文件。
- Candidate 必须关联 owner Component 和 Draft Version；缺失时显示稳定错误。
- 发布后的只读 Version 可以继续展示，但编辑、关系变更和发布按钮只在当前 Version 为 Draft 时启用。
- 页面操作不能修改冻结 Source、SceneSnapshot、Part Library 或结构/几何 hash。

## 3. 默认读取内容

进入页面后并发读取：

- Candidate、目标 Component 和 Draft/current Version。
- Worker 已生成的 Version GLB Preview；可旋转、缩放和重置视角。
- 冻结 BOM，包括 Part 名称/编号、数量和 geometry 可用状态。

Preview 与 BOM 独立降级：任一失败只影响自己的区域，不能隐藏另一项或 Component 主数据。默认不读取 relation、
connector 或 external interface，避免普通审核首屏承担高级分析请求。

## 4. 连接信息开关

- “加载连接信息”默认为关闭；用户明确开启后才读取 relations、free connectors 和 external interfaces。
- 加载期间禁用重复开关操作并显示状态；关闭只隐藏高级工作台，不删除或修改已有数据。
- 高级工作台展示 Candidate ID、关系数、外部 connector 数、interface 数和审核步骤。
- “检测关系”调度持久任务并等待最终结果；完成后刷新 Candidate、relations 和 connector/interface 投影。
- Draft owner 可以确认或拒绝 relation；已 confirmed 不能再次确认或拒绝，已 rejected 不能重复拒绝。
- 页面展示位置残差、旋转残差和置信度等机器数值；错误通过稳定 code/params 本地化。

## 5. 验证与发布

- owner 可以为 Draft 或 published Version 触发验证；验证报告按检查项展示状态和本地化说明。
- 验证与发布相互独立，ValidationReport 不是强制发布门禁。
- Draft 状态下可编辑 Component 名称、分类、Version 字符串和发布说明。
- Component 名称去除首尾空白后必填；分类空白保存为 null；发布说明保留作者原文与 locale。
- 发布操作先保存 Component 和 Draft Version 元数据，再发布该 Version。
- 发布成功后更新 Component current Version，并显示成功状态；并发或重复发布由服务端状态机收敛。
- 发布会产生不可变发布事件和 Feed 图片任务，但页面不等待 Feed 图片完成。

## 6. 新图纸更新

- 已有关联 Component 时显示“上传新图纸”。
- 上传会固定目标 Component，并使用 current/当前 Version 作为 baseVersionId，进入与新建相同的安全上传与进度流程。
- 新导入完成后形成新的 Candidate 和 Draft Version；不能原地改写已发布 Version。

## 7. 页面操作与反馈

- “新建导入”进入 `/component-repo/import`，“返回列表”进入 `/component-repo`。
- 所有任务或 mutation 执行期间使用统一 loading 锁，避免重复检测、验证、关系操作或发布。
- 成功操作显示本地化 notice；失败保留当前已加载 Preview/BOM 并显示错误。
- Preview 不可用时显示独立占位/错误；geometry 不可用的 BOM Part 仍保留数量并明确标记。

## 8. 验收条件

1. 非 owner 无法读取或修改 Candidate；缺少 Candidate、Component 或 Draft 时显示稳定错误。
2. 默认只加载 Preview 和 BOM，不请求连接分析；开启开关后才显示 relation/connector/interface 工作台。
3. Preview 和 BOM 任一失败时另一项与主数据仍可使用。
4. 关系检测、确认、拒绝遵守 Draft 和状态边界，完成后刷新权威数据。
5. 验证失败或未执行不自动阻止发布；发布仍必须满足 owner、Draft 和元数据校验。
6. 发布保存名称、分类、版本与原文说明，成功后 current Version 与页面状态一致。
7. 上传新图纸创建新的修订 Import，不修改旧 Version 的冻结来源。
8. 中文、英文、3D 交互、开关、任务状态、键盘和错误反馈通过浏览器验收。

## 9. 当前限制

- 连接分析仍属于高级审核能力，不在公开 Component 详情展示。
- 页面步骤条是审核进展摘要，不是强制的线性发布向导。
- 当前关系检测和验证交互等待既有任务适配器完成；没有提供跨页面统一任务中心。
- BOM 卡片的 Part 缩略图体验目前在 Component 详情更完整，Candidate 工作台主要展示 Part 身份和数量。
