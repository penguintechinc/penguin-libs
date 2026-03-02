package authz

import (
	"context"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

func makeClaims(sub, tenant string) *authn.Claims {
	now := time.Now()
	return &authn.Claims{
		Sub:    sub,
		Iss:    "https://issuer.example.com",
		Aud:    []string{"app"},
		Iat:    now,
		Exp:    now.Add(time.Hour),
		Tenant: tenant,
	}
}

func TestContextWithClaims_RoundTrip(t *testing.T) {
	claims := makeClaims("user-123", "acme-corp")
	ctx := ContextWithClaims(context.Background(), claims)

	got := ClaimsFromContext(ctx)
	if got == nil {
		t.Fatal("expected claims in context, got nil")
	}
	if got.Sub != "user-123" {
		t.Errorf("expected sub user-123, got %q", got.Sub)
	}
}

func TestClaimsFromContext_AbsentReturnsNil(t *testing.T) {
	got := ClaimsFromContext(context.Background())
	if got != nil {
		t.Errorf("expected nil claims from empty context, got %v", got)
	}
}

func TestTenantFromContext_ReturnsTenant(t *testing.T) {
	ctx := ContextWithClaims(context.Background(), makeClaims("u", "my-tenant"))
	if tenant := TenantFromContext(ctx); tenant != "my-tenant" {
		t.Errorf("expected my-tenant, got %q", tenant)
	}
}

func TestTenantFromContext_AbsentClaimsReturnsEmpty(t *testing.T) {
	if tenant := TenantFromContext(context.Background()); tenant != "" {
		t.Errorf("expected empty string, got %q", tenant)
	}
}

func TestTenantFromContext_EmptyTenantField(t *testing.T) {
	ctx := ContextWithClaims(context.Background(), makeClaims("u", ""))
	if tenant := TenantFromContext(ctx); tenant != "" {
		t.Errorf("expected empty string for unset tenant, got %q", tenant)
	}
}

func TestClaimsKey_Isolation(t *testing.T) {
	// Verify that using a different key type does not collide with claimsKey{}.
	type otherKey struct{}
	claims := makeClaims("u", "t")
	ctx := context.WithValue(context.Background(), otherKey{}, claims)

	got := ClaimsFromContext(ctx)
	if got != nil {
		t.Error("claims stored under different key should not be visible via ClaimsFromContext")
	}
}
