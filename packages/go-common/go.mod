// Deprecated: Go libraries are being phased out; Rust replacement planned.
module github.com/penguintechinc/penguin-libs/packages/go-common

go 1.26.0

toolchain go1.26.10

require go.uber.org/zap v1.27.0

require go.uber.org/multierr v1.11.0 // indirect

replace github.com/penguintechinc/penguin-libs/packages/go-logging => ../go-logging
