module github.com/penguintechinc/penguin-libs/packages/go-xdp

go 1.24.2

require (
	github.com/cilium/ebpf v0.17.3
	github.com/penguintechinc/penguin-libs/packages/go-logging v0.0.0
	go.uber.org/zap v1.27.0
	golang.org/x/sys v0.30.0
)

require go.uber.org/multierr v1.11.0 // indirect

replace github.com/penguintechinc/penguin-libs/packages/go-logging => ../go-logging
