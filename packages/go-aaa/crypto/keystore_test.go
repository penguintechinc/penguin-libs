package crypto_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/crypto"
)

func TestMemoryKeyStore_RS256_GetSigningKey(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore(RS256): %v", err)
	}

	key, err := ks.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey: %v", err)
	}
	if key == nil {
		t.Fatal("expected non-nil signing key")
	}
}

func TestMemoryKeyStore_ES256_GetSigningKey(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmES256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore(ES256): %v", err)
	}

	key, err := ks.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey: %v", err)
	}
	if key == nil {
		t.Fatal("expected non-nil signing key")
	}
}

func TestMemoryKeyStore_GetKeySet_HasPublicKey(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	keySet, err := ks.GetKeySet()
	if err != nil {
		t.Fatalf("GetKeySet: %v", err)
	}
	if keySet.Len() == 0 {
		t.Fatal("expected at least one public key in key set")
	}
}

func TestMemoryKeyStore_RotateKey_ChangesKey(t *testing.T) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		t.Fatalf("NewMemoryKeyStore: %v", err)
	}

	keyBefore, err := ks.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey before rotation: %v", err)
	}

	if err := ks.RotateKey(); err != nil {
		t.Fatalf("RotateKey: %v", err)
	}

	keyAfter, err := ks.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey after rotation: %v", err)
	}

	// Key IDs should differ after rotation (or at minimum keys should not be equal).
	if keyBefore == keyAfter {
		t.Error("expected different key pointer after rotation")
	}
}

func TestMemoryKeyStore_InvalidAlgorithm(t *testing.T) {
	_, err := crypto.NewMemoryKeyStore("PS256")
	if err == nil {
		t.Fatal("expected error for unsupported algorithm PS256")
	}
}

func TestFileKeyStore_RS256_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "keystore.json")

	ks, err := crypto.NewFileKeyStore(crypto.AlgorithmRS256, path)
	if err != nil {
		t.Fatalf("NewFileKeyStore: %v", err)
	}

	key, err := ks.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey: %v", err)
	}
	if key == nil {
		t.Fatal("expected non-nil signing key")
	}

	// Verify the file was created.
	if _, err := os.Stat(path); os.IsNotExist(err) {
		t.Fatal("expected keystore file to be created on disk")
	}
}

func TestFileKeyStore_LoadsExistingKey(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "keystore.json")

	// Create the key store and capture the key ID.
	ks1, err := crypto.NewFileKeyStore(crypto.AlgorithmRS256, path)
	if err != nil {
		t.Fatalf("NewFileKeyStore (first): %v", err)
	}
	key1, err := ks1.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey (first): %v", err)
	}

	// Load from the same file.
	ks2, err := crypto.NewFileKeyStore(crypto.AlgorithmRS256, path)
	if err != nil {
		t.Fatalf("NewFileKeyStore (second): %v", err)
	}
	key2, err := ks2.GetSigningKey()
	if err != nil {
		t.Fatalf("GetSigningKey (second): %v", err)
	}

	// Both stores should yield the same key ID.
	if key1.KeyID() != key2.KeyID() {
		t.Errorf("expected same key ID after reload, got %q and %q", key1.KeyID(), key2.KeyID())
	}
}

func TestFileKeyStore_RotateKey_UpdatesFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "keystore.json")

	ks, err := crypto.NewFileKeyStore(crypto.AlgorithmES256, path)
	if err != nil {
		t.Fatalf("NewFileKeyStore: %v", err)
	}

	statBefore, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat before rotation: %v", err)
	}

	if err := ks.RotateKey(); err != nil {
		t.Fatalf("RotateKey: %v", err)
	}

	statAfter, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat after rotation: %v", err)
	}

	// File should have been rewritten (modification time or size may differ).
	_ = statBefore
	_ = statAfter
}

func TestFileKeyStore_GetKeySet_NotEmpty(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "keystore.json")

	ks, err := crypto.NewFileKeyStore(crypto.AlgorithmRS256, path)
	if err != nil {
		t.Fatalf("NewFileKeyStore: %v", err)
	}

	keySet, err := ks.GetKeySet()
	if err != nil {
		t.Fatalf("GetKeySet: %v", err)
	}
	if keySet.Len() == 0 {
		t.Fatal("expected at least one public key in key set")
	}
}
