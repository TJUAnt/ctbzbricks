# 当前系统详细功能设计

本目录是当前系统详细功能设计的根目录。与 [`docs/requirements`](../requirements/README.md) 一致，当前功能设计
按照前端实际菜单层级组织，使需求、实现、接口和验证证据可以沿同一条菜单路径定位。

## 1. 目录规则

```text
design/
├── README.md                         # 当前系统详细功能设计入口
├── model-plaza/                      # 一级菜单组：模型广场
│   ├── README.md                     # 菜单组设计索引
│   └── model-plaza/                  # 二级菜单项：模型广场
│       └── README.md                 # 组件广场详细设计
├── my-models/                        # 一级菜单组：我的模型
│   ├── README.md                     # 菜单组设计索引
│   ├── component-repo/               # 二级菜单项：我的模型
│   │   ├── README.md                 # Component 主设计
│   │   ├── star.md                   # 收藏领域设计
│   │   ├── star-design-and-roadmap.md
│   │   ├── watch.md                  # 订阅领域设计
│   │   └── watch-design-and-roadmap.md
│   └── part-search/                  # 二级菜单项：零件搜索
│       └── README.md                 # Part Library / Part Search 设计
└── model-tools/                      # 一级菜单组：模型小工具
    ├── README.md                     # 菜单组索引（含规划项）
    └── model-3d/                     # 规划二级菜单项：3D 模型构建 LEGO
        └── README.md                 # 菜单级方案草案
```

- 一级目录对应菜单组，二级目录对应可点击菜单项；共享领域设计放在主要所属菜单项目录内。
- `README.md` 作为每一级入口；功能需求与详细设计应互相链接。
- 本目录记录代码调用、HTTP 接口、Go 服务、SQL、任务、权限、i18n、验证证据和实现偏移。
- ADR、迁移路线、算法方案、部署和专项技术文档仍按其自身领域目录维护，不因本索引重复搬迁。

## 2. 当前菜单设计索引

| 一级菜单组 | 二级菜单项 | 页面路由 | 功能需求 | 详细设计 |
|---|---|---|---|---|
| 模型广场 | 模型广场 | `/model-plaza` | [功能需求](../requirements/model-plaza/model-plaza/README.md) | [组件广场详细设计](./model-plaza/model-plaza/README.md) |
| 我的模型 | 我的模型 | `/component-repo` | [功能需求](../requirements/my-models/component-repo/README.md) | [Component 详细设计](./my-models/component-repo/README.md) |
| 我的模型 | 零件搜索 | `/part-search` | [功能需求](../requirements/my-models/part-search/README.md) | [Part Library 详细设计](./my-models/part-search/README.md) |
| 模型工具 | 2D 模型工具 | `/pixel-art` | 待整理 | 待按菜单结构整理 |

规划中的“模型小工具 / 3D 模型构建 LEGO”见[菜单级设计草案](./model-tools/model-3d/README.md)与
[功能需求草案](../requirements/model-tools/model-3d/README.md)；当前没有对应菜单项或确定路由，不计入上表。

## 3. 共享领域设计

- [Star 详细设计](./my-models/component-repo/star.md)
- [Star 产品与容量路线](./my-models/component-repo/star-design-and-roadmap.md)
- [Watch 详细设计](./my-models/component-repo/watch.md)
- [Watch 产品与容量路线](./my-models/component-repo/watch-design-and-roadmap.md)

上述设计服务于 Component Repo、Component 详情及模型广场，但其关系所有权和写操作边界归属于 Component Repo，
因此统一放在“我的模型 / 我的模型”目录。

## 4. 其他设计资料

[Shape 分块总览与专题](./lego_shape_decomposition_design.md)是规划中 3D 模型构建 LEGO 功能的研究资料，
由菜单级设计草案索引；研究文档本身不代表当前系统已具备该功能。
