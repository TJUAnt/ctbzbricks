# 多语言领域字段分类

> 更新日期：2026-09-12
> 适用里程碑：M4～M5

| 实体 / 字段 | 分类 | 存储与展示规则 |
|---|---|---|
| 状态、类型、ID、LDraw 编号、尺寸、算法 | 机器数据 | 保存稳定值，不翻译 |
| `Component.name/description/tags`（`content_kind=user`） | 用户内容 | 原文保存并记录 `content_locale`，不自动翻译、不回退 |
| `ComponentGroup.name`（`group_type=custom`） | 用户内容 | 按用户原文保存并记录 `content_locale`；根节点不保存名称，由前端语义键本地化 |
| `ComponentGroup.id/owner_id/parent_group_id/group_type/sort_order`、分组关系与 Star 关系 | 机器数据 | `actor_id/component_id/starred_at/source`、`starredAt/starCount` 和 `sort=starred_at_desc` 保持稳定且不翻译；内部清理残留计数不进入公共 API，分类与尺寸筛选值按用户原文传输 |
| Component Watch period、列表与 Feed cursor | 机器数据 / 系统内容边界 | period ID、`actor_id/component_id/watch_level/started_seq/ended_seq/watched_at/unwatched_at`、`releases_only`、`since/windowStart`、不透明 cursor 及 API 字段保持稳定且不翻译；Watch 操作、状态、时间范围和结构化错误通过 typed semantic key 本地化。Feed 在读取时使用当前 active Watch，Watch 不改变 Star、Fork 或资源权限。 |
| Component 发布领域事件、Feed 展示与指标 | 机器数据 / 用户内容 / 官方内容 | `event_id/event_type/component_id/component_version_id/actor_id/event_seq/occurred_at/created_at`、公共广场 `publisher.id`、Feed entry 的 `render_status/available_at/render_profile/renderer_version/task/artifact`、图片 hash/字节数/尺寸/格式和不透明 cursor 都保持稳定且不翻译；pending 不返回，ready/fallback 是机器状态。指标及固定标签不接受 actor、Component ID 或请求文本。事件不复制展示内容；Release Note 保持作者原文及 locale，用户 Component 名称和描述保持原文，official Component 名称只选择 reviewed translation。公共广场不从认证资料推断昵称、邮箱或头像。 |
| `PixelArtProject.name` / Go `pixel_2d.projects.name/source_name` | 用户内容 | 原文保存并返回 `contentLocale`；不自动迁移无 owner 的 legacy 项目 |
| Go 2D revision/task/catalog/blob ID、RGB、BOM、尺寸、算法版本 | 机器数据 | 保持稳定；任务冻结 locale/timezone/export catalogVersion，JSON 属性不翻译，官方目录名称保留源内容并声明 en-US |
| `ModelAsset.name/source_name` | 用户内容 | 原文保存并返回 `contentLocale` |
| `Component`（`content_kind=official`） | 官方内容 | 源内容保存在主表，翻译保存在 `component_translations` |
| `LDrawPart.name/description` | 官方内容 | 英文源内容保存在主表，翻译保存在 `part_translations` |
| Go Part Search 的 `parts.source_name` / `ldraw_part_num` | 源内容检索投影 / 机器编号 | `query` 关键词匹配 importer 从 LDraw 文件头固化的源名称或稳定编号；结果返回源名称及其 `contentLocale`、`translationStatus=source`，不选择 reviewed translation。`imageUrl` 当前为 `null`，后续图片定位符仍属于机器数据、不翻译。 |
| 零件查找 `query` 及解析结果 | 用户查询 / 机器数据 | 空格或逗号分隔的名称关键词按用户原文用于检索，不保存、不翻译；从 `axb` / `axbxc` 提取的尺寸、关键词命中数和排序分数是机器数据 |
| 组件列表搜索 `query`、尺寸、状态与分页 | 用户查询 / 机器数据 / 官方内容选择 | 查询词按用户原文使用，不保存、不翻译；尺寸、状态、页码、容差和匹配分数保持机器数据。用户组件匹配原始名称；官方组件只匹配请求 locale 下实际选中的 reviewed 名称，缺失时按既有规则回退源内容 |
| 自动外部接口 ID、连接点类型、识别状态、识别规则版本 | 机器数据 | 由组件分析算法确定并随版本冻结，不提供用户创建或编辑，不翻译 |
| 组件预览零件 `availability`、可计算数量和缺失几何/mesh 状态 | 机器数据 | API 返回稳定状态值；缺失零件不参与尺寸、连接识别或 GLB，界面状态标签通过语义键本地化 |
| `ComponentVersion.preview_artifact_id/preview_status/preview_generator_version` 与 GLB 完整性字段 | 机器数据 | 使用版本 ID 直接定位派生 GLB；状态、生成器版本、artifact ID 和 SHA-256 不翻译。零件清单名称仍由独立 locale-aware API 选择 reviewed 翻译，不写入 GLB 定位数据 |
| Component Version Diff 的版本/实例/Part ID、`change kind`、矩阵、颜色码、数量与算法版本 | 机器数据 | API 返回稳定值并由双栏 3D 查看器定位节点；字段值不翻译。页面标题、操作、变化类型图例和空/错误状态使用 typed semantic key 本地化 |
| `Component/ComponentVersion.deleted_at/deleted_by`、版本发布/删除权限原因 | 机器数据 | 用于发布、逻辑删除、审计和权限判断，保持稳定且不翻译；操作界面中的组件名仍按用户或官方内容规则展示 |
| `Component.ownedByActor` | 机器数据 / 当前请求授权投影 | Go API 根据已鉴权 actor 与数据库 owner 计算，只控制当前页面管理操作，不保存、不翻译，也不能替代 mutation 的服务端 owner 校验 |
| `ComponentImport`、上传会话及其解析元数据 | 内部来源与机器数据 | 上传确认后冻结 `contentLocale/timezone`，API 以 `202` 结束写交互，并由持久任务在请求外执行 verify、解析/BOM 和 GLB 物化。`processing/ready/failed`、ID、状态、哈希与元数据键保持稳定且不翻译；界面处理状态使用 typed semantic key，失败使用 `code + params`。临时上传清理不得删除已成为不可变版本来源的 Artifact。 |
| 导入文件名、项目标签 | 用户或技术原文 | 不自动翻译；必要时单独记录内容语言 |
| API 错误、任务进度、验证 issue | 系统内容 | 只保存 `code + params`，由资源目录翻译 |
| 导出 JSON 的属性名、枚举、ID、BOM 数值 | 机器数据 | 保持稳定契约，不翻译 |
| 导出标题、说明、章节/字段标签、步骤名称 | 系统内容 | 按冻结 `exportContext` 从版本化服务端词典渲染 |
| 用户上传源文件、原始模型、组件源代码 | 用户或技术原文 | 下载内容和名称保持原样，不经过导出翻译层 |

官方翻译只有 `translation_status=reviewed` 时可对外展示；`draft` 和 `rejected` 不参与查询。请求语言缺失已审核翻译时回退到主表 `content_locale`，返回实际 `contentLocale` 并累计缺失翻译指标。

Component/Part 详情预览接口按请求的 `contentLocale` 选择已审核的官方译文；资源类型、资源 ID、LDraw 编号、几何和版本字段保持机器值。召回列表中的名称仍保持源内容，不执行本地化选择。
