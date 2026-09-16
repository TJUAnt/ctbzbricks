package componentactivity

import (
	"crypto/sha256"
	"encoding/binary"

	"github.com/jackc/pgx/v5/pgtype"
)

// LockKey 把 Component UUID 稳定映射为 PostgreSQL advisory lock key。
// Watch/Unwatch/Star 使用共享锁，Publish 与 Component 删除取得独占锁，使关系写入、发布审计和删除生命周期
// 在同一事务边界上排序；read-time Feed 的成员资格只读取当前 active Watch，不使用该锁或 sequence 判定收件人。
func LockKey(componentID pgtype.UUID) int64 {
	hash := sha256.Sum256(componentID.Bytes[:])
	return int64(binary.BigEndian.Uint64(hash[:8]))
}
