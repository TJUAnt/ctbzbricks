package pixel2d

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"
)

type cell struct{ x, y int }
type cells map[cell]bool
type rectangle struct{ x, y, w, h int }

func area(p Placement) int { return p.Width * p.Height }
func normalParts(input []Part) []Part {
	a := append([]Part(nil), input...)
	sort.SliceStable(a, func(i, j int) bool {
		if a[i].Area != a[j].Area {
			return a[i].Area > a[j].Area
		}
		return a[i].LDrawPartNum < a[j].LDrawPartNum
	})
	out := []Part{}
	seen := map[[2]int]bool{}
	for _, p := range a {
		k := [2]int{min(p.Width, p.Height), max(p.Width, p.Height)}
		if !seen[k] {
			out = append(out, p)
			seen[k] = true
		}
	}
	return out
}
func placement(p Part, c Color, x, y, w, h, rotation int) Placement {
	return Placement{PartID: p.LDrawPartNum, RebrickablePartNum: p.RebrickablePartNum, LegoDesignID: p.LegoDesignID, ColorID: c.ID, ColorName: c.Name, ColorRGB: strings.ToUpper(c.RGB), LDrawColorCode: "0x2" + strings.TrimPrefix(strings.ToUpper(c.RGB), "#"), X: x, Y: y, Width: w, Height: h, LogicalHeightPlate: p.LogicalHeightPlate, Rotation: rotation}
}
func validPlace(p Placement, remaining cells) bool {
	for y := p.Y; y < p.Y+p.Height; y++ {
		for x := p.X; x < p.X+p.Width; x++ {
			if !remaining[cell{x, y}] {
				return false
			}
		}
	}
	return true
}
func removePlace(p Placement, remaining cells) {
	for y := p.Y; y < p.Y+p.Height; y++ {
		for x := p.X; x < p.X+p.Width; x++ {
			delete(remaining, cell{x, y})
		}
	}
}
func topLeft(a cells) cell {
	best := cell{math.MaxInt, math.MaxInt}
	for c := range a {
		if c.y < best.y || (c.y == best.y && c.x < best.x) {
			best = c
		}
	}
	return best
}
func copyCells(a cells) cells {
	b := cells{}
	for c := range a {
		b[c] = true
	}
	return b
}
func connected(a cells) []cells {
	rest := copyCells(a)
	out := []cells{}
	for len(rest) > 0 {
		first := topLeft(rest)
		delete(rest, first)
		queue := []cell{first}
		group := cells{first: true}
		for i := 0; i < len(queue); i++ {
			c := queue[i]
			for _, n := range []cell{{c.x - 1, c.y}, {c.x + 1, c.y}, {c.x, c.y - 1}, {c.x, c.y + 1}} {
				if rest[n] {
					delete(rest, n)
					group[n] = true
					queue = append(queue, n)
				}
			}
		}
		out = append(out, group)
	}
	return out
}
func largestRectangle(a cells) rectangle {
	x0, y0, x1, y1 := math.MaxInt, math.MaxInt, 0, 0
	for c := range a {
		x0 = min(x0, c.x)
		y0 = min(y0, c.y)
		x1 = max(x1, c.x)
		y1 = max(y1, c.y)
	}
	heights := make([]int, x1-x0+2)
	best := rectangle{}
	for y := y0; y <= y1; y++ {
		for x := x0; x <= x1; x++ {
			if a[cell{x, y}] {
				heights[x-x0]++
			} else {
				heights[x-x0] = 0
			}
		}
		stack := []int{}
		for i, h := range heights {
			for len(stack) > 0 && heights[stack[len(stack)-1]] > h {
				height := heights[stack[len(stack)-1]]
				stack = stack[:len(stack)-1]
				left := 0
				if len(stack) > 0 {
					left = stack[len(stack)-1] + 1
				}
				width := i - left
				if width*height > best.w*best.h {
					best = rectangle{x0 + left, y - height + 1, width, height}
				}
			}
			stack = append(stack, i)
		}
	}
	return best
}
func bestAt(c cell, a cells, parts []Part, color Color) (Placement, bool) {
	best := Placement{}
	for _, p := range parts {
		for rotation := 0; rotation <= 90; rotation += 90 {
			if rotation == 90 && p.Width == p.Height {
				continue
			}
			w, h := p.Width, p.Height
			if rotation == 90 {
				w, h = h, w
			}
			candidate := placement(p, color, c.x, c.y, w, h, rotation)
			if w*h > area(best) && validPlace(candidate, a) {
				best = candidate
			}
		}
	}
	return best, area(best) > 0
}
func rectangleCells(r rectangle) cells {
	a := cells{}
	for y := r.y; y < r.y+r.h; y++ {
		for x := r.x; x < r.x+r.w; x++ {
			a[cell{x, y}] = true
		}
	}
	return a
}
func greedy(ctx context.Context, a cells, parts []Part, color Color) ([]Placement, error) {
	out := []Placement{}
	for len(a) > 0 {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		p, ok := bestAt(topLeft(a), a, parts, color)
		if !ok {
			return nil, domain("lego_design.generation_failed")
		}
		out = append(out, p)
		removePlace(p, a)
	}
	return out, nil
}

// solveCells 先最大矩形分解再重新合并；目录必须有 1×1 Plate，保证任意像素区域可完整覆盖。
func solveCells(ctx context.Context, a cells, parts []Part, color Color) ([]Placement, error) {
	out := []Placement{}
	queue := connected(a)
	for len(queue) > 0 {
		if e := ctx.Err(); e != nil {
			return nil, e
		}
		group := queue[0]
		queue = queue[1:]
		r := largestRectangle(group)
		ps, e := greedy(ctx, rectangleCells(r), parts, color)
		if e != nil {
			return nil, e
		}
		out = append(out, ps...)
		for _, p := range ps {
			removePlace(p, group)
		}
		queue = append(queue, connected(group)...)
	}
	merged, e := greedy(ctx, copyCells(a), parts, color)
	if e == nil && len(merged) <= len(out) {
		return merged, nil
	}
	return out, nil
}

// GenerateDesign 把不可变项目映射到冻结目录，验证覆盖/颜色/无重叠后生成 BOM。
func GenerateDesign(ctx context.Context, p Project, m Metadata) (Design, error) {
	if err := ValidateMetadata(m); err != nil {
		return Design{}, err
	}
	if _, err := normalizePixels(&p); err != nil {
		return Design{}, err
	}
	colors := map[int]Color{}
	rgbs := make([]rgb, len(m.Colors))
	for i, c := range m.Colors {
		rgbs[i], _ = parseHex(c.RGB)
		colors[c.ID] = c
	}
	mappings := []Mapping{}
	byRGB := map[string]Color{}
	for _, v := range p.Palette {
		vRGB, _ := parseHex(v.RGB)
		c := m.Colors[nearest(vRGB, rgbs)]
		byRGB[v.RGB] = c
		mappings = append(mappings, Mapping{v.RGB, c.ID, c.Name, strings.ToUpper(c.RGB), "0x2" + strings.TrimPrefix(strings.ToUpper(c.RGB), "#")})
	}
	groups := map[int]cells{}
	order := []int{}
	for _, v := range p.Pixels {
		c := byRGB[v.RGB]
		if groups[c.ID] == nil {
			groups[c.ID] = cells{}
			order = append(order, c.ID)
		}
		groups[c.ID][cell{v.X, v.Y}] = true
	}
	out := []Placement{}
	parts := normalParts(m.Parts)
	for _, id := range order {
		ps, e := solveCells(ctx, groups[id], parts, colors[id])
		if e != nil {
			return Design{}, e
		}
		out = append(out, ps...)
	}
	covered := cells{}
	for _, v := range out {
		for y := v.Y; y < v.Y+v.Height; y++ {
			for x := v.X; x < v.X+v.Width; x++ {
				key := cell{x, y}
				if covered[key] || !groups[v.ColorID][key] {
					return Design{}, domain("lego_design.generation_failed")
				}
				covered[key] = true
			}
		}
	}
	if len(covered) != len(p.Pixels) {
		return Design{}, domain("lego_design.generation_failed")
	}
	return Design{p.GridWidth, p.GridHeight, out, createBOM(out), mappings, Dimensions{p.GridWidth, p.GridHeight, 1, float64(p.GridWidth) * .8, float64(p.GridHeight) * .8, .32}}, nil
}
func createBOM(ps []Placement) []BOMItem {
	out := []BOMItem{}
	index := map[string]int{}
	for _, p := range ps {
		key := fmt.Sprintf("%s:%d:%s:%d:%d", p.PartID, p.ColorID, p.LDrawColorCode, p.Width, p.Height)
		if i, ok := index[key]; ok {
			out[i].Quantity++
		} else {
			index[key] = len(out)
			out = append(out, BOMItem{key, p.PartID, p.RebrickablePartNum, p.LegoDesignID, p.ColorID, p.ColorName, p.ColorRGB, p.LDrawColorCode, p.Width, p.Height, 1})
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Quantity > out[j].Quantity })
	return out
}

// supportLayers 在白底接缝与外边框构造黑色连接层；不会让窄图底座越出网格。
func supportLayers(ctx context.Context, d Design, m Metadata) ([]Placement, []Placement, error) {
	parts := normalParts(m.Parts)
	white, e := greedy(ctx, rectangleCells(rectangle{0, 0, d.Width, d.Height}), parts, Color{ID: 15, Name: "White", RGB: "#FFFFFF"})
	if e != nil {
		return nil, nil, e
	}
	keys := cells{}
	owner := map[cell]int{}
	for i, p := range white {
		for c := range rectangleCells(rectangle{p.X, p.Y, p.Width, p.Height}) {
			owner[c] = i
		}
	}
	for y := 0; y < d.Height; y++ {
		for x := 0; x < d.Width; x++ {
			c := cell{x, y}
			if x < 2 || y < 2 || x >= d.Width-2 || y >= d.Height-2 {
				keys[c] = true
			}
			for _, n := range []cell{{x + 1, y}, {x, y + 1}} {
				if idx, ok := owner[n]; ok && idx != owner[c] {
					keys[c] = true
					keys[n] = true
				}
			}
		}
	}
	// 与原扩张策略一致：基于原集合一次选取“至少覆盖两格、额外最多一格”的候选。
	expanded := copyCells(keys)
	for _, p := range parts {
		for r := 0; r <= 90; r += 90 {
			w, h := p.Width, p.Height
			if r == 90 {
				w, h = h, w
			}
			for y := 0; y <= d.Height-h; y++ {
				for x := 0; x <= d.Width-w; x++ {
					covered := 0
					extra := []cell{}
					for yy := y; yy < y+h; yy++ {
						for xx := x; xx < x+w; xx++ {
							c := cell{xx, yy}
							if keys[c] {
								covered++
							} else {
								extra = append(extra, c)
							}
						}
					}
					if covered >= 2 && len(extra) == 1 {
						expanded[extra[0]] = true
					}
				}
			}
		}
	}
	black, e := solveCells(ctx, expanded, parts, Color{ID: 0, Name: "Black", RGB: "#000000"})
	for i := range white {
		white[i].LDrawColorCode = "15"
	}
	for i := range black {
		black[i].LDrawColorCode = "0"
	}
	return white, black, e
}
