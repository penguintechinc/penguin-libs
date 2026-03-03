package crypto_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/crypto"
)

func TestJWKSBytes_ValidJSON(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	data, err := crypto.JWKSBytes(ks)
	if err != nil {
		t.Fatalf("JWKSBytes: %v", err)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("JWKSBytes returned invalid JSON: %v", err)
	}
}

func TestJWKSBytes_ContainsKeys(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmES256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	data, err := crypto.JWKSBytes(ks)
	if err != nil {
		t.Fatalf("JWKSBytes: %v", err)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}

	keys, ok := parsed["keys"]
	if !ok {
		t.Fatal("expected 'keys' field in JWKS document")
	}

	keyList, ok := keys.([]interface{})
	if !ok {
		t.Fatalf("expected 'keys' to be an array, got %T", keys)
	}
	if len(keyList) == 0 {
		t.Fatal("expected at least one key in JWKS document")
	}
}

func TestJWKSHandler_StatusOK(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	handler := crypto.JWKSHandler(ks)
	req := httptest.NewRequest(http.MethodGet, "/.well-known/jwks.json", nil)
	rec := httptest.NewRecorder()

	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", rec.Code)
	}
}

func TestJWKSHandler_ContentTypeJSON(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	handler := crypto.JWKSHandler(ks)
	req := httptest.NewRequest(http.MethodGet, "/.well-known/jwks.json", nil)
	rec := httptest.NewRecorder()

	handler(rec, req)

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %q", ct)
	}
}

func TestJWKSHandler_BodyIsValidJWKS(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmES256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	handler := crypto.JWKSHandler(ks)
	req := httptest.NewRequest(http.MethodGet, "/.well-known/jwks.json", nil)
	rec := httptest.NewRecorder()

	handler(rec, req)

	var parsed map[string]interface{}
	if err := json.NewDecoder(rec.Body).Decode(&parsed); err != nil {
		t.Fatalf("response body is not valid JSON: %v", err)
	}

	if _, ok := parsed["keys"]; !ok {
		t.Error("expected 'keys' field in JWKS response body")
	}
}
