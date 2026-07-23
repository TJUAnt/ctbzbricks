# 多语言变更强制约束

> 文档性质：架构护栏 / 任务执行入口  
> 适用对象：用户、开发者、代码审查者和智能体  
> 架构依据：[I18N_ARCHITECTURE.md](./I18N_ARCHITECTURE.md)

## 1. 每个任务开始前必须回答

执行者必须先向用户说明：

```text
多语言影响：有 / 无
影响面：页面文案 / API 错误 / 异步任务 / 领域内容 / 导出 / locale 格式化 / 无
采用契约：对应下表中的规则
```

只要改动可能被用户看见、保存、下载或通过 API 返回，就不能默认判定为“无”。纯算法、内部日志、测试夹具或不改变展示语义的重构可以判定为“无”，但仍不得破坏既有结构化字段。

## 2. 变更决策表

| 改动类型 | 必须执行 | 禁止 |
|---|---|---|
| React 页面、按钮、提示、空状态 | 在所有生产 locale 的对应 namespace 增加语义 key；使用 typed translator | TS/TSX 硬编码用户可见中英文；`defaultValue` |
| 展示型 JSON 配置 | 保存 `namespace:semantic.key`，通过 `localizedConfig` 读取 | 在配置中保存最终展示句子 |
| 状态、类型、枚举、ID | API 和数据库保存稳定机器值；前端边界映射 key | 翻译后再做业务判断；按语言改变枚举值 |
| API 错误 | `DomainError(code, params, http_status)`；补齐 `errors` 资源 | `detail=str(error)`；返回异常正文或最终译文 |
| 任务进度、验证 issue | 保存/返回 `code + params`；任务冻结 locale/timezone | 保存最终错误句子；轮询时重写任务语言 |
| 用户创建的名称、标签、描述 | 原文保存并记录 `contentLocale` | 自动翻译、回退成系统译文、把用户内容当 key |
| 官方 Component/Part 内容 | 使用翻译表；只读取 `reviewed` 记录；缺失时返回实际 `contentLocale` 并计数 | 给实体主表增加 `name_zh/name_en`；展示 draft 译文 |
| LDraw、设计计划、报告等导出 | 使用冻结 `ExportContext` 和版本化服务端词典；本地化标题/标签/步骤/文件名 | 翻译 JSON 机器字段；按下载时浏览器语言生成；客户端临时拼报告 |
| 日期、数字、相对时间、排序 | 使用当前 locale 的 `Intl`/格式化 helper | 手写固定日期或千分位格式 |
| 新增生产语言 | 增加同构资源目录、catalog 配置、导出资源及 reviewed 领域翻译；更新 hash/version/release notes | 在业务代码加入语言分支；未审核即加入 `productLocales` |
| RTL 语言 | 先完成 `I18N_RTL_ASSESSMENT.md` 清单和视觉/键盘验收 | 仅设置 `dir=rtl` 就宣布支持 |

## 3. 四类内容边界

```text
机器数据       -> 永不翻译：ID、enum、code、JSON key、数值、文件格式
用户内容       -> 原样保存：名称、标签、描述、上传文件名，并记录 contentLocale
官方领域内容   -> 翻译表：Component/Part，只有 reviewed 可展示
系统生成内容   -> 资源渲染：UI、错误、任务消息、导出标题与标签
```

无法确定分类时，先查阅 `I18N_FIELD_CLASSIFICATION.md`；仍不明确则暂停实现并向用户说明需要做出的领域决策。

## 4. 资源和版本规则

- 前端 catalog：[frontend/src/i18n/catalog.json](./frontend/src/i18n/catalog.json)。
- 前端资源：[frontend/src/i18n/resources](./frontend/src/i18n/resources)。
- 服务端导出资源：[backend/src/i18n/export_resources](./backend/src/i18n/export_resources)。
- 术语表：[backend/config/i18n_glossary.json](./backend/config/i18n_glossary.json)。
- 发布记录：[I18N_RELEASE_NOTES.md](./I18N_RELEASE_NOTES.md)。

修改前端资源时：

1. 同步修改全部生产语言。
2. 保持插值参数集合一致，禁止 HTML。
3. 升级 `catalogVersion`。
4. 运行 `npm run i18n:hash` 得到新 hash，通过补丁写入 `contentHash`。
5. 在发布记录新增版本，禁止覆盖旧版本说明。
6. 运行 `npm run i18n:types` 更新类型，再执行质量门禁。

## 5. Definition of Done

一个涉及多语言的任务只有同时满足以下条件才算完成：

- 已说明影响面和采用的契约。
- 所有生产语言资源完整，key 和插值参数一致。
- API、任务、领域内容和导出边界没有混入最终译文或用户内容误翻译。
- catalog version、hash、发布说明与资源一致。
- 未知 key/code 和 locale fallback 仍能被监控。
- `npm run i18n:check`、前端测试/构建和后端测试通过。
- 架构契约变化已同步更新相关文档。

## 6. 智能体最终交付模板

```text
多语言影响：<影响面或无>
遵循的契约：<UI/API/任务/领域内容/导出/格式化>
资源与版本：<无变化，或新 catalog/export version>
验证：<i18n check、测试、构建结果>
```

不得只写“已支持多语言”；必须说明数据边界、locale 来源以及译文生成发生在哪一层。
