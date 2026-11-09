// Package document provides document store implementations (MongoDB).
//
// # Filter and update screening
//
// Every filter and update passed to MongoDB operations is screened before it
// reaches the driver. $where, $function and $accumulator (server-side
// JavaScript) are rejected at any depth, in filters and in updates, including
// pipeline-form updates. Only the logical operators $and, $or and $nor are
// allowed at the top level of a filter: top-level $text, $expr and $comment
// filters are rejected with ErrUnsafeFilter and now require wrapping the
// filter in Trusted. Operators in value position ({"age": {"$gt": 3}}) remain
// allowed. Use Trusted only for filters or updates the application authored
// itself, never for anything built from request input.
//
// Deprecated: Go libraries are being phased out; use rust-dal (packages/rust-dal) instead.
package document

import (
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Ensure interface compliance at compile time.
var (
	_ dal.DocumentStore = (*MongoDB)(nil)
)
