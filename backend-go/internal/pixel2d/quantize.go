package pixel2d

import (
	"bytes"
	"context"
	"fmt"
	_ "golang.org/x/image/webp"
	"image"
	"image/color"
	_ "image/jpeg"
	"image/png"
	"math"
	"slices"
	"strconv"
	"strings"
)

type rgb [3]float64

func distance(a, b rgb) float64 {
	d := 0.0
	for i := range 3 {
		d += (a[i] - b[i]) * (a[i] - b[i])
	}
	return math.Sqrt(d/3) / 255
}
func hex(c rgb) string { return fmt.Sprintf("#%02X%02X%02X", int(c[0]), int(c[1]), int(c[2])) }
func parseHex(s string) (rgb, error) {
	if len(s) != 7 || s[0] != '#' {
		return rgb{}, invalid("rgb")
	}
	n, e := strconv.ParseUint(s[1:], 16, 24)
	return rgb{float64(n >> 16), float64(n >> 8 & 255), float64(n & 255)}, e
}
func clip(v float64) float64 { return math.Floor(math.Max(0, math.Min(255, v))) }

// ValidateSettings 在接受上传前约束所有数值；实际解码尺寸及裁剪边界由 Worker 二次验证。
func ValidateSettings(s Settings) error {
	if !slices.Contains([]string{"photo_illustration", "logo_text", "side_mixed_plate_brick_pixel"}, s.Algorithm) {
		return domain("pixel_art.invalid_settings")
	}
	if s.GridWidth < 1 || s.GridWidth > 128 || s.GridHeight < 1 || s.GridHeight > 128 {
		return domain("pixel_art.invalid_grid")
	}
	if !slices.Contains([]int{2, 4, 8, 16, 24, 32, 48, 64}, s.ColorCount) {
		return domain("pixel_art.invalid_color_count")
	}
	p := s.Preprocessing
	for _, v := range [][3]float64{{p.Brightness, .7, 1.3}, {p.Contrast, .7, 1.6}, {p.Saturation, .5, 1.5}, {p.Sharpness, .7, 1.8}, {p.LocalContrast, 0, 1}} {
		if math.IsNaN(v[0]) || math.IsInf(v[0], 0) || v[0] < v[1] || v[0] > v[2] {
			return domain("pixel_art.invalid_settings")
		}
	}
	if s.Crop.X < 0 || s.Crop.Y < 0 || s.Crop.Width < 1 || s.Crop.Height < 1 {
		return domain("pixel_art.invalid_crop")
	}
	return nil
}

// Quantize 执行三种原有算法；先 DecodeConfig 限制解压面积，避免小文件导致内存爆炸。
func Quantize(ctx context.Context, data []byte, s Settings) (Project, []byte, error) {
	if err := ValidateSettings(s); err != nil {
		return Project{}, nil, err
	}
	cfg, format, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil || !slices.Contains([]string{"jpeg", "png", "webp"}, format) {
		return Project{}, nil, domain("pixel_art.unsupported_image_type")
	}
	if cfg.Width < 1 || cfg.Height < 1 || int64(cfg.Width)*int64(cfg.Height) > 32_000_000 {
		return Project{}, nil, domain("pixel_art.invalid_grid")
	}
	c := s.Crop
	if c.X > cfg.Width || c.Y > cfg.Height || c.Width > cfg.Width-c.X || c.Height > cfg.Height-c.Y {
		return Project{}, nil, domain("pixel_art.invalid_crop")
	}
	source, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return Project{}, nil, domain("pixel_art.generation_failed")
	}
	pixels := make([]rgb, c.Width*c.Height)
	for y := 0; y < c.Height; y++ {
		if err := ctx.Err(); err != nil {
			return Project{}, nil, err
		}
		for x := 0; x < c.Width; x++ {
			r, g, b, a := source.At(c.X+x, c.Y+y).RGBA()
			pixels[y*c.Width+x] = rgb{math.Round(float64(r+65535-a) / 257), math.Round(float64(g+65535-a) / 257), math.Round(float64(b+65535-a) / 257)}
		}
	}
	var small, mapped []rgb
	if s.Algorithm == "logo_text" {
		palette, e := kmeans(ctx, pixels, s.ColorCount)
		if e != nil {
			return Project{}, nil, e
		}
		// 每个原图块先映射到全图众数调色板，再选块内众数，保留文字/标志边缘。
		small = make([]rgb, s.GridWidth*s.GridHeight)
		for y := 0; y < s.GridHeight; y++ {
			if e := ctx.Err(); e != nil {
				return Project{}, nil, e
			}
			for x := 0; x < s.GridWidth; x++ {
				x0, y0 := x*c.Width/s.GridWidth, y*c.Height/s.GridHeight
				x1, y1 := min(c.Width, max(x0+1, (x+1)*c.Width/s.GridWidth)), min(c.Height, max(y0+1, (y+1)*c.Height/s.GridHeight))
				counts := map[rgb]int{}
				order := []rgb{}
				for yy := y0; yy < y1; yy++ {
					for xx := x0; xx < x1; xx++ {
						v := palette[nearest(pixels[yy*c.Width+xx], palette)]
						if counts[v] == 0 {
							order = append(order, v)
						}
						counts[v]++
					}
				}
				best := order[0]
				for _, v := range order {
					if counts[v] > counts[best] {
						best = v
					}
				}
				small[y*s.GridWidth+x] = best
			}
		}
		mapped = small
	} else {
		pixels = preprocess(pixels, c.Width, c.Height, s)
		small = boxResize(pixels, c.Width, c.Height, s.GridWidth, s.GridHeight)
		palette, e := kmeans(ctx, small, s.ColorCount)
		if e != nil {
			return Project{}, nil, e
		}
		mapped = make([]rgb, len(small))
		for i, v := range small {
			mapped[i] = palette[nearest(v, palette)]
		}
	}
	p := Project{Schema: "pixel-art-v1", GridWidth: s.GridWidth, GridHeight: s.GridHeight, ColorCount: s.ColorCount, Pixels: make([]Pixel, len(mapped))}
	for i, v := range mapped {
		p.Pixels[i] = Pixel{X: i % s.GridWidth, Y: i / s.GridWidth, RGB: hex(v), SourceColor: hex(small[i]), QuantizedColor: hex(v)}
	}
	if s.Algorithm == "side_mixed_plate_brick_pixel" {
		sideMetadata(&p)
	}
	preview, err := normalizePixels(&p)
	return p, preview, err
}
func nearest(v rgb, palette []rgb) int {
	best := 0
	d := math.Inf(1)
	for i, c := range palette {
		if n := distance(v, c); n < d {
			best = i
			d = n
		}
	}
	return best
}

// kmeans 保持首次出现的稳定顺序及众数回落；禁止 Go map 迭代顺序影响最终颜色。
func kmeans(ctx context.Context, pixels []rgb, k int) ([]rgb, error) {
	counts, order := map[rgb]int{}, []rgb{}
	step := (len(pixels) + 49999) / 50000
	for i := 0; i < len(pixels); i += step {
		v := pixels[i]
		if counts[v] == 0 {
			order = append(order, v)
		}
		counts[v]++
	}
	first := order[0]
	for _, v := range order {
		if counts[v] > counts[first] {
			first = v
		}
	}
	centers := []rgb{first}
	for len(centers) < min(k, len(order)) {
		best := order[0]
		score := -1.0
		for _, v := range order {
			n := float64(counts[v]) * distance(v, centers[nearest(v, centers)])
			if n > score {
				best = v
				score = n
			}
		}
		centers = append(centers, best)
	}
	for range 16 {
		if e := ctx.Err(); e != nil {
			return nil, e
		}
		sums := make([]rgb, len(centers))
		weights := make([]int, len(centers))
		for _, v := range order {
			i := nearest(v, centers)
			weights[i] += counts[v]
			for ch := range 3 {
				sums[i][ch] += v[ch] * float64(counts[v])
			}
		}
		movement := 0.0
		for i := range centers {
			if weights[i] == 0 {
				continue
			}
			for ch := range 3 {
				sums[i][ch] /= float64(weights[i])
			}
			movement += distance(centers[i], sums[i]) * 255 * math.Sqrt(3)
			centers[i] = sums[i]
		}
		if movement <= .5 {
			break
		}
	}
	full, seq := map[rgb]int{}, []rgb{}
	for _, v := range pixels {
		if full[v] == 0 {
			seq = append(seq, v)
		}
		full[v]++
	}
	best, weights := make([]rgb, len(centers)), make([]int, len(centers))
	for _, v := range seq {
		i := nearest(v, centers)
		if full[v] > weights[i] {
			best[i] = v
			weights[i] = full[v]
		}
	}
	palette := []rgb{}
	for i, v := range best {
		if weights[i] > 0 && !slices.Contains(palette, v) {
			palette = append(palette, v)
		}
	}
	return palette, nil
}
func luminance(v rgb) float64 {
	return math.Floor((v[0]*19595 + v[1]*38470 + v[2]*7471 + 32768) / 65536)
}
func blend(a, b rgb, f float64) rgb {
	var out rgb
	for i := range 3 {
		out[i] = clip(float64(float32(a[i]) + float32(f)*float32(b[i]-a[i])))
	}
	return out
}
func preprocess(input []rgb, w, h int, s Settings) []rgb {
	p := s.Preprocessing
	a := make([]rgb, len(input))
	mean := 0.0
	for i, v := range input {
		a[i] = blend(rgb{}, v, p.Brightness)
		mean += luminance(a[i])
	}
	mean = math.Floor(mean/float64(len(a)) + .5)
	for i, v := range a {
		v = blend(rgb{mean, mean, mean}, v, p.Contrast)
		gray := luminance(v)
		a[i] = blend(rgb{gray, gray, gray}, v, p.Saturation)
	}
	b := slices.Clone(a)
	for y := 1; y < h-1; y++ {
		for x := 1; x < w-1; x++ {
			var sm rgb
			for dy := -1; dy <= 1; dy++ {
				for dx := -1; dx <= 1; dx++ {
					weight := 1.0
					if dx == 0 && dy == 0 {
						weight = 5
					}
					for ch := range 3 {
						sm[ch] += a[(y+dy)*w+x+dx][ch] * weight
					}
				}
			}
			for ch := range 3 {
				sm[ch] = math.Floor(sm[ch]/13 + .5)
			}
			b[y*w+x] = blend(sm, a[y*w+x], p.Sharpness)
		}
	}
	if p.LocalContrast > 0 {
		hist := [256]int{}
		ys := make([]int, len(b))
		for i, v := range b {
			ys[i] = (fixed6(.299, v[0]) + fixed6(.587, v[1]) + fixed6(.114, v[2])) >> 6
			hist[ys[i]]++
		}
		last := 255
		for last > 0 && hist[last] == 0 {
			last--
		}
		step := (len(b) - hist[last]) / 255
		lut := [256]int{}
		sum := step / 2
		for i, n := range hist {
			lut[i] = i
			if step > 0 {
				lut[i] = min(255, sum/step)
			}
			sum += n
		}
		{
			for i, v := range b {
				yy := int(float32(ys[i]) + float32(p.LocalContrast)*float32(lut[ys[i]]-ys[i]))
				cb := (fixed6(-.16874, v[0]) + fixed6(-.33126, v[1]) + fixed6(.5, v[2])) >> 6
				cr := (fixed6(.5, v[0]) + fixed6(-.41869, v[1]) + fixed6(-.08131, v[2])) >> 6
				b[i] = rgb{clip(float64(yy + (fixed6(1.402, float64(cr)) >> 6))), clip(float64(yy + ((fixed6(-.34414, float64(cb)) + fixed6(-.71414, float64(cr))) >> 6))), clip(float64(yy + (fixed6(1.772, float64(cb)) >> 6)))}
			}
		}
	}
	return b
}

// boxResize 采用 separable BOX 与像素中心采样；两个方向各自舍入以对应 Pillow 的 RGB 缩放。
func boxResize(a []rgb, w, h, nw, nh int) []rgb {
	b := make([]rgb, nw*h)
	for y := 0; y < h; y++ {
		for x := 0; x < nw; x++ {
			lo := int(math.Floor(float64(x)*float64(w)/float64(nw) + .5))
			hi := int(math.Floor(float64(x+1)*float64(w)/float64(nw) + .5))
			lo = min(w-1, lo)
			hi = min(w, max(lo+1, hi))
			var v rgb
			for xx := lo; xx < hi; xx++ {
				for ch := range 3 {
					v[ch] += a[y*w+xx][ch]
				}
			}
			for ch := range 3 {
				v[ch] = math.Floor(v[ch]/float64(hi-lo) + .5)
			}
			b[y*nw+x] = v
		}
	}
	out := make([]rgb, nw*nh)
	for y := 0; y < nh; y++ {
		lo := min(h-1, int(math.Floor(float64(y)*float64(h)/float64(nh)+.5)))
		hi := min(h, max(lo+1, int(math.Floor(float64(y+1)*float64(h)/float64(nh)+.5))))
		for x := 0; x < nw; x++ {
			var v rgb
			for yy := lo; yy < hi; yy++ {
				for ch := range 3 {
					v[ch] += b[yy*nw+x][ch]
				}
			}
			for ch := range 3 {
				v[ch] = math.Floor(v[ch]/float64(hi-lo) + .5)
			}
			out[y*nw+x] = v
		}
	}
	return out
}
func sideMetadata(p *Project) {
	w, h := p.GridWidth, p.GridHeight
	for y := 0; y < h; y++ {
		for x := 0; x < w; {
			end := x + 1
			for end < w && p.Pixels[y*w+end].RGB == p.Pixels[y*w+x].RGB {
				end++
			}
			for xx := x; xx < end; xx++ {
				v := &p.Pixels[y*w+xx]
				v.SidePixelWidthPlates = 1
				v.SidePixelHeightPlates = 1
				v.SidePartWidthPlates = end - x
			}
			x = end
		}
	}
	for x := 0; x < w; x++ {
		for y := 0; y < h; {
			end := y + 1
			for end < h && p.Pixels[end*w+x].RGB == p.Pixels[y*w+x].RGB {
				end++
			}
			for y < end {
				size := 1
				kind := "plate"
				if end-y >= 3 {
					size = 3
					kind = "brick"
				}
				for dy := 0; dy < size; dy++ {
					v := &p.Pixels[(y+dy)*w+x]
					v.SidePartType = kind
					v.SidePartHeightPlates = size
					v.SidePartRole = "single"
					if size == 3 {
						v.SidePartRole = "continue"
						if dy == 0 {
							v.SidePartRole = "start"
						}
					}
				}
				y += size
			}
		}
	}
}

// normalizePixels 验证编辑矩阵完整性并同步预览与调色板，禁止重复坐标、缺格或非法颜色落库。
func normalizePixels(p *Project) ([]byte, error) {
	if p.GridWidth < 1 || p.GridHeight < 1 || len(p.Pixels) != p.GridWidth*p.GridHeight {
		return nil, invalid("pixels")
	}
	ordered := make([]Pixel, len(p.Pixels))
	seen := make([]bool, len(p.Pixels))
	for _, v := range p.Pixels {
		if v.X < 0 || v.X >= p.GridWidth || v.Y < 0 || v.Y >= p.GridHeight {
			return nil, invalid("pixels")
		}
		i := v.Y*p.GridWidth + v.X
		if seen[i] {
			return nil, invalid("pixels")
		}
		if _, e := parseHex(v.RGB); e != nil {
			return nil, invalid("rgb")
		}
		v.RGB = strings.ToUpper(v.RGB)
		seen[i] = true
		ordered[i] = v
	}
	p.Pixels = ordered
	p.Palette = []PaletteColor{}
	indexes := map[string]int{}
	img := image.NewNRGBA(image.Rect(0, 0, p.GridWidth, p.GridHeight))
	for i := range p.Pixels {
		v := &p.Pixels[i]
		idx, ok := indexes[v.RGB]
		if !ok {
			idx = len(p.Palette)
			indexes[v.RGB] = idx
			p.Palette = append(p.Palette, PaletteColor{ColorIndex: idx, RGB: v.RGB})
		}
		v.ColorIndex = idx
		p.Palette[idx].Count++
		c, _ := parseHex(v.RGB)
		img.SetNRGBA(v.X, v.Y, color.NRGBA{uint8(c[0]), uint8(c[1]), uint8(c[2]), 255})
	}
	var buf bytes.Buffer
	err := png.Encode(&buf, img)
	return buf.Bytes(), err
}

// fixed6 保留历史 Pillow 的 6-bit YCbCr 量化及负数向零取整规则，防止预处理改变 K-means 众数。
// 依据：https://github.com/python-pillow/Pillow/blob/main/src/libImaging/ConvertYCbCr.c
func fixed6(coefficient, value float64) int { return int(.5 + coefficient*64*value) }
