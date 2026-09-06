package componentactivity

import (
	"crypto/sha256"
	"encoding/binary"

	"github.com/jackc/pgx/v5/pgtype"
)

// LockKey 把 Component UUID 稳定映射为 PostgreSQL advisory lock key。
// Watch/Unwatch 使用共享锁，Publish 复用本函数取得独占锁，避免事件越过未提交的偏好变更。
func LockKey(componentID pgtype.UUID) int64 {
	hash := sha256.Sum256(componentID.Bytes[:])
	return int64(binary.BigEndian.Uint64(hash[:8]))
}
