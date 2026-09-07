// Package pixel2d 实现图片像素化及平面 LEGO 拼接，计算仅由持久 Worker 调用。
package pixel2d

import (
	"embed"
	"encoding/json"
	"fmt"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"net/http"
	"time"
)

// AlgorithmVersion 算法语义版本随任务冻结，后续算法变更须增加版本。
const AlgorithmVersion = "pixel-2d-go-v1"

// ExportVersion 导出目录复用已发布的服务端资源版本。
const ExportVersion = "brickbuilder-export-2026.07.18.1"

// GenerateType 源图量化的持久任务类型。
const GenerateType = "pixel_2d.generate"

// EditType 像素编辑校验与预览再生的持久任务类型。
const EditType = "pixel_2d.edit"

// DesignType 平面拼接及全部导出物化的持久任务类型。
const DesignType = "pixel_2d.design"

//go:embed resources/*.json
var resources embed.FS

// Settings 冻结客户端裁剪与预处理输入；机器算法 ID 与原有前端保持一致。
type Settings struct {
	Algorithm  string `json:"algorithm"`
	GridWidth  int    `json:"gridWidth"`
	GridHeight int    `json:"gridHeight"`
	ColorCount int    `json:"colorCount"`
	Crop       struct {
		X      int `json:"x"`
		Y      int `json:"y"`
		Width  int `json:"width"`
		Height int `json:"height"`
	} `json:"crop"`
	Preprocessing struct {
		Brightness           float64 `json:"brightness"`
		Contrast             float64 `json:"contrast"`
		Saturation           float64 `json:"saturation"`
		Sharpness            float64 `json:"sharpness"`
		LocalContrast        float64 `json:"localContrast"`
		PreserveLightDetails bool    `json:"preserveLightDetails"`
	} `json:"preprocessing"`
}

// Pixel 保留用户编辑锁定及侧面拼搭元数据，不将用户颜色当作翻译资源。
type Pixel struct {
	X                     int     `json:"x"`
	Y                     int     `json:"y"`
	ColorIndex            int     `json:"colorIndex"`
	RGB                   string  `json:"rgb"`
	SourceColor           string  `json:"sourceColor,omitempty"`
	QuantizedColor        string  `json:"quantizedColor,omitempty"`
	FeatureScore          float64 `json:"featureScore"`
	EdgeStrength          float64 `json:"edgeStrength"`
	LocalContrast         float64 `json:"localContrast"`
	Modified              bool    `json:"modified"`
	Locked                bool    `json:"locked"`
	SidePixelWidthPlates  int     `json:"sidePixelWidthPlates,omitempty"`
	SidePixelHeightPlates int     `json:"sidePixelHeightPlates,omitempty"`
	SidePartWidthPlates   int     `json:"sidePartWidthPlates,omitempty"`
	SidePartHeightPlates  int     `json:"sidePartHeightPlates,omitempty"`
	SidePartType          string  `json:"sidePartType,omitempty"`
	SidePartRole          string  `json:"sidePartRole,omitempty"`
}

// PaletteColor 是颜色计数投影，Worker 从像素重新计算，不信任客户端统计。
type PaletteColor struct {
	ColorIndex int    `json:"colorIndex"`
	RGB        string `json:"rgb"`
	Count      int    `json:"count"`
}

// Project 是不可变像素修订的读取契约；revisionId 用于乐观并发控制。
type Project struct {
	ModelID       string         `json:"modelId"`
	RevisionID    string         `json:"revisionId"`
	Name          string         `json:"name"`
	ContentLocale string         `json:"contentLocale"`
	Source        string         `json:"source"`
	CreatedAt     time.Time      `json:"createdAt"`
	Schema        string         `json:"schema"`
	GridWidth     int            `json:"gridWidth"`
	GridHeight    int            `json:"gridHeight"`
	ColorCount    int            `json:"colorCount"`
	Palette       []PaletteColor `json:"palette"`
	Pixels        []Pixel        `json:"pixels,omitempty"`
	PreviewImage  string         `json:"previewImage"`
}

// Color 和 Part 来自显式导入的冻结目录，名称保留源内容。
type Color struct {
	ID      int    `json:"id"`
	Name    string `json:"name"`
	RGB     string `json:"rgb"`
	IsTrans bool   `json:"isTrans"`
}

// Part 保存真实 Plate 编号及整数网格尺寸，不用虚构零件填补区域。
type Part struct {
	LDrawPartNum       string  `json:"ldrawPartNum"`
	RebrickablePartNum *string `json:"rebrickablePartNum"`
	LegoDesignID       *string `json:"legoDesignId"`
	Name               string  `json:"name"`
	PartRole           string  `json:"partRole"`
	Width              int     `json:"width"`
	Height             int     `json:"height"`
	LogicalHeightPlate int     `json:"logicalHeightPlate"`
	Area               int     `json:"area"`
}

// Metadata 以内容哈希冻结，发布目录变更不会改变已排队的拼接结果。
type Metadata struct {
	Colors        []Color `json:"colors"`
	Parts         []Part  `json:"parts"`
	TerrainParts  []Part  `json:"terrainParts"`
	ContentLocale string  `json:"contentLocale"`
}

// Mapping 记录源 RGB 到官方颜色的稳定映射。
type Mapping struct {
	SourceRGB      string `json:"sourceRgb"`
	ColorID        int    `json:"colorId"`
	ColorName      string `json:"colorName"`
	ColorRGB       string `json:"colorRgb"`
	LDrawColorCode string `json:"ldrawColorCode"`
}

// Placement 同时保存网格位置与旋转，导出复用同一投影，避免 BOM 与预览分叉。
type Placement struct {
	PartID             string  `json:"partId"`
	RebrickablePartNum *string `json:"rebrickablePartNum"`
	LegoDesignID       *string `json:"legoDesignId"`
	ColorID            int     `json:"colorId"`
	ColorName          string  `json:"colorName"`
	ColorRGB           string  `json:"colorRgb"`
	LDrawColorCode     string  `json:"ldrawColorCode"`
	X                  int     `json:"x"`
	Y                  int     `json:"y"`
	Width              int     `json:"width"`
	Height             int     `json:"height"`
	LogicalHeightPlate int     `json:"logicalHeightPlate"`
	Rotation           int     `json:"rotation"`
}

// BOMItem 按零件、颜色和尺寸归并的材料数量。
type BOMItem struct {
	Key                string  `json:"key"`
	PartID             string  `json:"partId"`
	RebrickablePartNum *string `json:"rebrickablePartNum"`
	LegoDesignID       *string `json:"legoDesignId"`
	ColorID            int     `json:"colorId"`
	ColorName          string  `json:"colorName"`
	ColorRGB           string  `json:"colorRgb"`
	LDrawColorCode     string  `json:"ldrawColorCode"`
	Width              int     `json:"width"`
	Height             int     `json:"height"`
	Quantity           int     `json:"quantity"`
}

// Dimensions 按网格与 Plate 高度计算模型的机器尺寸。
type Dimensions struct {
	LengthStud  int     `json:"lengthStud"`
	WidthStud   int     `json:"widthStud"`
	HeightPlate int     `json:"heightPlate"`
	LengthCm    float64 `json:"lengthCm"`
	WidthCm     float64 `json:"widthCm"`
	HeightCm    float64 `json:"heightCm"`
}
type Design struct {
	Width           int         `json:"width"`
	Height          int         `json:"height"`
	Placements      []Placement `json:"placements"`
	BOM             []BOMItem   `json:"bom"`
	ColorMappings   []Mapping   `json:"colorMappings"`
	ModelDimensions Dimensions  `json:"modelDimensions"`
}

// ExportContext 在任务创建时冻结，不读取下载时浏览器的语言。
// ExportContext 冻结创建任务时的语言、时区和词典版本。
type ExportContext struct {
	Locale         string `json:"locale"`
	Timezone       string `json:"timezone"`
	CatalogVersion string `json:"catalogVersion"`
}

func domain(code string) error { return apierror.New(code, http.StatusBadRequest, nil) }
func invalid(field string) error {
	return apierror.New("request.validation_failed", 422, map[string]any{"field": field})
}
func mustJSON(v any) []byte {
	data, err := json.Marshal(v)
	if err != nil {
		panic(fmt.Sprintf("invalid internal JSON: %v", err))
	}
	return data
}
