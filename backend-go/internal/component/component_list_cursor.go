package component

import (
	"encoding/base64"
	"encoding/json"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

type componentListCursorPayload struct {
	UpdatedAt string `json:"updatedAt"`
	ID        string `json:"id"`
	Locale    string `json:"locale"`
	Query     string `json:"query"`
	Category  string `json:"category"`
	Status    string `json:"status"`
}

type decodedComponentListCursor struct {
	UpdatedAt   pgtype.Timestamptz
	ComponentID pgtype.UUID
	Locale      string
	Query       string
	Category    string
	Status      string
}

// decodeComponentListCursor 校验不透明目录游标，并恢复与 SQL 排序一致的时间和 UUID 边界。
func decodeComponentListCursor(raw string) (decodedComponentListCursor, error) {
	if raw == "" {
		return decodedComponentListCursor{}, nil
	}
	data, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil {
		return decodedComponentListCursor{}, err
	}
	var payload componentListCursorPayload
	if err := json.Unmarshal(data, &payload); err != nil {
		return decodedComponentListCursor{}, err
	}
	updatedAt, err := time.Parse(time.RFC3339Nano, payload.UpdatedAt)
	if err != nil {
		return decodedComponentListCursor{}, err
	}
	id, err := uuidutil.Parse(payload.ID)
	if err != nil {
		return decodedComponentListCursor{}, err
	}
	return decodedComponentListCursor{
		UpdatedAt: pgtype.Timestamptz{Time: updatedAt.UTC(), Valid: true}, ComponentID: id,
		Locale: payload.Locale, Query: payload.Query, Category: payload.Category, Status: payload.Status,
	}, nil
}

// encodeComponentListCursor 将最后一行和冻结筛选写入游标，避免调用方换筛选后从旧边界继续而漏项。
func encodeComponentListCursor(
	updatedAt time.Time,
	id pgtype.UUID,
	locale string,
	query string,
	category string,
	status string,
) (string, error) {
	payload, err := json.Marshal(componentListCursorPayload{
		UpdatedAt: updatedAt.UTC().Format(time.RFC3339Nano), ID: uuidutil.String(id),
		Locale: locale, Query: query, Category: category, Status: status,
	})
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(payload), nil
}
