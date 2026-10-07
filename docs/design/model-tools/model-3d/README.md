# 模型小工具 / 3D 模型构建 LEGO：菜单级设计草案

> 状态：方案阶段，未实现。当前没有本功能的菜单项、确定路由、HTTP 契约或端到端求解器。
>
> 功能需求：[3D 模型构建 LEGO](../../../requirements/model-tools/model-3d/README.md)；算法研究：[Shape 分块总览与专题](../../lego_shape_decomposition_design.md)。

## 1. 归属与范围

计划在“模型小工具”下设置独立的 3D 模型构建 LEGO 入口，与现有 2D 模型工具并列。本文作为该用户可访问功能的设计入口；Shape 分块总览及其专题只负责 Split / Build 的算法问题。现有 `/direct-import`、`/lego-builder` 等路由不能仅凭名称当作本功能的已实现入口，是否复用应在产品流程确定后检查其实际能力。

整体目标是输入连续 3D 模型与目标物理尺寸，输出可拼搭的 LEGO 模型并支持单文件 LDraw 导出，同时保持等比缩放。当前优先验证从 Shape 到 Split / Build 的决策，尚未设计完整 Build、Merge 与导出工作流。

## 2. 设计链路与阶段边界

```text
连续 3D 模型 + 目标尺寸
  → 目标 LEGO 尺度下的几何分析
  → 候选主轴、截面与几何规律拟合
  → 候选分块及 Split / Build 决策
  → 局部 LEGO 求解（后续阶段）
  → 组合与可拼搭验证（后续阶段）
  → LDraw 导出（后续阶段）
```

第一阶段以局部 Shape benchmark 验证四种 Pattern 的覆盖率和候选切分的收益，不把 Box 填充率、Skeleton 分叉或任一拟合分数当作硬停止条件。Shape 分块专题中的公式、阈值与候选生成方法均为待实验假设。

## 3. 待定义的实现契约

| 边界 | 当前结论 | 实现前必须确定 |
|---|---|---|
| 前端调用 | 计划设置独立菜单入口；当前未添加 | 路由、上传格式、尺寸输入、预览与结果状态 |
| HTTP 接口 | 尚未定义 | 创建、查询、取消、下载等操作是否需要独立 API，以及请求与响应字段 |
| Go 服务与任务 | 几何分析和求解可能耗时，不应放在有界 HTTP Handler 内 | 持久任务阶段、重试/取消语义、资源上限与 Worker 边界 |
| 持久化与对象存储 | 尚未定义新表或 Artifact | 用户所有权、源文件和派生产物分离、结果版本与清理策略 |
| 权限 | 尚未定义具体动作 | 上传、查看、任务状态、下载和删除均按 owner 授权 |
| i18n | 沿用仓库既有体系 | 页面语义 key、任务 `code + params`、冻结 locale/timezone 和导出资源版本 |

上述是后续设计决策，不是已经存在的接口或数据结构。若未来修改 Component Repo、共享任务或 Go 后端，先执行仓库规定的迁移预读，并按实际契约更新 `docs/api.md` 与迁移进度。

## 4. 验证路径与当前证据

当前证据只有[Shape 分块总览与专题](../../lego_shape_decomposition_design.md)中的推理及待验证问题，没有 benchmark、求解器对照、接口测试或部署验收。下一步按“局部 Shape 数据集 → Pattern 覆盖率 → Split 收益 → 真实 LEGO 求解器相关性”的顺序建立证据；只有实验支持后才固定 SplitGain 与产品交互。

## 5. 编号清理项

| 编号 | 代码/文档证据 | 影响与依赖阶段 | 客观关闭条件 |
|---|---|---|---|
| MODEL3D-DOC-01 | `frontend/src/app/appConfig.json` 的 `modelTools.items` 当前只有 `model2d`；`docs/design/lego_shape_decomposition_design.md` 此前没有菜单级归属 | 原方案难以从菜单索引发现；本轮文档归属已补齐，菜单落地依赖产品交互与算法验证 | 确定名称和路由，新增对应菜单及页面，并用真实前端调用、API、权限和验证证据更新本文 |
| MODEL3D-DOC-02 | `frontend/src/app/appConfig.json` 已有若干 3D 相关页面 ID 与路由，但当前 `modelTools.items` 未挂载本方案 | 名称相近易造成误认为现有页面已实现 Shape → LEGO；复用决策依赖功能范围确定 | 逐一核对现有页面能力，记录复用或独立实现的决定，并用可运行流程关闭 |
