# DEM Final Design 代码问题汇总

## 代码架构

```
前端 LegoDesignPage.tsx
  └─ createDemFinalDesignRequest() → POST /api/dem-lego-design/final-design (同步)
        └─ dem_final_design_service.load_final_dem_design()
             ├─ ① validate_surface_part_ids()
             ├─ ② load_part_surface_profile_models()   — LDraw mesh 解析 + 表面轮廓采样
             ├─ ③ generate_surface_patch_candidates()   — 位置/旋转/基高组合候选
             ├─ ④ load_dem_structure_parts()            — DB 查 Plate/Brick 结构件
             ├─ ⑤ solve_surface_plan()                  — 回溯搜索全局精确覆盖
             ├─ ⑥ build_base_h_structure()              — 自底向上搭支撑结构
             ├─ ⑦ load_surface_metadata()               — 颜色 + 交叉引用元数据
             └─ ⑧ assemble_final_dem_design()           — 拼装结果 + 全量校验
```

---

## 一、同步调用风险

**文件:** `backend/src/services/dem_final_design_service.py` — `load_final_dem_design()`

`/api/dem-lego-design/final-design` 是同步 API（无 Job 轮询），核心算法 `solve_surface_plan()` 使用回溯搜索求解全局精确覆盖问题。当地形较大、候选数量多时，回溯搜索时间可能显著增长，导致 HTTP 请求超时。

**建议:** 对大尺寸地形采用异步 Job 模式，或添加超时保底逻辑。

---

## 二、while True 无限循环风险

**文件:** `backend/src/services/dem_final_design_service.py` L299-L318

```python
rejected_base_h = set()
while True:
    plan = solve_surface_plan(...)
    structure = build_base_h_structure(...)  # 失败 → rejected_base_h.add(plan.base_h) → continue
```

如果 `build_base_h_structure` 对所有可能的 base_h 都失败、但 `solve_surface_plan` 仍能生成新组合，循环会持续重试。理论上 search 空间有限（candidates 固定），但缺乏显式上限保护。

**建议:** 增加 `max_retries` 限制。

---

## 三、LDraw 文件系统硬依赖

**文件:** `backend/src/services/dem_lego_design_service.py` L36-L60

```python
root = Path(profile_config["ldraw_root"])  # "D:\\Program Files\\LDraw"
```

在非本地开发环境（CI/服务器）该路径不存在，`load_part_surface_profile_models()` 会直接失败，错误信息不直观。

**建议:** 加载前校验路径存在性；区分 dev/prod 配置。

---

## 四、无表面轮廓缓存

**文件:** `backend/src/services/dem_lego_design_service.py` — `load_part_surface_profile_models()`

每次请求都重新解析 LDraw `.dat` 文件 + 三角剖分 + 表面采样，同一零件在不同请求中被重复计算。

**建议:** 对 `PartSurfaceProfile` 对象按 `part_id` 做内存 LRU 缓存。

---

## 五、seam_error 边界计算隐患

**文件:** `backend/src/services/dem_surface_plan_service.py` L84-L119

```python
if offset["x"] == 1:
    left_sample_x = neighbor_x * sample_rate - 1  # neighbor_x=0 → left_sample_x=-1
```

当 `neighbor_x == 0` 时 `left_sample_x == -1`，Python 中 `target_surface[sample_z][-1]` 会取到最后一列而非报错，可能导致 seam_error 计算偏差。`neighbor_z == 0` 同理。

**建议:** 添加 `>= 0` 显式边界检查。

---

## 六、三个端点共用同一个请求 Schema

**文件:** `backend/src/api/routes/dem_lego_design.py` L79-L115

`/surface-patch/candidates`、`/surface-plan`、`/final-design` 都使用 `DemSurfacePatchCandidatesRequest`。三个端点语义不同但契约一样，API 设计不够清晰。

**建议:** 为 `/final-design` 定义独立的 Request Schema（或至少加注释）。

---

## 七、验证失败信息过于笼统

**文件:** `backend/src/services/dem_final_design_service.py` L180-L192

所有验证条件（体积不匹配、碰撞数非零、支撑数非零、BOM 计数不一致等）失败时都抛出同一错误消息 `"final validation failed"`，无法定位具体原因。

**建议:** 返回具体失败条件，例如 "volume mismatch: target=120, placed=118"。

---

## 八、前端 partIds 与后端数据一致性

**文件:** `frontend/src/legoDesign/legoDesignConfig.json` L30-L38

```json
"partIds": ["3024.dat", "54200.dat", "5404.dat", "3040b.dat",
            "3039.dat", "4286.dat", "3044b.dat", "3300.dat"]
```

如果这些零件在 `LDrawPart` 表或文件系统中缺失，运行时才会暴露。同时零件库的选择直接影响 DEM 拟合质量。

**建议:** 应用启动时预检查零件可用性；或暴露 API 返回可用零件列表供前端动态选择。

---

## 九、颜色 RGB 空字符串绕过 None 检查

**文件:** `backend/src/services/dem_final_design_service.py` L246-L249

```python
if set(colors) != color_ids or any(colors[color_id].rgb is None for color_id in color_ids):
```

`rgb is None` 无法拦截空字符串 `""`，后续 `color.rgb.upper()` 会产生错误的 LDraw 颜色代码。

**建议:** 改为 `if ... or any(not colors[color_id].rgb for color_id in color_ids)`。

---

## 十、新旧两条路由并行存在

**文件:** `backend/src/api/main.py` L213-L214

```python
app.include_router(create_lego_design_router(lego_design_config))
app.include_router(create_dem_lego_design_router(dem_lego_design_config))
```

DEM 路线与旧 `lego_design` 路线同时注册，前端按资产类型分流。如果意向是完全迁移到 DEM 路线，需制定旧路由的清理计划。
