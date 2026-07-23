# RTL 技术评估

## 结论

当前 `zh-CN`、`en-US` 及验证语言 `ja-JP` 都是 LTR。运行时已经根据 catalog 的 `rtlLanguageCodes` 设置 HTML `dir`，但现有样式仍有物理方向属性，因此阿拉伯语等 RTL 语言尚不能直接发布。

## 已具备

- `textDirection(locale)` 对 `ar`、`fa`、`he`、`ur` 返回 `rtl`。
- 语言变化时同步 `<html lang>` 与 `<html dir>`。
- 文案资源、API code 和机器数据没有绑定左右方向。

## 上线前必须完成

| 范围 | 当前风险 | 改造要求 |
|---|---|---|
| 页面间距和边框 | `padding-left/right`、`border-left/right` | 改为 `padding-inline-*`、`border-inline-*` |
| 浮层和角标 | 大量 `left/right` 绝对定位 | 区分几何坐标与 UI 起止方向；UI 改用 `inset-inline-*` |
| 文本对齐 | `text-align: left/right` | 改为 `start/end`，数值列按数据语义单独处理 |
| 箭头、前进/返回图标 | 方向含义可能反转 | 为语义方向图标增加 `[dir=rtl]` 镜像；播放、下载等图标不镜像 |
| 拖拽与 3D 坐标 | `left` 表示画布 X 轴 | 保持物理坐标，不随 RTL 镜像 |
| 表格、步骤条、分页 | 阅读顺序与键盘顺序 | RTL 浏览器回归验证 DOM 顺序、焦点和读屏顺序 |

## 验收清单

- 增加 `ar-XB` RTL 伪语言，仅用于开发和视觉回归。
- 1280px 与 390px 下验证导航、表单、弹窗、表格、步骤条和下载按钮。
- 检查所有方向图标，明确“镜像/不镜像”分类。
- 键盘 Tab 顺序和屏幕阅读器顺序与视觉顺序一致。
- CSS 物理方向属性扫描只允许画布、图形和明确豁免项。
