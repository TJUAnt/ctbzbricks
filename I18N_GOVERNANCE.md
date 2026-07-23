# BrickBuilder 多语言治理规范

> 生效日期：2026-07-18  
> 所有者登记：[backend/config/i18n_owners.json](./backend/config/i18n_owners.json)

## 1. 负责人和审批

每项翻译变更必须同时获得资源所有者和目标语言审核者确认。仓库维护者负责在人员变化时更新所有者登记，不允许在资源文件中记录个人姓名。

| 范围 | 负责人角色 | 审核重点 |
|---|---|---|
| `common`、`app` | `product-localization` | 产品语气、导航和通用术语 |
| 业务 namespace | `feature-owner` | 功能上下文、数值和交互准确性 |
| `errors`、`tasks` | `api-contract-owner` | code、参数集合和错误语义 |
| 服务端导出 | `api-contract-owner` | 冻结上下文、catalog version 和机器字段稳定性 |
| 组件/零件领域翻译 | `component-library-owner` / `part-library-owner` | 官方内容、审核状态和术语一致性 |
| 术语表 | `product-localization` | 品牌、技术标准和跨模块一致性 |

领域翻译只有 `reviewed` 状态可以对外显示；提交者不能同时作为唯一语言审核者。

## 2. 文案风格

- key 描述语义而不是原文，禁止把完整中文或英文句子作为 key。
- 中文使用简体中文和全角中文标点；英文使用 sentence case，按钮优先使用动词。
- LEGO、LDraw、DEM 等术语以 `i18n_glossary.json` 为准，不自行创造同义译法。
- 不翻译 ID、枚举、文件格式、零件编号、单位 code 和用户原文。
- 插值只传结构化值，不拼接 HTML；需要富文本时先建立受控组件插槽方案。
- 错误文案说明用户可采取的动作，不泄露异常、路径、SQL 或鉴权响应。

## 3. PR 工作流

1. 先新增或修改源语言语义 key，再补齐所有生产语言。
2. 参数名在所有语言中必须完全一致；删除参数时同步修改类型化调用点。
3. 运行 `npm run i18n:hash`，升级 `catalogVersion`、更新 `contentHash`，并在 `I18N_RELEASE_NOTES.md` 记录变更。
4. 导出词典发生变化时升级 `EXPORT_CATALOG_VERSION`，保留旧版本发布记录。
5. 执行 `npm run i18n:check && npm test && npm run build` 和后端测试。
6. PR 描述列出资源所有者与目标语言审核者，并确认无用户内容被翻译。

## 4. 发布和回滚

- catalog version 一经发布不可原地复用；修正文案也必须创建新版本。
- 回滚应用时同时回滚对应资源与版本声明，不单独回滚译文文件。
- 未审核的新增语言只允许作为 `validationLocales`，不得加入 `productLocales` 或语言选择器。
- 未知 key、未知 API code 和 locale fallback 由 `/api/i18n/metrics` 监控；发布后出现非零新增趋势必须建立修复项。
