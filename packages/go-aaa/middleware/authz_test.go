package middleware

import (
	"context"
	"testing"
	"time"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

func ctxWithClaims(sub string, scopes, roles []string, tenant string) context.Context {
	now := time.Now()
	claims := &authn.Claims{
		Sub:    sub,
		Iss:    "https://issuer.example.com",
		Aud:    []string{"app"},
		Iat:    now,
		Exp:    now.Add(time.Hour),
		Scope:  scopes,
		Roles:  roles,
		Tenant: tenant,
	}
	return authz.ContextWithClaims(context.Background(), claims)
}

func TestAuthzInterceptor_SufficientDirectScopes(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	procedures := ProcedureScopes{"/svc.Foo/Bar": {"report:read"}}
	interceptor := NewAuthzInterceptor(enforcer, procedures)

	ctx := ctxWithClaims("u", []string{"report:read"}, nil, "")
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(ctx, req)
	if err != nil {
		t.Fatalf("expected no error for sufficient scopes, got %v", err)
	}
}

func TestAuthzInterceptor_InsufficientScopes(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	procedures := ProcedureScopes{"": {"report:write"}}
	interceptor := NewAuthzInterceptor(enforcer, procedures)

	ctx := ctxWithClaims("u", []string{"report:read"}, nil, "")
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(ctx, req)
	if err == nil {
		t.Fatal("expected error for insufficient scopes, got nil")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v", connect.CodeOf(err))
	}
}

func TestAuthzInterceptor_ScopesFromRole(t *testing.T) {
	enforcer := authz.NewRBACEnforcer(authz.Role{Name: "editor", Scopes: []string{"doc:write", "doc:read"}})
	procedures := ProcedureScopes{"": {"doc:write"}}
	interceptor := NewAuthzInterceptor(enforcer, procedures)

	ctx := ctxWithClaims("u", nil, []string{"editor"}, "")
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(ctx, req)
	if err != nil {
		t.Fatalf("expected no error when scopes come from role, got %v", err)
	}
}

func TestAuthzInterceptor_NoProcedureRequirements_Allows(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	procedures := ProcedureScopes{} // procedure not listed
	interceptor := NewAuthzInterceptor(enforcer, procedures)

	ctx := ctxWithClaims("u", nil, nil, "")
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(ctx, req)
	if err != nil {
		t.Fatalf("expected no error when procedure has no scope requirements, got %v", err)
	}
}

func TestAuthzInterceptor_NoClaims_ReturnsPermissionDenied(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	procedures := ProcedureScopes{"": {"report:read"}}
	interceptor := NewAuthzInterceptor(enforcer, procedures)

	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(context.Background(), req)
	if err == nil {
		t.Fatal("expected error when no claims in context, got nil")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v", connect.CodeOf(err))
	}
}

func TestAuthzInterceptor_PublicProcedure_Bypasses(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	procedures := ProcedureScopes{"": {"admin:all"}}
	interceptor := NewAuthzInterceptor(enforcer, procedures, WithPublicProcedures(""))

	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(context.Background(), req)
	if err != nil {
		t.Fatalf("expected no error for public procedure, got %v", err)
	}
}

func TestResolveScopes_DeduplicatesScopes(t *testing.T) {
	enforcer := authz.NewRBACEnforcer(authz.Role{Name: "viewer", Scopes: []string{"report:read"}})

	scopes := resolveScopes(enforcer, []string{"report:read"}, []string{"viewer"})
	count := 0
	for _, s := range scopes {
		if s == "report:read" {
			count++
		}
	}
	if count != 1 {
		t.Errorf("expected report:read to appear exactly once, appeared %d times", count)
	}
}

func TestTenantInterceptor_PresentTenant(t *testing.T) {
	interceptor := NewTenantInterceptor()
	ctx := ctxWithClaims("u", nil, nil, "tenant-xyz")
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(ctx, req)
	if err != nil {
		t.Fatalf("expected no error for present tenant, got %v", err)
	}
}

func TestTenantInterceptor_MissingTenant(t *testing.T) {
	interceptor := NewTenantInterceptor()
	ctx := ctxWithClaims("u", nil, nil, "")
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(ctx, req)
	if err == nil {
		t.Fatal("expected error for missing tenant, got nil")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v", connect.CodeOf(err))
	}
}

func TestTenantInterceptor_PublicProcedure_Bypasses(t *testing.T) {
	interceptor := NewTenantInterceptor(WithPublicProcedures(""))
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor(noopNext)(context.Background(), req)
	if err != nil {
		t.Fatalf("expected no error for public procedure, got %v", err)
	}
}
