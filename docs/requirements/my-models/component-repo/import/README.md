# Component 上传导入功能需求

> 所属菜单：我的模型 / 我的模型
>
> 独立路由：`/component-repo/import`
>
> 同类入口：个人仓库和 Candidate 工作台中的“上传 Component/上传新图纸”弹窗
>
> 文档状态：当前功能
>
> 详细实现：[Component 详细设计](../../../../design/my-models/component-repo/README.md#4-创建与修订的异步主链路)

## 1. 功能目标

用户可以上传 Studio 或 LDraw 图纸，新建 Component，或基于现有 Component/Version 创建一次修订导入。浏览器只负责
创建上传会话、把文件直传到服务端指定的对象存储位置并声明完成；解析、BOM、Candidate、Draft Version 和 Preview
生成由持久任务继续执行。

## 2. 入口与导入类型

| 入口 | 导入类型 | 目标信息 |
|---|---|---|
| `/component-repo/import` | 新建 Component | 不指定目标 Component 或基准 Version |
| 个人仓库上传弹窗 | 新建 Component | 不指定目标 Component 或基准 Version |
| Candidate 工作台“上传新图纸” | 更新现有 Component | 固定 `targetComponentId`，以 current/当前 Version 作为 `baseVersionId` |

- 所有入口必须使用同一安全上传协议，不能因 UI 不同绕过文件、owner 或 lineage 校验。
- 更新导入只能指向当前 actor 拥有的用户 Component 和合法基准 Version。
- 上传完成后统一进入 `/component-repo/imports/:importId`，不在上传界面等待解析或 Preview 完成。

## 3. 文件选择

- Source 文件必填，接受 `.io`、`.ldr`、`.mpd`，扩展名匹配不区分大小写。
- Exchange 文件可选，只接受 `.ldr` 或 `.mpd`；主要用于 `.io` Source 需要显式交换文件的场景。
- 页面向用户说明单个 Component 文件最大 100 MB；服务端仍负责实际大小、MIME、hash 和扩展名校验。
- 上传弹窗支持点击选择和拖放 Source；不符合支持扩展名的拖放文件不得进入已选择状态。
- 用户可以在开始前替换选择。上传进行中禁止关闭弹窗、重复提交或更换文件。

## 4. 上传协议与进度

1. 浏览器计算文件大小和 SHA-256，并携带创建时的 locale/timezone 请求 upload session。
2. API 返回当前 owner、会话和文件角色绑定的精确 bucket/object path。
3. 浏览器使用当前用户会话直传每个文件，禁止 upsert，不能自行修改目标路径。
4. 浏览器调用 complete；服务端核对对象存在性、大小、MIME 和会话状态，并持久创建 Artifact、Import 与任务依赖。
5. complete 返回 `202 {importId,taskId,status}` 后，上传交互结束并导航到导入进度页。

上传弹窗展示从创建通道、Source 上传、Exchange 上传到 complete 的传输进度。该百分比只描述浏览器上传阶段，不能冒充
解析或 Preview 的完成度。

## 5. 安全与恢复

- Storage 目标由 API 生成，用户不能在请求中指定 bucket、key、owner 或 Artifact ID。
- 只有会话仍 pending、未过期、属于当前 actor 且路径完全匹配时，Storage RLS 才允许 INSERT。
- API 不接收文件正文，不在 HTTP 请求内解析 Studio/LDraw 或生成 GLB。
- complete 必须幂等；重复调用返回既有 Import/task，不能创建重复导入链。
- 浏览器关闭或导航离开不会取消已经 complete 的持久任务；用户可从导入历史恢复进度入口。
- 上传失败时保留所选文件信息和本地化错误，允许用户重试；补偿删除由服务端负责，客户端没有通用 Artifact 删除权限。

## 6. 状态与可访问性

| 状态 | 用户可观察行为 |
|---|---|
| 未选择 Source | 主提交按钮禁用 |
| 已选择 | 显示文件名和本地化文件大小 |
| 上传中 | 显示进度条、阶段消息和百分比，关闭与重复提交禁用 |
| 上传失败 | 显示结构化错误，提供关闭和重试 |
| complete 成功 | 立即进入导入进度页 |

弹窗使用 `role=dialog`、标题关联、Escape/背景关闭规则和可访问进度条；上传中 Escape 和背景点击不能关闭。所有标签、
状态和错误使用 typed semantic keys，文件名、hash、扩展名和机器状态不翻译。

## 7. 验收条件

1. `.io/.ldr/.mpd` 可作为 Source，Exchange 只接受 `.ldr/.mpd`，没有 Source 时不能提交。
2. 新建和更新导入都由 API 校验 owner 和基准 Version，不能修改他人 Component。
3. Storage 只能写 API 分配的当前会话精确路径，伪造或过期路径被拒绝。
4. 上传中显示传输阶段进度且无法重复提交；complete 后不等待 Worker，直接进入对应 importId 状态页。
5. complete 重试不创建第二条 Import；网络或 Storage 失败显示可恢复错误。
6. 页面关闭后持久任务继续，用户可从导入历史重新进入进度页。
7. 中英文、键盘、拖放、进度条和错误状态通过浏览器验收。

## 8. 当前限制

- 当前只支持 Studio/LDraw 文本与归档格式，不支持任意 CAD、图片或压缩包。
- 浏览器必须保持打开直到文件直传和 complete 结束；complete 后才允许离开而不影响任务。
- 独立 `/component-repo/import` 页面是较简化入口，个人仓库弹窗提供更完整的上传进度体验；两者共享后端契约。
