// Package cache provides cache backend implementations (Redis, Valkey).
//
// Deprecated: Go libraries are being phased out; use rust-dal (packages/rust-dal) instead.
package cache

import (
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Ensure interface compliance at compile time.
var (
	_ dal.CacheStore = (*RedisCache)(nil)
	_ dal.CacheStore = (*ValkeyCache)(nil)
)
