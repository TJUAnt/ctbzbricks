# 当前系统功能需求

本目录是当前系统用户功能需求的根目录。文档按照前端实际菜单配置分层组织，目标是让产品、设计、开发和测试从
同一条菜单路径找到对应功能，而不是按后端包、数据库表或历史开发阶段查找。

## 1. 目录规则

```text
requirements/
├── README.md                         # 系统功能需求入口
├── model-plaza/                      # 一级菜单组：模型广场
│   ├── README.md                     # 菜单组说明
│   └── model-plaza/                  # 二级菜单项：模型广场
│       └── README.md                 # 当前功能需求
├── my-models/                        # 一级菜单组：我的模型
│   ├── README.md                     # 菜单组说明
│   ├── component-repo/               # 二级菜单项：我的模型及其下钻页面
│   │   ├── README.md                 # 个人仓库功能需求
│   │   ├── import/                   # 上传导入
│   │   ├── import-status/            # 导入进度
│   │   ├── import-history/           # 导入历史
│   │   ├── candidate-workbench/      # Candidate 审核与发布
│   │   ├── component-detail/         # Component 详情
│   │   └── watch-management/         # 订阅管理
│   └── part-search/                   # 二级菜单项：零件搜索
│       ├── README.md                 # 搜索功能需求
│       └── part-detail/              # Part 详情与 3D 查看器
└── model-tools/                      # 一级菜单组：模型工具
    └── model-2d/                     # 二级菜单项：2D 模型工具
```

- 目录名使用稳定的菜单 `id` 对应英文 kebab-case；文档标题使用当前中文菜单名称。
- 一级目录对应菜单组，二级目录对应可点击菜单项；从菜单项进入的独立子页面继续在其目录下分层。
- 每个已建目录使用 `README.md` 作为入口，链接只指向已有文档，不用空白文件冒充已整理需求。
- 菜单配置变化时，必须同步本索引及受影响的组目录；功能需求变化时同步对应功能文档。
- 本目录描述用户可观察的现行功能、边界和验收条件。代码实现、HTTP 契约、SQL、任务、迁移及性能证据仍由
  [`docs/design`](../design/README.md) 下的详细设计维护；路线图和待办不能写成当前已经可用的功能。

## 2. 当前菜单需求索引

以下层级来自 `frontend/src/app/appConfig.json` 的 `menuGroups`；“待整理”只表示需求文档尚未迁入，不代表功能
不存在或不可用。

| 一级菜单组 | 二级菜单项 | 页面路由 | 功能需求 |
|---|---|---|---|
| 模型广场 | 模型广场 | `/model-plaza` | [模型广场功能需求](./model-plaza/model-plaza/README.md) |
| 我的模型 | 我的模型 | `/component-repo` | [个人 Component 仓库功能需求](./my-models/component-repo/README.md) |
| 我的模型 | 零件搜索 | `/part-search` | [Part Search 功能需求](./my-models/part-search/README.md) |
| 模型工具 | 2D 模型工具 | `/pixel-art` | 待整理 |

## 3. 文档状态约定

| 状态 | 含义 |
|---|---|
| 当前功能 | 已有代码与验证证据支持；部署状态仍需在文档中单独说明 |
| 部分实现 | 只有部分验收条件有代码或验证证据，未完成部分必须明确列出 |
| 规划 | 尚未成为当前系统能力，不得写成用户已经可以使用 |
| 待整理 | 功能可能存在，但尚未按本目录规范形成需求文档 |

当前已建立的功能文档：

- [模型广场 / 模型广场](./model-plaza/model-plaza/README.md)
- [我的模型 / 个人 Component 仓库](./my-models/component-repo/README.md)
- [我的模型 / 零件搜索](./my-models/part-search/README.md)
