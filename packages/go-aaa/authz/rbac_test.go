package authz

import (
	"testing"
)

func TestNewRBACEnforcer_EmptyRegistry(t *testing.T) {
	e := NewRBACEnforcer()
	_, ok := e.ScopesForRole("admin")
	if ok {
		t.Error("expected ScopesForRole to return false for unknown role")
	}
}

func TestRegisterRole_OverwritesExisting(t *testing.T) {
	e := NewRBACEnforcer(Role{Name: "viewer", Scopes: []string{"report:read"}})
	e.RegisterRole(Role{Name: "viewer", Scopes: []string{"report:read", "report:export"}})

	scopes, ok := e.ScopesForRole("viewer")
	if !ok {
		t.Fatal("expected viewer role to exist")
	}
	if len(scopes) != 2 {
		t.Errorf("expected 2 scopes after overwrite, got %d", len(scopes))
	}
}

func TestScopesForRole_ReturnsCopy(t *testing.T) {
	e := NewRBACEnforcer(Role{Name: "editor", Scopes: []string{"doc:write"}})

	scopes, _ := e.ScopesForRole("editor")
	scopes[0] = "tampered"

	scopes2, _ := e.ScopesForRole("editor")
	if scopes2[0] != "doc:write" {
		t.Error("ScopesForRole should return an independent copy of the scopes slice")
	}
}

func TestHasScope(t *testing.T) {
	scopes := []string{"report:read", "user:write"}

	if !HasScope(scopes, "report:read") {
		t.Error("expected HasScope to return true for present scope")
	}
	if HasScope(scopes, "report:delete") {
		t.Error("expected HasScope to return false for absent scope")
	}
	if HasScope(nil, "report:read") {
		t.Error("expected HasScope to return false for nil scopes")
	}
}

func TestHasAnyScope(t *testing.T) {
	scopes := []string{"report:read", "user:write"}

	if !HasAnyScope(scopes, "report:delete", "report:read") {
		t.Error("expected HasAnyScope to return true when at least one scope matches")
	}
	if HasAnyScope(scopes, "report:delete", "admin:all") {
		t.Error("expected HasAnyScope to return false when no scopes match")
	}
	if HasAnyScope(scopes) {
		t.Error("expected HasAnyScope to return false with no required scopes")
	}
}

func TestHasAllScopes(t *testing.T) {
	scopes := []string{"report:read", "user:write", "admin:view"}

	if !HasAllScopes(scopes, "report:read", "user:write") {
		t.Error("expected HasAllScopes to return true when all scopes are present")
	}
	if HasAllScopes(scopes, "report:read", "report:delete") {
		t.Error("expected HasAllScopes to return false when any scope is missing")
	}
	if !HasAllScopes(scopes) {
		t.Error("expected HasAllScopes to return true for empty required list")
	}
}

func TestValidateScopes_ValidFormat(t *testing.T) {
	scopes := []string{"report:read", "user:write", "admin:all"}
	if err := ValidateScopes(scopes); err != nil {
		t.Errorf("expected no error for valid scopes, got %v", err)
	}
}

func TestValidateScopes_EmptyList(t *testing.T) {
	if err := ValidateScopes(nil); err != nil {
		t.Errorf("expected no error for nil scopes, got %v", err)
	}
	if err := ValidateScopes([]string{}); err != nil {
		t.Errorf("expected no error for empty scopes, got %v", err)
	}
}

func TestValidateScopes_InvalidFormat(t *testing.T) {
	cases := []struct {
		name   string
		scopes []string
	}{
		{"no colon", []string{"reportread"}},
		{"empty resource", []string{":read"}},
		{"empty action", []string{"report:"}},
		{"multiple colons are ok but empty parts are not", []string{":"}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := ValidateScopes(tc.scopes); err == nil {
				t.Errorf("expected error for scope %v, got nil", tc.scopes)
			}
		})
	}
}

func TestValidateScopes_MultipleColonsAllowed(t *testing.T) {
	// "resource:sub:action" is acceptable — only the first colon splits.
	if err := ValidateScopes([]string{"resource:sub:action"}); err != nil {
		t.Errorf("expected no error for multi-part scope, got %v", err)
	}
}
