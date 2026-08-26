package uuidutil

import (
	"crypto/sha1"

	"github.com/jackc/pgx/v5/pgtype"
)

// NameSHA1 returns an RFC 4122 version 5 UUID for namespace/name.
func NameSHA1(namespace pgtype.UUID, name string) pgtype.UUID {
	digest := sha1.New()
	if namespace.Valid {
		_, _ = digest.Write(namespace.Bytes[:])
	}
	_, _ = digest.Write([]byte(name))
	sum := digest.Sum(nil)
	var bytes [16]byte
	copy(bytes[:], sum[:16])
	bytes[6] = (bytes[6] & 0x0f) | 0x50
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return pgtype.UUID{Bytes: bytes, Valid: true}
}
