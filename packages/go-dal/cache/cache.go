// Package cache provides cache backend implementations (Redis, Valkey).
package cache

import (
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Ensure interface compliance at compile time.
var (
	_ dal.CacheStore = (*RedisCache)(nil)
	_ dal.CacheStore = (*ValkeyCache)(nil)
)
