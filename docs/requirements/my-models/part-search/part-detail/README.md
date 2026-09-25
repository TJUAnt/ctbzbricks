# Part 详情与 3D 查看器功能需求

> 所属菜单：我的模型 / 零件搜索
>
> 路由：`/parts/:partLibraryVersionId/:ldrawPartNum`
>
> 文档状态：当前功能；依赖已有 ready Part Preview
>
> 搜索入口：[Part Search 功能需求](../README.md)
>
> 详细实现：[Part Library 详细设计](../../../../design/my-models/part-search/README.md)

## 1. 功能目标

用户可以从 Part Search 或 Component BOM 打开一个不可变 Part Library Version 中的指定 LDraw Part，查看官方名称、
编号、逻辑尺寸、几何面数和交互式 3D Preview。详情必须固定使用链接中的 `partLibraryVersionId + ldrawPartNum`，不能
静默切换到后来生效的 active library。

## 2. 用户与读取边界

- 页面要求登录，但 Part Library 是共享官方内容，不按 owner 分区。
- `partLibraryVersionId` 与 `ldrawPartNum` 都必填；缺失或非法路径参数显示本地化无效条目错误。
- 页面先用 GET 读取既有 geometry、reviewed translation 和当前 generator 的 Preview；GET 本身不创建任务。
- Preview 未 ready 时，页面显式 POST materialize，等待 durable task 完成后重新 GET；长计算不在 HTTP 请求内执行。
- 只有 `status=ready`、geometry 存在且当前 GLB Artifact 可签名时进入完整查看器。
- 旧 generator、pending、running、failed 或对象缺失不能伪装成 ready 模型。

## 3. 页面内容

页面头部显示 Part Library 标识、查看器标题、说明和 loading/ready/error 状态。成功读取后侧栏展示：

- requested locale 的 reviewed 官方名称；缺失时回退源名称。
- 稳定 LDraw 编号。
- geometry/Preview ready 状态。
- 宽、深（stud）和高（plate）；缺失值显示 `—`，数字按 locale 格式化，并标识为标称尺寸或包围盒尺寸。
- 几何 face count。
- Three.js renderer 与统一摄影棚说明。

编号、尺寸、face count、状态和路由参数是机器数据，不翻译。

## 4. 3D 交互

- 加载 meshopt GLB 后使用统一摄影棚环境、三点光、接触阴影和材质调优。
- 用户可拖动旋转、滚轮缩放；不启用自由平移。
- “重置视角”重新按模型包围盒居中并自适应相机距离。
- renderer 适配容器尺寸和设备像素比，并在卸载时释放 requestAnimationFrame、ResizeObserver、控制器、geometry、
  material、环境贴图和 WebGL renderer。
- GLB 下载或解析失败时在舞台内显示错误，不能保留上一 Part 的模型。

## 5. 状态与错误

| 状态 | 用户可观察行为 |
|---|---|
| loading | 舞台显示加载状态，侧栏显示待加载条目 |
| ready | 展示模型、操作提示、重置按钮和完整侧栏 |
| error | 舞台显示可访问错误，不挂载残缺 Viewer |

loading 包含首次状态读取、显式 materialize 的排队/执行和最终重读。重复打开时 ready cache、pending/running task 和既有
succeeded task 按后端幂等规则复用，不能为同一逻辑输入无限创建任务。

切换 locale 或路由参数时重新读取，并废弃旧请求。错误只使用稳定本地化信息，不暴露 Storage key、LDraw 本机路径、
provider 错误或堆栈。

## 6. 多语言与可访问性

- 页面文案使用 typed semantic keys；official 名称只选择 reviewed translation，否则回退 source/contentLocale。
- 3D canvas 是装饰性视觉区域并隐藏于读屏，等价信息由侧栏文本提供。
- ready/loading/error 状态有文本表达；重置操作使用原生按钮。
- 数字按 locale 格式化，切换语言不会改变 Part 身份或 Library Version。

## 7. 验收条件

1. 从搜索或 BOM 打开的 URL 固定使用原 `partLibraryVersionId`，active library 切换后仍指向同一 Part。
2. reviewed translation 存在时显示对应名称，draft/rejected 不展示；缺失时回退源名称。
3. ready GLB 可旋转、缩放、重置并响应容器尺寸；切换 Part 后不残留旧模型或资源。
4. 尺寸缺失显示 `—`，已有尺寸显示标称/bbox 来源，face count 和单位正确，数字按当前 locale 格式化。
5. Preview 未 ready 时显式调度或复用 materialize task，成功后重读；failed、缺失 Artifact 或签名失败不挂载残缺 Viewer。
6. GET 不创建任务；POST 只调度持久任务，API 请求不执行 LDraw 解析或 GLB 生成。
7. 中文、英文、键盘、错误和响应式布局通过浏览器验收。

## 8. 当前限制

- 页面没有独立“生成 Preview”按钮；打开未 ready Part 时会自动走显式 materialize + 等待流程。
- 当前只展示整体 Part 几何、尺寸和面数，不展示 connector、collider、颜色变体或 Source 下载。
- 页面没有显式“返回搜索结果”状态保存；浏览器返回行为取决于 Part Search 页面是否仍在历史栈中。
