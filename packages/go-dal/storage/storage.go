// Package storage provides storage backend implementations (S3, NFS).
package storage

import (
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Ensure interface compliance at compile time.
var (
	_ dal.StorageStore = (*S3Store)(nil)
	_ dal.StorageStore = (*NFSStore)(nil)
)
