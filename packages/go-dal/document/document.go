// Package document provides document store implementations (MongoDB).
package document

import (
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Ensure interface compliance at compile time.
var (
	_ dal.DocumentStore = (*MongoDB)(nil)
)
