// Package authz provides role-based access control for Penguin Tech applications.
//
// It supports scope-based authorization with a role registry, allowing callers
// to check whether a subject has the required scopes for a given operation.
package authz

import (
	"fmt"
	"strings"
	"sync"
)

// Role represents a named role with associated OAuth 2.0 scopes.
type Role struct {
	// Name is the unique identifier for the role.
	Name string
	// Scopes lists the OAuth 2.0 scopes granted to this role.
	Scopes []string
}

// RBACEnforcer holds a registry of roles and provides scope-checking operations.
type RBACEnforcer struct {
	mu    sync.RWMutex
	roles map[string]Role
}

// NewRBACEnforcer creates an RBACEnforcer pre-populated with the given roles.
func NewRBACEnforcer(roles ...Role) *RBACEnforcer {
	e := &RBACEnforcer{
		roles: make(map[string]Role, len(roles)),
	}
	for _, r := range roles {
		e.roles[r.Name] = r
	}
	return e
}

// RegisterRole adds or replaces a role in the enforcer's registry.
func (e *RBACEnforcer) RegisterRole(role Role) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.roles[role.Name] = role
}

// ScopesForRole returns the scopes assigned to the named role and whether the role exists.
func (e *RBACEnforcer) ScopesForRole(roleName string) ([]string, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	r, ok := e.roles[roleName]
	if !ok {
		return nil, false
	}
	out := make([]string, len(r.Scopes))
	copy(out, r.Scopes)
	return out, true
}

// HasScope reports whether the given scopes list contains the target scope.
func HasScope(scopes []string, target string) bool {
	for _, s := range scopes {
		if s == target {
			return true
		}
	}
	return false
}

// HasAnyScope reports whether scopes contains at least one of the required scopes.
func HasAnyScope(scopes []string, required ...string) bool {
	for _, req := range required {
		if HasScope(scopes, req) {
			return true
		}
	}
	return false
}

// HasAllScopes reports whether scopes contains every one of the required scopes.
func HasAllScopes(scopes []string, required ...string) bool {
	for _, req := range required {
		if !HasScope(scopes, req) {
			return false
		}
	}
	return true
}

// ValidateScopes checks that every entry in scopes follows the "resource:action" format.
// It returns an error describing the first violation found.
func ValidateScopes(scopes []string) error {
	for _, s := range scopes {
		parts := strings.SplitN(s, ":", 2)
		if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
			return fmt.Errorf("authz: scope %q is not in resource:action format", s)
		}
	}
	return nil
}
