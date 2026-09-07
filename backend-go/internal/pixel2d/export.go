package pixel2d

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

type stepItem struct {
	p     Placement
	layer string
	level int
}
type buildStep struct {
	id, name, layer string
	items           []stepItem
}

func sortedPlacements(a []Placement) []Placement {
	b := append([]Placement(nil), a...)
	sort.SliceStable(b, func(i, j int) bool {
		if b[i].Y != b[j].Y {
			return b[i].Y < b[j].Y
		}
		if b[i].X != b[j].X {
			return b[i].X < b[j].X
		}
		if area(b[i]) != area(b[j]) {
			return area(b[i]) > area(b[j])
		}
		return b[i].PartID < b[j].PartID
	})
	return b
}
func exportCatalog(c ExportContext) (map[string]any, error) {
	if c.CatalogVersion != ExportVersion {
		return nil, domain("export.catalog_version_unsupported")
	}
	data, e := resources.ReadFile("resources/" + c.Locale + ".json")
	if e != nil {
		return nil, invalid("locale")
	}
	var out map[string]any
	e = json.Unmarshal(data, &out)
	return out, e
}
func exportText(c map[string]any, key string, params map[string]any) string {
	var v any = c
	for _, part := range strings.Split(key, ".") {
		v = v.(map[string]any)[part]
	}
	s := v.(string)
	for k, v := range params {
		s = strings.ReplaceAll(s, "{"+k+"}", fmt.Sprint(v))
	}
	return s
}
func projection(p Placement, level, w, h int) map[string]any {
	matrix := []int{0, 0, 1, 0, 1, 0, -1, 0, 0}
	if p.Rotation == 90 {
		matrix = []int{1, 0, 0, 0, 1, 0, 0, 0, 1}
	}
	return map[string]any{"x": (2*p.X + p.Width) * 10, "y": level, "z": (2*h - 2*p.Y - p.Height) * 10, "matrix": matrix}
}
func planPlacement(item stepItem, w, h int) map[string]any {
	p := item.p
	return map[string]any{"partId": p.PartID, "rebrickablePartNum": p.RebrickablePartNum, "legoDesignId": p.LegoDesignID, "colorId": p.ColorID, "colorName": p.ColorName, "colorRgb": p.ColorRGB, "ldrawColorCode": p.LDrawColorCode, "layer": item.layer, "ldrawY": item.level, "grid": map[string]any{"x": p.X, "y": p.Y, "level": item.level, "width": p.Width, "height": p.Height, "logicalHeightPlate": p.LogicalHeightPlate, "rotation": p.Rotation}, "ldraw": projection(p, item.level, w, h)}
}

// ExportDesign 由 Worker 预生成 LDraw/JSON 两套底座选项；GET 只读取既有产物，不执行拼搭算法。
func ExportDesign(ctx context.Context, d Design, m Metadata, base bool, c ExportContext) ([]byte, []byte, error) {
	catalog, e := exportCatalog(c)
	if e != nil {
		return nil, nil, e
	}
	steps := []buildStep{}
	layers := []any{}
	layer := func(id string, order, level int, ps []Placement) {
		items := []any{}
		for _, p := range ps {
			v := planPlacement(stepItem{p, id, level}, d.Width, d.Height)
			delete(v, "layer")
			delete(v, "ldrawY")
			items = append(items, v)
		}
		layers = append(layers, map[string]any{"id": id, "name": exportText(catalog, "layers."+id, nil), "order": order, "ldrawY": level, "placements": items})
	}
	if base {
		white, black, err := supportLayers(ctx, d, m)
		if err != nil {
			return nil, nil, err
		}
		layer("blackSupport", 0, 16, black)
		layer("whiteBase", 1, 8, white)
		white = sortedPlacements(white)
		remaining := sortedPlacements(black)
		complete := cells{}
		for start := 0; start < len(white); start += 4 {
			batch := white[start:min(start+4, len(white))]
			batchKeys := cells{}
			items := []stepItem{}
			for _, p := range batch {
				items = append(items, stepItem{p, "whiteBase", 8})
				for key := range rectangleCells(rectangle{p.X, p.Y, p.Width, p.Height}) {
					batchKeys[key] = true
					complete[key] = true
				}
			}
			rest := []Placement{}
			for _, p := range remaining {
				all, intersects := true, false
				for key := range rectangleCells(rectangle{p.X, p.Y, p.Width, p.Height}) {
					if !complete[key] {
						all = false
					}
					intersects = intersects || batchKeys[key]
				}
				if all && intersects {
					items = append(items, stepItem{p, "blackSupport", 16})
				} else {
					rest = append(rest, p)
				}
			}
			remaining = rest
			i := len(steps) + 1
			steps = append(steps, buildStep{fmt.Sprintf("base-%d", i), exportText(catalog, "steps.pixelBase", map[string]any{"index": i}), "base", items})
		}
		if len(steps) > 0 {
			for _, p := range remaining {
				steps[len(steps)-1].items = append(steps[len(steps)-1].items, stepItem{p, "blackSupport", 16})
			}
		}
	}
	layer("topDesign", 2, 0, d.Placements)
	topIndex := 0
	for y := 0; y < d.Height; y += 4 {
		items := []stepItem{}
		for _, p := range sortedPlacements(d.Placements) {
			if p.Y >= y && p.Y < y+4 {
				items = append(items, stepItem{p, "topDesign", 0})
			}
		}
		if len(items) > 0 {
			topIndex++
			steps = append(steps, buildStep{fmt.Sprintf("top-%d", topIndex), exportText(catalog, "steps.pixelTop", map[string]any{"start": y, "end": min(y+3, d.Height-1)}), "top", items})
		}
	}
	lines := []string{"0 FILE pixel-design.ldr", "0 Name: pixel-design.ldr", "0 Author: ctbzbricks", "0 // " + exportText(catalog, "documents.legoDesignPlan.title", nil), "0 // " + exportText(catalog, "documents.legoDesignPlan.description", nil), "0 // " + c.CatalogVersion}
	planSteps := []any{}
	for i, s := range steps {
		if i > 0 {
			lines = append(lines, "0 STEP")
		}
		lines = append(lines, "0 // "+s.name)
		items := []any{}
		for _, item := range s.items {
			p := item.p
			v := projection(p, item.level, d.Width, d.Height)
			matrix := v["matrix"].([]int)
			line := fmt.Sprintf("1 %s %d %d %d", p.LDrawColorCode, v["x"], v["y"], v["z"])
			for _, n := range matrix {
				line += fmt.Sprintf(" %d", n)
			}
			lines = append(lines, line+" "+p.PartID)
			items = append(items, planPlacement(item, d.Width, d.Height))
		}
		planSteps = append(planSteps, map[string]any{"id": s.id, "name": s.name, "order": i + 1, "layer": s.layer, "placements": items})
	}
	plan := map[string]any{"format": "lego-design-plan", "includeSupportBase": base, "grid": map[string]int{"width": d.Width, "height": d.Height}, "layers": layers, "steps": planSteps, "modelDimensions": d.ModelDimensions, "bom": d.BOM, "colorMappings": d.ColorMappings, "ldrawProjection": map[string]any{"lduPerStud": 20, "gridRotationMatrices": map[string]any{"0": []int{0, 0, 1, 0, 1, 0, -1, 0, 0}, "90": []int{1, 0, 0, 0, 1, 0, 0, 0, 1}, "180": []int{0, 0, -1, 0, 1, 0, 1, 0, 0}, "270": []int{-1, 0, 0, 0, 1, 0, 0, 0, -1}}, "xOriginGridWidthMultiplier": 0, "xDirection": 1, "zOriginGridHeightMultiplier": 1, "zDirection": -1}, "document": map[string]any{"schema": "brickbuilder.export.v1", "locale": c.Locale, "timezone": c.Timezone, "catalogVersion": c.CatalogVersion, "kind": "legoDesignPlan", "title": exportText(catalog, "documents.legoDesignPlan.title", nil), "description": exportText(catalog, "documents.legoDesignPlan.description", nil), "sections": catalog["sections"], "fields": catalog["fields"]}}
	data, err := json.MarshalIndent(plan, "", "  ")
	return []byte(strings.Join(lines, "\n") + "\n"), data, err
}
