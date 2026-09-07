package pixel2d

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/jackc/pgx/v5/pgxpool"
	"regexp"
	"strings"
)

var partNumberPattern = regexp.MustCompile(`^[a-z0-9_-]+\.dat$`)

// ValidateMetadata 拒绝无法覆盖任意像素或非矩形 Plate 的目录，不用虚构零件填补缺口。
func ValidateMetadata(m Metadata) error {
	if len(m.Colors) == 0 || len(m.Colors) > 2048 || len(m.Parts) == 0 || len(m.Parts) > 256 {
		return domain("lego_design.generation_failed")
	}
	colors := map[int]bool{}
	for _, c := range m.Colors {
		if _, err := parseHex(c.RGB); err != nil || c.IsTrans || colors[c.ID] {
			return invalid("colors")
		}
		colors[c.ID] = true
	}
	one := false
	parts := map[string]bool{}
	for _, p := range m.Parts {
		if !partNumberPattern.MatchString(p.LDrawPartNum) || parts[p.LDrawPartNum] || p.Width < 1 || p.Height < 1 || p.Width*p.Height > 64 || p.Area != p.Width*p.Height || p.LogicalHeightPlate != 1 || p.PartRole != "plate" {
			return invalid("parts")
		}
		parts[p.LDrawPartNum] = true
		one = one || (p.Width == 1 && p.Height == 1)
	}
	if !one {
		return invalid("parts.1x1")
	}
	return nil
}

// ImportCatalog 是显式数据迁移入口；输入来自已审核真实零件/颜色目录，启动进程不隐式导入。
func ImportCatalog(ctx context.Context, pool *pgxpool.Pool, data []byte) (string, error) {
	var m Metadata
	if err := json.Unmarshal(data, &m); err != nil {
		return "", err
	}
	for i := range m.Colors {
		m.Colors[i].RGB = "#" + strings.ToUpper(strings.TrimPrefix(m.Colors[i].RGB, "#"))
	}
	m.TerrainParts = []Part{}
	m.ContentLocale = "en-US"
	if err := ValidateMetadata(m); err != nil {
		return "", err
	}
	data = mustJSON(m)
	hash := fmt.Sprintf("%x", sha256.Sum256(data))
	err := db.New(pool).PutPixelCatalog(ctx, db.PutPixelCatalogParams{Hash: hash, Document: data})
	return hash, err
}
