package server

import (
	"testing"
)

func TestEnvOrDefault_Set(t *testing.T) {
	t.Setenv("TEST_VAR", "test_value")

	result := envOrDefault("TEST_VAR", "default_value")

	if result != "test_value" {
		t.Errorf("expected test_value, got %s", result)
	}
}

func TestEnvOrDefault_Unset(t *testing.T) {
	// Don't set the var
	result := envOrDefault("UNSET_TEST_VAR", "default_value")

	if result != "default_value" {
		t.Errorf("expected default_value, got %s", result)
	}
}

func TestNewTLSConfig_InvalidPaths(t *testing.T) {
	_, err := NewTLSConfig("/nonexistent/cert.pem", "/nonexistent/key.pem")

	if err == nil {
		t.Error("expected error for invalid paths, got nil")
	}
}
