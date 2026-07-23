# `ja-JP` 第三语言扩展验证

## 结论

选择日语 `ja-JP` 作为第三语言验证目标。它不在当前 `productLocales` 中，未审核译文不会出现在生产语言选择器；当前状态为“架构通过、翻译未开始”。

新增正式日语时只需要：

1. 在 `frontend/src/i18n/resources/ja-JP` 增加与源语言同构的 10 个 JSON 文件。
2. 在前后端 catalog 的 `productLocales` 中加入 `ja-JP`，从 `validationLocales` 移除，并在前端 catalog 配置语言名称 key。
3. 在服务端导出资源中增加 `ja-JP.json`，并发布新的 export catalog version。
4. 为官方 Component/Part 写入 `ja-JP` 且状态为 `reviewed` 的翻译记录。
5. 更新 catalog hash、发布说明并完成语言审核。

资源加载通过目录发现完成，locale 解析通过 catalog alias 完成，业务页面、API 和导出代码均不需要增加 `if (locale === 'ja-JP')` 分支。

自动化验证覆盖：

- 前后端 catalog 均登记 `ja-JP` validation locale。
- 通用 locale resolver 可在候选列表包含日语时解析 `ja`、`ja-JP`。
- `Intl.DateTimeFormat` 与 `Intl.NumberFormat` 使用 `ja-JP` 输出。
- 未加入 `productLocales` 前，请求日语仍回退默认生产语言。
