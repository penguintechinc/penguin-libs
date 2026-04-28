module github.com/penguintechinc/penguin-libs/packages/go-aaa

go 1.24.2

replace github.com/penguintechinc/penguin-libs/packages/go-common => ../go-common

require (
	connectrpc.com/connect v1.19.1
	github.com/coreos/go-oidc/v3 v3.17.0
	github.com/google/uuid v1.6.0
	github.com/lestrrat-go/jwx/v2 v2.1.6
	github.com/penguintechinc/penguin-libs/packages/go-common v0.0.0-00010101000000-000000000000
	github.com/spiffe/go-spiffe/v2 v2.6.0
	go.uber.org/zap v1.27.0
	golang.org/x/oauth2 v0.35.0
)

require (
	github.com/Microsoft/go-winio v0.6.2 // indirect
	github.com/decred/dcrd/dcrec/secp256k1/v4 v4.4.0 // indirect
	github.com/go-jose/go-jose/v4 v4.1.4 // indirect
	github.com/goccy/go-json v0.10.3 // indirect
	github.com/lestrrat-go/blackmagic v1.0.3 // indirect
	github.com/lestrrat-go/httpcc v1.0.1 // indirect
	github.com/lestrrat-go/httprc v1.0.6 // indirect
	github.com/lestrrat-go/iter v1.0.2 // indirect
	github.com/lestrrat-go/option v1.0.1 // indirect
	github.com/segmentio/asm v1.2.0 // indirect
	go.uber.org/multierr v1.11.0 // indirect
	golang.org/x/crypto v0.46.0 // indirect
	golang.org/x/net v0.48.0 // indirect
	golang.org/x/sys v0.39.0 // indirect
	golang.org/x/text v0.32.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20251202230838-ff82c1b0f217 // indirect
	google.golang.org/grpc v1.79.3 // indirect
	google.golang.org/protobuf v1.36.10 // indirect
)
