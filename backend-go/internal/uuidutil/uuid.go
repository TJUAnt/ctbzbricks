package uuidutil

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5/pgtype"
)

func New() (pgtype.UUID, error) {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return pgtype.UUID{}, fmt.Errorf("generate UUID: %w", err)
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return pgtype.UUID{Bytes: bytes, Valid: true}, nil
}

func Parse(value string) (pgtype.UUID, error) {
	raw := strings.ReplaceAll(strings.TrimSpace(value), "-", "")
	if len(raw) != 32 {
		return pgtype.UUID{}, errors.New("invalid UUID")
	}
	decoded, err := hex.DecodeString(raw)
	if err != nil {
		return pgtype.UUID{}, errors.New("invalid UUID")
	}
	var bytes [16]byte
	copy(bytes[:], decoded)
	return pgtype.UUID{Bytes: bytes, Valid: true}, nil
}

func String(value pgtype.UUID) string {
	if !value.Valid {
		return ""
	}
	b := value.Bytes
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

func Equal(left, right pgtype.UUID) bool {
	return left.Valid == right.Valid && (!left.Valid || left.Bytes == right.Bytes)
}

func NullableString(value pgtype.UUID) *string {
	if !value.Valid {
		return nil
	}
	formatted := String(value)
	return &formatted
}
