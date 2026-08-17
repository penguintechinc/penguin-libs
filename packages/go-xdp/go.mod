module github.com/penguintechinc/penguin-libs/packages/go-xdp

go 1.25.0

require (
	github.com/cilium/ebpf v0.22.0
	github.com/penguintechinc/penguin-libs/packages/go-logging v0.0.0
	go.uber.org/zap v1.27.0
	golang.org/x/sys v0.43.0
)

require go.uber.org/multierr v1.11.0 // indirect

replace github.com/penguintechinc/penguin-libs/packages/go-logging => ../go-logging
