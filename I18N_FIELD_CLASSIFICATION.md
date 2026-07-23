# 多语言领域字段分类

> 更新日期：2026-07-21  
> 适用里程碑：M4～M5

| 实体 / 字段 | 分类 | 存储与展示规则 |
|---|---|---|
| 状态、类型、ID、LDraw 编号、尺寸、算法 | 机器数据 | 保存稳定值，不翻译 |
| `Component.name/description/tags`（`content_kind=user`） | 用户内容 | 原文保存并记录 `content_locale`，不自动翻译、不回退 |
| `PixelArtProject.name` | 用户内容 | 原文保存并返回 `contentLocale` |
| `ModelAsset.name/source_name` | 用户内容 | 原文保存并返回 `contentLocale` |
| `Component`（`content_kind=official`） | 官方内容 | 源内容保存在主表，翻译保存在 `component_translations` |
| `LDrawPart.name/description` | 官方内容 | 英文源内容保存在主表，翻译保存在 `part_translations` |
| `FittingCandidateProfile.appearance_tags.name/remarks`（召回接口） | 源内容检索投影 | `key` 只匹配画像中的源名称；召回结果直接返回源快照及实际 `contentLocale`，不查询或选择 Component/Part 翻译；`imageUrl` 是从 `rb_part_images`/编号映射取得的机器定位符，不翻译 |
| 组件接口名、导入文件名、项目标签 | 用户或技术原文 | 不自动翻译；必要时单独记录内容语言 |
| API 错误、任务进度、验证 issue | 系统内容 | 只保存 `code + params`，由资源目录翻译 |
| 导出 JSON 的属性名、枚举、ID、BOM 数值 | 机器数据 | 保持稳定契约，不翻译 |
| 导出标题、说明、章节/字段标签、步骤名称 | 系统内容 | 按冻结 `exportContext` 从版本化服务端词典渲染 |
| 用户上传源文件、原始模型、组件源代码 | 用户或技术原文 | 下载内容和名称保持原样，不经过导出翻译层 |

官方翻译只有 `translation_status=reviewed` 时可对外展示；`draft` 和 `rejected` 不参与查询。请求语言缺失已审核翻译时回退到主表 `content_locale`，返回实际 `contentLocale` 并累计缺失翻译指标。

Component/Part 详情预览接口按请求的 `contentLocale` 选择已审核的官方译文；资源类型、资源 ID、LDraw 编号、几何和版本字段保持机器值。召回列表中的名称仍保持源内容，不执行本地化选择。
