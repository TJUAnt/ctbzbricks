# 多语言资源发布记录

资源版本只追加、不复用。前端资源内容由 SHA-256 锁定，服务端导出版本写入每个正式产物。

## frontend-2026.07.21.3

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：826
- 内容哈希：`105dd3915908141531afb960d88b0bb1f0a5dce2dd92531b2d2e0a18daef055d`
- 新增按 Component/Part 类型展示的详情页标题、加载状态、几何说明及稳定错误资源。
- `itemType`、`itemId`、URL、LDraw 编号、尺寸和网格字段保持机器值，不参与翻译；详情名称继续按官方内容规则选择已审核译文。

## frontend-2026.07.21.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：815
- 内容哈希：`af26a0aec6db4538f518fe0764c62414c31e9d24b2b0f850f427f0cfcda0f79c`
- 召回卡片精简为零件图示、源名称和零件编号，并新增每行显示数量设置文案。
- 图片 URL 和每行数量为机器数据，不参与翻译。

## frontend-2026.07.21.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：814
- 内容哈希：`81bd0e1120f35ced3e8cb5329d80ab9367d1611088e679ff9cb8d3307ba203bf`
- 组件与零件召回由类型模糊匹配调整为源名称关键词匹配，更新搜索框、结果匹配状态和空结果提示文案。
- 候选名称保持源内容，不参与本地化选择；`key`、尺寸和评分等机器字段保持稳定且不翻译。

## frontend-2026.07.20.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：814
- 内容哈希：`ead7ba626b5609792d6397e24b30ac954e4c200df940f4494e504b4f93ba73cf`
- 组件库移除人工批准环节，新增编辑/发布版本、历史版本、上传新图纸和指定版本三维预览文案。
- 新增发布校验、版本冲突、零件库不可用及连接关系完整性错误资源。

## frontend-2026.07.19.5

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：801
- 内容哈希：`433b433888bfa00fed72774bf47eee63024bb81e190f265ac8923147ae709ddf`
- 允许 3D 查看器直接预览尚未批准为正式 Component 的已解析仓库条目。

## frontend-2026.07.19.4

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：801
- 内容哈希：`df0733292d6bd09d89d0a0b25ff62a394fd8c184a3840c5814b86db12149c5ee`
- 允许 3D 查看器预览数据库首个草稿 Component，并补充真实组件状态与版本回退文案。

## frontend-2026.07.19.3

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：800
- 内容哈希：`f3ce4cfb3f5d05455cd605cd589047f73ea56dda7f7cc5818f9f74bcaf13877c`
- 将 3D 查看器切换为数据库首个启用 Component，并新增加载状态、结构信息及预览错误文案。

## frontend-2026.07.19.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：788
- 内容哈希：`1a9e41c3b3fcae5bb3cb20a6118ce3621887c4fd39e17a3d8dbfbb4773cff427`
- 新增零件 3D 查看器页面的导航、交互提示、尺寸与渲染状态文案。

## frontend-2026.07.19.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：775
- 内容哈希：`37d08f43e68cfc826987dcc3afbb57bdbb0d743265cba56240922b2746f574fc`
- 新增组件拟合候选轮廓构建与批量回填的结构化错误资源。

## frontend-2026.07.18.5

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：770
- 内容哈希：`a5268f661c12950354115f37640c301f65013f29729edbb77590e9f386752010`
- 新增旧版组件导入失败记录的结构化错误资源。

## frontend-2026.07.18.4

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：769
- 内容哈希：`ac495b1e1b2b2a5f01c8ed27902eaebe908ef7ce9aa404f300ddfc079b8ba73c`
- 新增组件与零件混合召回页面的尺寸、类型模糊匹配、候选状态文案。

## frontend-2026.07.18.3

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：749
- 内容哈希：`68ee9d234db0bfacca9e4836bf1120b0f4dc55c98ab1dc27f62593494c5bc4a3`
- 补齐多语言监控事件类型的结构化错误资源。

## frontend-2026.07.18.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：748
- 内容哈希：`36464ec43882cde87f5787471d0c7bc9c61cf68c7adb739aa4648f4dbefc3df2`
- Dashboard 新增未知 key、未知 API code、locale fallback 和监控容量指标。
- locale 解析与资源加载改为 catalog/目录驱动，并完成 `ja-JP` 扩展验证。

## frontend-2026.07.18.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：740
- 内容哈希：`1caea6c4a410e036dcba5aafd7796a52c190975180fdeecee4bf6d10a2daf324`
- 建立 M6 资源完整性、插值参数和 HTML 安全门禁。
- 选择 `ja-JP` 作为未发布的第三语言架构验证目标。

## brickbuilder-export-2026.07.18.1

- 生产语言：`zh-CN`、`en-US`
- 覆盖 LEGO LDraw、设计方案、DEM LDraw 和 DEM 报告。
- 首次记录冻结的 locale、timezone 与 catalog version。
