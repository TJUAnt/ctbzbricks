# 多语言资源发布记录

资源版本只追加、不复用。前端资源内容由 SHA-256 锁定，服务端导出版本写入每个正式产物。

## frontend-2026.09.07.1

- 2D 像素任务新增上传、排队、处理、完成、失败和离页恢复提示，以及已保存项目的处理进度入口。
- 内容哈希：`369c7fe3189d1643ced79283c52eea375718f7fb515eaa5cbba7e7e724aa58c2`
- `queued`、`running`、`succeeded`、`failed`、`cancelled`、taskId 和 projectId 保持稳定机器值；仅状态说明被本地化。

## frontend-2026.09.06.2

- 新增 2D 预览处理失败提示（zh-CN/en-US）；预览计算转入 Worker，原图和导出上下文不变。
- 内容哈希：`721090ee3c1217811f9dde45cf792ec85e09d68e0af662a82a7b42fcc3d81b3b`
- 当前阶段隐藏 DEM 与 3D 工具入口；遥测切换至 Go `/api/v1/i18n`。

## frontend-2026.09.06.1

- 生产语言：`zh-CN`、`en-US`；namespace：10。
- 内容哈希：`60a2ecb137b2d00122dd60bd0c4aae0a5dcb66a76105c4a816f6df9dfa0f3f56`
- 导航调整为模型广场、我的模型组件和模型小工具；新增 2D 流程导航，并明确 3D 当前仅提供 GLB 上传及颜色分析。
- 仅调整前端系统文案；用户内容、官方翻译选择、API 和任务契约不变。

## frontend-2026.09.04.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：1039
- 内容哈希：`25ef31679402e7c0aaafae4d3d25607f9a96286bd864ec1ed9b086d999a6379d`
- Component Repo 新增独立“我的订阅”页面，包含名称/ID 与分类筛选、Watch 级别、最近公开发布、订阅时间、游标续页、取消订阅和空状态文案。
- `releases_only`、Component/Version ID、cursor、时间戳与分类查询仍是稳定机器或用户输入数据；页面只本地化系统标签，并保留服务端选择后的 Component 原文或 reviewed translation。

## frontend-2026.08.31.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：1015
- 内容哈希：`738bd687f4132a8334b2c35e6f126efd4a5576624f96e8c8e4594f63fda81e0f`
- Component 详情新增与 Star 独立的 Watch/Unwatch 操作、订阅状态、成功反馈和结构化错误文案；MVP 级别说明固定为“新版本发布时通知”。
- `releases_only`、Watch period ID、`started_seq/ended_seq`、关系时间、Component ID、不透明 cursor 和 API error code 保持稳定机器数据；Watch 不翻译用户 Component 内容，也不授予额外权限。

## frontend-2026.08.30.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：1005
- 内容哈希：`9bf13c034632618130ce2b73addc8c9c77bdb67f032cef38c487e8f8acf55a9f`
- Component Repo 区分“我的组件”与“我的收藏”，收藏页新增分类/逻辑尺寸筛选、收藏时间列，以及“从未收藏 / 筛选无结果 / 关系存在但目标不可见”三类空状态。
- 用户输入的名称、Component ID、分类和尺寸条件保持原文；`sort=starred_at_desc`、`starredAt`、`relationshipTotal` 与 Star 计数继续作为稳定机器数据，不翻译。

## frontend-2026.08.29.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：998
- 内容哈希：`241a429203a5b8f2f7f050cf4de198a50f2d7ead71a540d0aaaec4168a98fcb5`
- Component Repo 新增 Star 收藏列表、列表与详情页收藏/取消收藏、收藏数、社区目录和空状态文案；Star 使用新的结构化错误，旧 Subscription 错误资源仅在遗留 Python 源码删除前保留兼容。
- `actor_id/component_id/starred_at/source`、`starredByActor/starCount`、Component ID 与 API error code 保持稳定机器数据；Component 名称仍按内容来源规则展示。

## frontend-2026.08.27.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：984
- 内容哈希：`7dafd9b3a0bae49ec864c40be0280ab4e7453b465fbd3e79e10274d7e68e924a`
- Component 详情页新增相邻版本三维并行对比、同步视角、差异图例、变化统计、聚焦与关闭操作文案。
- Version/Instance/Part ID、`change kind`、矩阵、颜色码、数量和 Diff 算法版本保持稳定机器数据；只有页面说明与图例名称本地化。

## frontend-2026.08.25.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：964
- 内容哈希：`0d75a5beb557077fd3cb96260c051118b400c6231e0dfdadea4ded01e28055f1`
- Component Repo 搜索改为按 Enter 追加 AND 条件，并在搜索框右侧显示可分别清除的条件标签；新增当前条件和清除按钮的无障碍语义文案。
- 用户输入的名称、UUID 或尺寸查询保持原文展示和传输；条件值、Box 数值及 `x/X/×` 分隔符不翻译。

## frontend-2026.08.24.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：962
- 内容哈希：`51167620152381700db4ca56a0fafef3a90d629847bd28053cd7ab952a234929`
- Component Repo 新增全局导入记录页面和组件详情导入记录 Tab；组件列表状态收敛为“全部 / 草稿 / 已发布”。
- Import 的 `processing/ready/failed`、Component 的 `draft/active`、ID、文件大小与时间字段保持机器数据；源文件名按用户原文展示，失败继续通过 `code + params` 本地化。

## frontend-2026.08.24.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：941
- 内容哈希：`27e0a34eea2255209feb1f11d163c3c2ff1027a0f7ef0e94740f507321241d4c`
- Component 发布与验证解耦；详情页复用既有“验证 / 已通过”语义 key，并新增“当前版本无法验证”的结构化错误文案。
- Version ID、Candidate ID、`passed`、ValidationReport ID、task 状态和错误 code 继续作为机器数据，不翻译。

## frontend-2026.08.23.3

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：940
- 内容哈希：`f79746ec4a2c52ec9061622ed0f43ff454eacdaaa761684a195ff1a3924bd726`
- Component 候选页和详情页的 BOM 对缺少 ready geometry 的 Part 显示“缺少预览几何”；Part 编号、数量及 `ready/failed/missing` 状态保持机器数据，不翻译。

## frontend-2026.08.23.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：939
- 内容哈希：`645fa27f5f45b7c2e112a194a50e6b24246346c2937c07cdeb9d66b4f89e9b04`
- Component 上传弹窗文案收敛为“只等待文件上传完成”；upload complete 返回后进入独立的解析中状态页，不再暗示弹窗等待 Worker 处理。
- Import ID、处理状态、task/candidate/version ID 和 API 字段继续作为机器数据；状态页使用既有 typed semantic key。

## frontend-2026.08.23.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：939
- 内容哈希：`a1df75fe1221177d4efd58e7818fb311468895007441a96056d65a7633e42b81`
- Component Candidate 默认结果页新增按需加载连接信息的开关说明与 BOM 独立失败提示；默认只展示 Worker 已生成的整体 GLB 与 Version BOM。
- Connector、relation、interface、Part 编号、数量和状态继续作为机器数据，不翻译；开关标题与说明使用 typed semantic key。

## frontend-2026.08.21.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：936
- 内容哈希：`93479d839918ae1af7dc517030383981ad8ff5a7d50312f60f2a338761fae8b9`
- 撤销未采用的 Component Repo 永久删除 / purge 文案和错误资源；当前 Component 删除只保留 soft delete 入口。
- Component 名称仍按用户内容原样插值；Component ID、删除审计字段、Storage key 和状态保持机器数据，不翻译。

## frontend-2026.08.17.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：947
- 内容哈希：`cee3d241508a132e7b2b7ba05672df74f59ce8489263ac438a723dc1b1fe0d62`
- Component Repo 详情页新增永久删除组件的二次确认文案，并新增 purge 任务与确认失败/Storage 删除失败错误文案。
- 组件名称仍按用户内容原样输入与比较；Component ID、task type、Storage key、删除计数和任务状态保持机器数据，不翻译。

## frontend-2026.08.17.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：936
- 内容哈希：`93479d839918ae1af7dc517030383981ad8ff5a7d50312f60f2a338761fae8b9`
- Component Repo 详情页新增整体删除组件的确认文案，区分 Component 删除与单个 Version 删除。
- Component ID、Version ID、删除审计字段、Storage key 和用户组件名称保持机器数据或用户内容；确认弹窗仅本地化系统说明。

## frontend-2026.08.14.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：931
- 内容哈希：`a1a6a2b1e255eb291ebba2639d2ca4fa43b1683e69080c0aeb943d605b3f9285`
- Component Repo 新增 Part Library 不可用、Part 不存在和 Part preview 无法物化三类结构化错误文案。
- Part Library 版本 ID、LDraw Part 编号、Artifact ID、任务状态与几何数值保持机器数据，不翻译。

## frontend-2026.08.05.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：928
- 内容哈希：`04cddb73de9ff94cf813ecfa946b69a832152d22c61053ce2aa9052253cc559f`
- 组件列表搜索接入服务端名称模糊匹配、二维/三维占用尺寸匹配、状态筛选和分页，并补充分页及尺寸搜索提示文案。
- 用户查询按原文处理；官方组件仅按请求 locale 的 reviewed 名称匹配，组件 ID、尺寸、状态、页码和匹配参数保持机器数据。

## frontend-2026.08.05.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：924
- 内容哈希：`c1dba66b0f251bbe667b342b39c9a4d4941744bdf4d748dde9742554b3e41480`
- 组件列表新增占用尺寸列，以长、宽的 stud 数和高度的 plate 数展示，并提供本地化无障碍表述。
- 尺寸数值、维度顺序和 API 属性保持机器数据；尺寸不完整时返回 `null`，界面使用资源文案说明不可用状态。

## frontend-2026.07.29.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：920
- 内容哈希：`d3f5e9a9cc89dce4ae8d9abe8c063ef5fa811179cb6d622a9657c2f6263670d3`
- 组件部分预览在缺少零件几何或网格时跳过缺失实例，并在零件清单显示“未纳入计算”。
- 零件可用状态、可计算数量和 LDraw 编号保持机器数据；前端通过语义键展示状态。

## frontend-2026.07.28.3

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：919
- 内容哈希：`7cbb3719ee78262f4d199acd2ba68335b9aca593db12ad7e9dde0c03068ec483`
- 零件单框搜索支持空格、英文逗号和中文逗号作为同级分隔符，并更新输入示例。
- 查询原文和名称关键词不翻译；提取出的尺寸仍为机器数据。

## frontend-2026.07.28.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：919
- 内容哈希：`2009d581149487479c5df15e4d75139fb82c6a709d88c10bed1cac599361a62f`
- 查找零件页面收敛为单搜索框，并更新逗号分隔的尺寸、名称关键词输入说明。
- 原始查询关键词按用户输入处理；提取出的尺寸、匹配数量、候选 ID 和排序分数保持机器数据，不翻译。

## frontend-2026.07.28.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：919
- 内容哈希：`05514d6166b1b69d004c49b0a4efd6b8c96f4699b39bd69944e8ceb3444ff862`
- 组件详情页新增草稿发布入口，并补充组件版本发布权限错误文案。
- 组件 ID、版本 ID、发布状态和创建者审计标识保持机器数据，不翻译；组件名称继续按用户内容或官方领域内容规则展示。

## frontend-2026.07.27.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：918
- 内容哈希：`e87cb888143ec1899253a6ac160ebc8eb8c51e28833bfcca6de6f42664bc0017`
- 组件详情的连接点增加状态分组 Tab，并默认展示外部连接点。
- 零件编号、连接点 ID/状态、API 路径、状态码、耗时和 traceId 保持机器数据；零件编号仅增加详情页导航，不翻译。

## frontend-2026.07.27.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：913
- 内容哈希：`a533e45ad51f4752abf68c2aae3921e23f0a3c6e900199ebf0405d137b4d4458`
- 组件详情页新增连接点选择、清除及三维预览定位提示；连接点和自动外部接口改为分组 Tab 展示。
- 连接点 ID、类型、状态、三维坐标、接口识别版本、API 路径、耗时和 traceId 仍为机器数据，不翻译。

## frontend-2026.07.26.4

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：910
- 内容哈希：`bf0a93cf98bcf7bb4f2c7b03f7ca528aad9856c310da1b1f751468449991212c`
- 上传完成后自动校验、解析并进入人工审核；新增自动处理进度与失败丢弃提示。
- 导入 ID、上传会话 ID、组件状态、文件名和 API 字段仍为机器或用户技术原文，不翻译。

## frontend-2026.07.26.3

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：907
- 内容哈希：`17cc4fa7e82b9076831de683cbde4d0d20c782535dd95e2f27e4abbdb1339ebd`
- 新增组件版本操作菜单、删除确认、唯一版本影响提示、删除结果和权限冲突文案。
- 组件名按用户内容原样展示；版本号、revision、版本 ID、权限原因和逻辑删除时间保持机器数据。

## frontend-2026.07.26.2

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：895
- 内容哈希：`e811d21df623e6c42c6a7ae77a46d92bd65dba7ee9e40ea4670c25fb819a2013`
- 新增组件详情、零件清单、连接点状态、自动外部接口、所属分组和版本历史文案。
- 连接点类型、接口 ID、识别状态和识别规则版本保持机器值；外部接口由算法派生并随组件版本冻结，不作为用户内容翻译。

## frontend-2026.07.26.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：871
- 内容哈希：`3ed110db276a38817ccf4194b8e4c02346fbc408e7424edffa12a459c94b7a4d`
- 组件目录树改为拖拽移动，节点 `+` 菜单支持新建子分组和向当前分组添加组件。
- 拖拽位置、父分组 ID 和组件关系仍为机器数据；组件和自定义分组名称继续按领域内容规则展示。

## frontend-2026.07.25.1

- 生产语言：`zh-CN`、`en-US`
- namespace：10
- 每种语言 key：862
- 内容哈希：`d6d24790f576170f5d423b4b9ce26d18f5d659649ca9143b5f6c5f6b08346623`
- 新增个人组件分组树、分组编辑、删除确认和组件多分组管理文案，以及对应稳定 API 错误资源。
- 根节点名称属于系统资源；自定义分组名称按用户原文和 `contentLocale` 保存；分组、组件和订阅 ID 等机器字段不翻译。

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

## 2026-09-06：2D Go 运行边界迁移

2D API/Worker 切换 Go，保留现有 code/params、用户原文 contentLocale 与冻结 ExportContext。服务端导出资源字节未变，继续使用 `brickbuilder-export-2026.07.18.1`，Go/Python canonical 副本同步由测试约束，不新增语言或文案键。前端资源版本沿用本日导航重组的 `frontend-2026.09.06.1`。i18n 检查、75 项前端测试、构建、296 项 Python 回归与 Go 测试通过。
