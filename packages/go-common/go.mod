module github.com/penguintechinc/penguin-libs/packages/go-common

go 1.24.2

require github.com/penguintechinc/penguin-libs/packages/go-logging v0.0.0

require (
	go.uber.org/multierr v1.11.0 // indirect
	go.uber.org/zap v1.27.0 // indirect
)

replace github.com/penguintechinc/penguin-libs/packages/go-logging => ../go-logging
