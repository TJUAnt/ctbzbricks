# 多语言领域字段分类

> 更新日期：2026-07-21  
> 适用里程碑：M4～M5

| 实体 / 字段 | 分类 | 存储与展示规则 |
|---|---|---|
| 状态、类型、ID、LDraw 编号、尺寸、算法 | 机器数据 | 保存稳定值，不翻译 |
| `Component.name/description/tags`（`content_kind=user`） | 用户内容 | 原文保存并记录 `content_locale`，不自动翻译、不回退 |
| `ComponentGroup.name`（`group_type=custom`） | 用户内容 | 按用户原文保存并记录 `content_locale`；根节点不保存名称，由前端语义键本地化 |
| `ComponentGroup.id/owner_id/parent_group_id/group_type/sort_order`、分组关系与订阅关系 | 机器数据 | 保持稳定且不翻译 |
| `PixelArtProject.name` | 用户内容 | 原文保存并返回 `contentLocale` |
| `ModelAsset.name/source_name` | 用户内容 | 原文保存并返回 `contentLocale` |
| `Component`（`content_kind=official`） | 官方内容 | 源内容保存在主表，翻译保存在 `component_translations` |
| `LDrawPart.name/description` | 官方内容 | 英文源内容保存在主表，翻译保存在 `part_translations` |
| `FittingCandidateProfile.appearance_tags.name/remarks`（召回接口） | 源内容检索投影 | `key` 只匹配画像中的源名称；召回结果直接返回源快照及实际 `contentLocale`，不查询或选择 Component/Part 翻译；`imageUrl` 是从 `rb_part_images`/编号映射取得的机器定位符，不翻译 |
| 零件查找 `query` 及解析结果 | 用户查询 / 机器数据 | 空格或逗号分隔的名称关键词按用户原文用于检索，不保存、不翻译；从 `axb` / `axbxc` 提取的尺寸、关键词命中数和排序分数是机器数据 |
| 组件列表搜索 `query`、尺寸、状态与分页 | 用户查询 / 机器数据 / 官方内容选择 | 查询词按用户原文使用，不保存、不翻译；尺寸、状态、页码、容差和匹配分数保持机器数据。用户组件匹配原始名称；官方组件只匹配请求 locale 下实际选中的 reviewed 名称，缺失时按既有规则回退源内容 |
| 自动外部接口 ID、连接点类型、识别状态、识别规则版本 | 机器数据 | 由组件分析算法确定并随版本冻结，不提供用户创建或编辑，不翻译 |
| 组件预览零件 `availability`、可计算数量和缺失几何/mesh 状态 | 机器数据 | API 返回稳定状态值；缺失零件不参与尺寸、连接识别或 GLB，界面状态标签通过语义键本地化 |
| `ComponentVersion.preview_artifact_id/preview_status/preview_generator_version` 与 GLB 完整性字段 | 机器数据 | 使用版本 ID 直接定位派生 GLB；状态、生成器版本、artifact ID 和 SHA-256 不翻译。零件清单名称仍由独立 locale-aware API 选择 reviewed 翻译，不写入 GLB 定位数据 |
| `Component/ComponentVersion.deleted_at/deleted_by`、版本发布/删除权限原因 | 机器数据 | 用于发布、逻辑删除、审计和权限判断，保持稳定且不翻译；操作界面中的组件名仍按用户或官方内容规则展示 |
| `ComponentImport`、上传会话及其解析元数据 | 内部来源与机器数据 | 成功记录只作为组件版本来源追溯，不作为用户可见任务；上传确认后冻结 `contentLocale/timezone` 并在请求外执行解析和 GLB 物化；失败时删除临时记录和私有存储对象。ID、状态、哈希与元数据键保持稳定且不翻译 |
| 导入文件名、项目标签 | 用户或技术原文 | 不自动翻译；必要时单独记录内容语言 |
| API 错误、任务进度、验证 issue | 系统内容 | 只保存 `code + params`，由资源目录翻译 |
| 导出 JSON 的属性名、枚举、ID、BOM 数值 | 机器数据 | 保持稳定契约，不翻译 |
| 导出标题、说明、章节/字段标签、步骤名称 | 系统内容 | 按冻结 `exportContext` 从版本化服务端词典渲染 |
| 用户上传源文件、原始模型、组件源代码 | 用户或技术原文 | 下载内容和名称保持原样，不经过导出翻译层 |

官方翻译只有 `translation_status=reviewed` 时可对外展示；`draft` 和 `rejected` 不参与查询。请求语言缺失已审核翻译时回退到主表 `content_locale`，返回实际 `contentLocale` 并累计缺失翻译指标。

Component/Part 详情预览接口按请求的 `contentLocale` 选择已审核的官方译文；资源类型、资源 ID、LDraw 编号、几何和版本字段保持机器值。召回列表中的名称仍保持源内容，不执行本地化选择。
