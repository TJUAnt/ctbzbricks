# Component 订阅管理功能需求

> 所属菜单：我的模型 / 我的模型
>
> 路由：`/component-repo/watches`
>
> 动态入口：`/model-plaza?tab=subscriptions`
>
> 文档状态：当前功能
>
> 详细实现：[Watch 详细设计](../../../../design/my-models/component-repo/watch.md)

## 1. 功能目标

订阅管理页展示当前用户仍有效且仍公开可见的 active Watch，支持按名称/ID与分类筛选、连续加载、进入详情和取消订阅。
发布动态不在本页展示，而是在模型广场“个人订阅”页签中读取。

## 2. 成员资格与权限

- 只读取当前 actor 的 active Watch；closed 历史不进入列表。
- Watch 目标必须是公开可见、非本人、active 且具有非 Draft Version 的 Component。
- Watch 不授予 Component、Version、Preview 或 Source 的额外可见性。
- 当前只支持 `releases_only` level，机器值不翻译。
- Component 删除、变为不可见或 Watch 被取消后，下次读取立即退出列表。

## 3. 筛选与读取

- 每批最多 20 条，按 `watchedAt DESC, componentId DESC` 使用不透明 keyset cursor 连续加载。
- 名称/ID搜索最长 200 字符；完整 UUID 使用等值路径，其他内容匹配名称或部分 ID。
- 分类最长 128 字符，按规范化精确值筛选。
- 用户编辑 draft filters 后点击“应用筛选”才生效；query 与 category 同时存在时按 AND 组合。
- 清除筛选同时清空 draft 和已应用条件，并重读首屏。
- cursor 绑定 locale/query/category，任一条件变化后不能继续使用旧 cursor。
- 页面不计算 exact total；标题数字只表示当前已经加载到页面的条目数，不得表述为全部订阅总数。

## 4. 列表内容与操作

每行展示 Component 名称、分类、缩短 ID、订阅级别、最新 published Version/Revision、发布时间、Watch 时间以及：

- “详情”进入 Component 详情。
- “取消订阅”立即乐观移除该行并禁止重复操作。
- 取消失败时按原位置恢复条目并显示错误；恢复后仍按服务端顺序去重。
- 手动刷新丢弃当前列表和 cursor，使用已应用筛选重读首屏。
- “加载更多”追加下一 cursor 页并按 Component ID 去重，不在前端重新排序。

## 5. 空状态与导航

- 没有任何订阅时提示浏览 Component，并提供返回 Component 仓库入口。
- 有筛选但无匹配时提示调整名称/ID或分类，不显示“没有任何订阅”的误导文案。
- 页头提供返回 Component 仓库的页签链接。
- 个人订阅动态的 7/30/90 天窗口、事件卡片和 Feed cursor 由模型广场需求负责，本页不复制动态。

## 6. 多语言与可访问性

- 页面文案、筛选、加载、空状态和 Unwatch 使用 typed semantic keys。
- official Component 只显示 requested locale 的 reviewed translation；用户内容保持原文。
- 日期按 locale 格式化；切换 locale 后重读首屏并废弃旧请求。
- 表格使用 row/cell/columnheader 语义，筛选表单可键盘提交，加载更多和取消订阅使用原生按钮。
- 错误通过稳定 `code + params` 本地化，不显示 actor、SQL、cursor payload 或内部关系历史。

## 7. 验收条件

1. 用户只能看到自己的 active Watch，closed、不可见、本人或已删除目标不出现。
2. 名称/ID和分类筛选组合正确，条件变化后旧 cursor 被废弃。
3. 连续加载保持服务端顺序并按 Component ID 去重，不显示伪造总数。
4. 行展示最新 published Version 与 watchedAt；没有可用版本时显示稳定缺省状态。
5. 取消订阅成功后条目退出，失败后原位置恢复；Star 和 Group 不受影响。
6. 无订阅和筛选无结果显示不同空状态，并能回到 Component 浏览入口。
7. locale 切换、快速筛选、刷新和续页时旧响应不会污染新列表。
8. 中文、英文、键盘、表格和响应式布局通过浏览器验收。

## 8. 当前限制

- 只有 `releases_only`，没有按事件类型、静音或通知渠道的偏好。
- 当前规划包络为每 actor 最多约 1,000 active Watch；这是容量规划，不是 API 强制拒绝阈值。
- Web 采用 last-write-wins，尚未提供 mutationId；未来引入离线队列或自动重放前需冻结强意图幂等协议。
