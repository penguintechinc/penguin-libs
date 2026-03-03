// Package middleware provides ConnectRPC interceptors for authentication,
// authorization, tenant validation, and audit logging in Penguin Tech applications.
package middleware

import (
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
)

// interceptorConfig holds the resolved configuration for an interceptor.
type interceptorConfig struct {
	publicProcedures map[string]bool
	skipAuditTypes   map[audit.EventType]bool
}

// InterceptorOption is a functional option that modifies interceptor behavior.
type InterceptorOption func(*interceptorConfig)

// WithPublicProcedures marks the listed procedure paths as exempt from authentication
// and authorization checks.
func WithPublicProcedures(procedures ...string) InterceptorOption {
	return func(cfg *interceptorConfig) {
		if cfg.publicProcedures == nil {
			cfg.publicProcedures = make(map[string]bool, len(procedures))
		}
		for _, p := range procedures {
			cfg.publicProcedures[p] = true
		}
	}
}

// WithSkipAuditTypes instructs the audit interceptor to suppress events of the
// listed types. Useful for suppressing noise from high-frequency health-check RPCs.
func WithSkipAuditTypes(types ...audit.EventType) InterceptorOption {
	return func(cfg *interceptorConfig) {
		if cfg.skipAuditTypes == nil {
			cfg.skipAuditTypes = make(map[audit.EventType]bool, len(types))
		}
		for _, t := range types {
			cfg.skipAuditTypes[t] = true
		}
	}
}

// applyOptions builds an interceptorConfig from the provided options.
func applyOptions(opts []InterceptorOption) interceptorConfig {
	cfg := interceptorConfig{}
	for _, o := range opts {
		o(&cfg)
	}
	return cfg
}
