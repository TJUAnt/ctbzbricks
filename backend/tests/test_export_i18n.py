"""Snapshot-style contract tests for deterministic localized exports."""

import json
import unittest

from src.i18n.export_catalog import (
    EXPORT_CATALOG_VERSION,
    content_disposition,
    create_export_context,
    dem_design_report,
    localized_filename,
    localize_lego_plan,
    validate_export_context,
)


class ExportI18nTest(unittest.TestCase):
    def test_lego_plan_and_bom_snapshots_are_localized_without_translating_machine_fields(self) -> None:
        plan = {
            "format": "lego-design-plan",
            "layers": [{"id": "topDesign", "name": "Top pixel design"}],
            "steps": [{"id": "top-1", "name": "Top rows 0-3", "layer": "top"}],
            "bom": [{"partId": "3024.dat", "colorName": "Red", "quantity": 4}],
        }

        snapshots = {}
        for locale in ("en-US", "zh-CN"):
            localized = localize_lego_plan(plan, create_export_context(locale, "Asia/Shanghai"))
            snapshots[locale] = {
                "document": localized["document"],
                "layerName": localized["layers"][0]["name"],
                "stepName": localized["steps"][0]["name"],
                "bom": localized["bom"],
            }

        self.assertEqual(
            json.dumps(snapshots, ensure_ascii=False, sort_keys=True),
            json.dumps(
                {
                    "en-US": {
                        "document": {
                            "schema": "brickbuilder.export.v1",
                            "locale": "en-US",
                            "timezone": "Asia/Shanghai",
                            "catalogVersion": EXPORT_CATALOG_VERSION,
                            "kind": "legoDesignPlan",
                            "title": "LEGO Design Plan",
                            "description": "Deterministic construction plan and bill of materials.",
                            "sections": {
                                "layers": "Layers",
                                "steps": "Build steps",
                                "dimensions": "Model dimensions",
                                "bom": "Bill of materials",
                                "colorMappings": "Color mappings",
                                "validation": "Validation report",
                            },
                            "fields": {
                                "partId": "Part ID", "partName": "Part name", "color": "Color",
                                "quantity": "Quantity", "width": "Width", "height": "Height",
                                "depth": "Depth", "role": "Role", "stage": "Stage",
                                "status": "Status", "metric": "Metric", "value": "Value",
                            },
                        },
                        "layerName": "Top pixel design",
                        "stepName": "Top rows 0-3",
                        "bom": [{"partId": "3024.dat", "colorName": "Red", "quantity": 4}],
                    },
                    "zh-CN": {
                        "document": {
                            "schema": "brickbuilder.export.v1",
                            "locale": "zh-CN",
                            "timezone": "Asia/Shanghai",
                            "catalogVersion": EXPORT_CATALOG_VERSION,
                            "kind": "legoDesignPlan",
                            "title": "乐高设计搭建方案",
                            "description": "包含搭建步骤与物料清单的确定性设计方案。",
                            "sections": {
                                "layers": "设计分层", "steps": "搭建步骤", "dimensions": "模型尺寸",
                                "bom": "物料清单", "colorMappings": "颜色映射", "validation": "验证报告",
                            },
                            "fields": {
                                "partId": "零件编号", "partName": "零件名称", "color": "颜色",
                                "quantity": "数量", "width": "宽度", "height": "高度", "depth": "深度",
                                "role": "用途", "stage": "阶段", "status": "状态",
                                "metric": "指标", "value": "数值",
                            },
                        },
                        "layerName": "顶层像素图案",
                        "stepName": "顶层第 0–3 行",
                        "bom": [{"partId": "3024.dat", "colorName": "Red", "quantity": 4}],
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

    def test_dem_report_snapshot_uses_frozen_context(self) -> None:
        context = create_export_context("zh-Hans-CN", "Asia/Shanghai")
        design = {
            "modelId": "taiwan-01",
            "strategy": "surface-plan",
            "steps": [{
                "id": "dem-step-1", "name": "Base layer 2", "stage": "structure", "basePlate": 2,
            }],
            "bom": [{"partId": "3005.dat", "quantity": 8}],
            "validation": {"totalPlacementCount": 8},
        }
        report = dem_design_report(design, context)

        self.assertEqual(
            {
                "title": report["document"]["title"],
                "catalogVersion": report["document"]["catalogVersion"],
                "step": report["design"]["steps"][0]["name"],
                "bom": report["design"]["bom"],
                "validation": report["design"]["validation"],
            },
            {
                "title": "DEM 乐高地形设计报告",
                "catalogVersion": EXPORT_CATALOG_VERSION,
                "step": "基础结构第 2 层",
                "bom": [{"partId": "3005.dat", "quantity": 8}],
                "validation": {"totalPlacementCount": 8},
            },
        )

    def test_catalog_version_and_unicode_filename_contract(self) -> None:
        context = create_export_context("zh-CN", "UTC")
        filename = localized_filename(context, "demReport", modelId="../../taiwan:01")
        disposition = content_disposition(filename)

        self.assertEqual(filename, "DEM乐高地形-taiwan-01-设计报告.json")
        self.assertIn('filename="DEM-taiwan-01-.json"', disposition)
        self.assertIn("filename*=UTF-8''DEM%E4%B9%90%E9%AB%98", disposition)
        with self.assertRaisesRegex(ValueError, "export.catalog_version_unsupported"):
            validate_export_context({**context, "catalogVersion": "unknown"})


if __name__ == "__main__":
    unittest.main()
