// Package ldrawmaterial 提供渲染链路共用的确定性 LDraw 颜色与材质分类。
// 数值来自仓库当前支持的 Studio LDConfig 语义，但运行时不读取可变安装目录。
package ldrawmaterial

import (
	"math"
	"strconv"
	"strings"
)

const (
	// ProfileVersion 参与 Preview/Feed Artifact 审计；任何材质参数或颜色快照变化都必须提升版本。
	ProfileVersion = "ldraw-studio-pbr-v1"

	// 以下常量是跨 GLB、Three.js 与 Cycles 共用的稳定机器分类，不作为用户展示文案。
	Plastic    = "plastic"
	Glass      = "glass"
	Rubber     = "rubber"
	Chrome     = "chrome"
	Pearl      = "pearl"
	Metal      = "metal"
	MatteMetal = "matte_metal"
	Luminous   = "luminous"
	Glitter    = "glitter"
	Speckle    = "speckle"
)

// Definition 是 Component GLB、Three.js 和 Feed Cycles 共用的版本化材质契约。
// 颜色与发光值使用线性空间；Alpha 保留 LDConfig 的名义透明度，Transmission 表达物理透射。
type Definition struct {
	Name               string
	BaseColor          [3]float64
	Alpha              float64
	Roughness          float64
	Metallic           float64
	IOR                float64
	Transmission       float64
	Specular           float64
	Clearcoat          float64
	ClearcoatRoughness float64
	EmissiveStrength   float64
	Class              string
}

type sourceDefinition struct {
	name, hex, class string
	alpha, luminance float64
}

// Lookup 按稳定 LDraw color code 返回定义；未知 code 使用中性塑料，避免把机器值当展示文案。
func Lookup(code string) Definition {
	code = normalizeCode(code)
	source, ok := catalog[code]
	if !ok {
		source = sourceDefinition{name: "Unknown", hex: "B8BDC7", class: Plastic, alpha: 1}
	}
	r, g, b := parseHex(source.hex)
	result := Definition{
		Name: source.name, BaseColor: [3]float64{srgbToLinear(r), srgbToLinear(g), srgbToLinear(b)},
		Alpha: source.alpha, Roughness: 0.26, IOR: 1.46, Specular: 0.9,
		Clearcoat: 0.18, ClearcoatRoughness: 0.14, Class: source.class,
	}
	switch source.class {
	case Glass:
		result.Roughness, result.IOR = 0.07, 1.49
		result.Transmission = transmissionForAlpha(source.alpha)
		result.Clearcoat, result.ClearcoatRoughness = 0.08, 0.08
	case Rubber:
		result.Roughness, result.IOR, result.Specular = 0.78, 1.52, 0.35
		result.Clearcoat, result.ClearcoatRoughness = 0.02, 0.4
		result.Transmission = transmissionForAlpha(source.alpha)
	case Chrome:
		result.Roughness, result.Metallic, result.Specular = 0.08, 1, 1
		result.Clearcoat, result.ClearcoatRoughness = 0.06, 0.06
	case Pearl:
		result.Roughness, result.Metallic, result.Specular = 0.24, 0.52, 0.9
	case Metal:
		result.Roughness, result.Metallic = 0.20, 0.82
	case MatteMetal:
		result.Roughness, result.Metallic = 0.34, 0.66
	case Luminous:
		result.Roughness, result.Specular = 0.3, 0.75
		result.Clearcoat, result.EmissiveStrength = 0.1, math.Max(0.6, source.luminance*5)
	case Glitter:
		result.Roughness, result.Metallic = 0.18, 0.28
		result.Clearcoat, result.ClearcoatRoughness = 0.25, 0.1
		result.Transmission = transmissionForAlpha(source.alpha)
	case Speckle:
		result.Roughness, result.Metallic, result.Clearcoat = 0.42, 0.18, 0.04
	}
	return result
}

// transmissionForAlpha 把 LDConfig 的覆盖率转换为薄壁透射强度；不透明材质保持零开销。
func transmissionForAlpha(alpha float64) float64 {
	if alpha >= 0.999 {
		return 0
	}
	return math.Min(0.9, 0.55+(1-alpha)*0.35)
}

// normalizeCode 恢复 Studio 印刷 Part 中用 100000+code 表示的嵌入材质；
// 例如挡风玻璃几何的 100040 与标准 Trans Black 40 共用材质定义。
func normalizeCode(code string) string {
	code = strings.TrimSpace(code)
	value, err := strconv.Atoi(code)
	if err == nil && value >= 100000 && value <= 199999 {
		return strconv.Itoa(value - 100000)
	}
	return code
}

func parseHex(value string) (float64, float64, float64) {
	parsed, _ := strconv.ParseUint(value, 16, 32)
	return float64((parsed>>16)&0xff) / 255, float64((parsed>>8)&0xff) / 255, float64(parsed&0xff) / 255
}

func srgbToLinear(value float64) float64 {
	if value <= 0.04045 {
		return value / 12.92
	}
	return math.Pow((value+0.055)/1.055, 2.4)
}
