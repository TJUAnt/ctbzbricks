# Component 导入进度功能需求

> 所属菜单：我的模型 / 我的模型
>
> 路由：`/component-repo/imports/:importId`
>
> 文档状态：当前功能
>
> 详细实现：[Component 详细设计](../../../../design/my-models/component-repo/README.md#42-import-与-worker)

## 1. 功能目标

导入进度页以 `importId` 为恢复句柄，只读观察已经提交的持久 Import 和任务链，让用户在刷新页面后仍能看到上传、
解析/BOM 和 3D Preview 三个阶段。页面不补发任务、不重新解析文件，也不把队列等待伪装成算法完成度。

## 2. 三阶段进度

| 阶段 | 完成条件 | 页面表达 |
|---|---|---|
| 文件上传 | upload session complete，Import 已建立 | 进入页面时固定为已完成 |
| 解析与 BOM | parse task succeeded，SceneSnapshot/BOM/Candidate/Draft 已持久化 | pending、active 或 complete |
| 3D Preview | Draft Version 的当前 Preview Artifact ready 且 verified | pending、active 或 complete |

- 页面每 2 秒轮询 owner-scoped Import 聚合状态。
- 同时尝试读取 parse task 和可选 preview task 的进度；Task 读取失败只缺少阶段细节，不放宽 Import 的 ready 条件。
- 总体百分比是稳定的阶段映射：上传约占首段、解析占中段、Preview 占末段；只有 Preview ready 才显示 100%。
- Task 提供结构化进度 code/params/percent 时显示本地化细节；否则展示阶段级说明。

## 3. 状态转换

- `processing`：任一必要 verify/parse/preview 阶段仍 queued/running，继续轮询。
- `ready`：Import、Snapshot、BOM、Draft 和 verified Preview 全部就绪；必须带 `candidateId`，页面以 replace 导航进入
  [Candidate 工作台](../candidate-workbench/README.md)。
- `failed`：任一必要阶段不可恢复地失败或必要 Artifact 无效；停止轮询并显示结构化 failure。
- Import ready 但缺少 candidateId 属于数据不一致，显示失败，不进入不完整工作台。
- 路由缺少 importId 或 Import 不可见时显示本地化错误。

## 4. 权限与恢复

- 只有 Import owner 可以读取状态和关联 Task；非 owner 不得通过 ID 判断资源是否存在。
- 刷新页面后从 PostgreSQL durable 状态恢复，不依赖上传页内存。
- 离开页面不会取消任务；再次从导入历史进入时继续观察同一 Import。
- 页面卸载后必须停止定时器，旧请求不得导航或覆盖后续页面。
- failure 只展示稳定 `code + params` 的本地化结果，不暴露堆栈、文件系统路径、Storage key 或 Worker 原始错误。

## 5. 验收条件

1. 页面显示上传、解析/BOM、3D Preview 三个阶段和可访问总体进度条。
2. queued/running 显示处理中但不声称精确算法进度；有任务进度时在所属阶段内映射。
3. 刷新后能继续观察同一 importId，不创建第二个 Task 或 Preview。
4. Import ready 且 candidateId 有效时 replace 到 Candidate 工作台，浏览器返回不会反复进入已完成状态页。
5. Import failed、无权限、缺少 ID 或聚合数据不一致时停止轮询并显示稳定错误。
6. Task 细节读取失败不把未 ready 的 Import 判为 ready。
7. 中文、英文、读屏进度和页面切换清理通过验证。

## 6. 当前限制

- 页面展示阶段级总体进度，不提供 Worker 预计完成时间或吞吐预测。
- 当前失败页没有直接重新执行持久任务的按钮；用户可返回仓库或重新上传，后台重试遵守任务系统策略。
- 当前 ready 自动进入工作台，不能停留在完成摘要页。
