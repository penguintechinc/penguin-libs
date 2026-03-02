// Package crypto provides cryptographic key management for Penguin Tech authentication services.
//
// It offers in-memory and file-backed key stores implementing the KeyStore interface,
// suitable for signing and verifying JWTs.
package crypto

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"encoding/json"
	"fmt"
	"os"
	"sync"

	"github.com/lestrrat-go/jwx/v2/jwa"
	"github.com/lestrrat-go/jwx/v2/jwk"
)

// KeyStore manages cryptographic keys used for signing and verifying tokens.
type KeyStore interface {
	// GetSigningKey returns the current private key used for signing tokens.
	GetSigningKey() (jwk.Key, error)
	// GetKeySet returns the public key set used for token verification.
	GetKeySet() (jwk.Set, error)
	// RotateKey generates a new signing key, retiring the previous one.
	RotateKey() error
}

// Algorithm identifies the key generation algorithm for a key store.
type Algorithm string

const (
	// AlgorithmRS256 uses 2048-bit RSA keys with SHA-256.
	AlgorithmRS256 Algorithm = "RS256"
	// AlgorithmES256 uses P-256 elliptic curve keys with SHA-256.
	AlgorithmES256 Algorithm = "ES256"
)

// MemoryKeyStore is a thread-safe, in-memory key store that generates and
// manages JWK keys without any persistent storage.
type MemoryKeyStore struct {
	mu         sync.RWMutex
	algorithm  Algorithm
	signingKey jwk.Key
	keySet     jwk.Set
}

// NewMemoryKeyStore creates a MemoryKeyStore using the given algorithm and
// generates an initial signing key.
func NewMemoryKeyStore(algorithm Algorithm) (*MemoryKeyStore, error) {
	ks := &MemoryKeyStore{algorithm: algorithm}
	if err := ks.RotateKey(); err != nil {
		return nil, fmt.Errorf("memory_keystore: failed to generate initial key: %w", err)
	}
	return ks, nil
}

// GetSigningKey returns the current private signing key.
func (ks *MemoryKeyStore) GetSigningKey() (jwk.Key, error) {
	ks.mu.RLock()
	defer ks.mu.RUnlock()
	if ks.signingKey == nil {
		return nil, fmt.Errorf("memory_keystore: no signing key available")
	}
	return ks.signingKey, nil
}

// GetKeySet returns a JWK set containing the current public key.
func (ks *MemoryKeyStore) GetKeySet() (jwk.Set, error) {
	ks.mu.RLock()
	defer ks.mu.RUnlock()
	if ks.keySet == nil {
		return nil, fmt.Errorf("memory_keystore: no key set available")
	}
	return ks.keySet, nil
}

// RotateKey generates a new signing key and replaces the current key set.
func (ks *MemoryKeyStore) RotateKey() error {
	privateKey, err := generateKey(ks.algorithm)
	if err != nil {
		return fmt.Errorf("memory_keystore: key generation failed: %w", err)
	}

	signingKey, err := jwk.FromRaw(privateKey)
	if err != nil {
		return fmt.Errorf("memory_keystore: failed to create jwk from private key: %w", err)
	}
	if err := setKeyAlgorithm(signingKey, ks.algorithm); err != nil {
		return err
	}

	publicKey, err := signingKey.PublicKey()
	if err != nil {
		return fmt.Errorf("memory_keystore: failed to derive public key: %w", err)
	}

	keySet := jwk.NewSet()
	if err := keySet.AddKey(publicKey); err != nil {
		return fmt.Errorf("memory_keystore: failed to add public key to set: %w", err)
	}

	ks.mu.Lock()
	defer ks.mu.Unlock()
	ks.signingKey = signingKey
	ks.keySet = keySet
	return nil
}

// fileKeyStoreData is the JSON-serializable representation of a FileKeyStore's state.
type fileKeyStoreData struct {
	Algorithm  Algorithm       `json:"algorithm"`
	PrivateKey json.RawMessage `json:"private_key"`
}

// FileKeyStore is a thread-safe, disk-backed key store. It persists the current
// signing key to a JSON file, loading it on creation and writing after each rotation.
type FileKeyStore struct {
	mu        sync.RWMutex
	algorithm Algorithm
	filePath  string
	inner     *MemoryKeyStore
}

// NewFileKeyStore creates a FileKeyStore backed by filePath. If the file exists and
// contains a valid key, it is loaded; otherwise a new key is generated and saved.
func NewFileKeyStore(algorithm Algorithm, filePath string) (*FileKeyStore, error) {
	fks := &FileKeyStore{
		algorithm: algorithm,
		filePath:  filePath,
	}

	loaded, err := fks.loadFromDisk()
	if err != nil {
		return nil, fmt.Errorf("file_keystore: failed to load key from %q: %w", filePath, err)
	}
	if !loaded {
		inner, err := NewMemoryKeyStore(algorithm)
		if err != nil {
			return nil, err
		}
		fks.inner = inner
		if err := fks.saveToDisk(); err != nil {
			return nil, fmt.Errorf("file_keystore: failed to save initial key to %q: %w", filePath, err)
		}
	}

	return fks, nil
}

// GetSigningKey returns the current private signing key.
func (fks *FileKeyStore) GetSigningKey() (jwk.Key, error) {
	fks.mu.RLock()
	defer fks.mu.RUnlock()
	return fks.inner.GetSigningKey()
}

// GetKeySet returns a JWK set containing the current public key.
func (fks *FileKeyStore) GetKeySet() (jwk.Set, error) {
	fks.mu.RLock()
	defer fks.mu.RUnlock()
	return fks.inner.GetKeySet()
}

// RotateKey generates a new key, replacing the current key both in memory and on disk.
func (fks *FileKeyStore) RotateKey() error {
	fks.mu.Lock()
	defer fks.mu.Unlock()

	if err := fks.inner.RotateKey(); err != nil {
		return err
	}
	return fks.saveToDisk()
}

// loadFromDisk attempts to read and deserialize the key from the backing file.
// It returns (true, nil) if the key was successfully loaded, (false, nil) if the
// file does not exist, and (false, err) on any other error.
func (fks *FileKeyStore) loadFromDisk() (bool, error) {
	data, err := os.ReadFile(fks.filePath)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("read file: %w", err)
	}

	var stored fileKeyStoreData
	if err := json.Unmarshal(data, &stored); err != nil {
		return false, fmt.Errorf("unmarshal key data: %w", err)
	}

	keySet, err := jwk.ParseString(string(stored.PrivateKey))
	if err != nil {
		return false, fmt.Errorf("parse jwk: %w", err)
	}
	if keySet.Len() == 0 {
		return false, fmt.Errorf("key file contains no keys")
	}

	signingKey, ok := keySet.Key(0)
	if !ok {
		return false, fmt.Errorf("failed to retrieve key at index 0")
	}

	publicKey, err := signingKey.PublicKey()
	if err != nil {
		return false, fmt.Errorf("derive public key: %w", err)
	}
	pubSet := jwk.NewSet()
	if err := pubSet.AddKey(publicKey); err != nil {
		return false, fmt.Errorf("add public key to set: %w", err)
	}

	inner := &MemoryKeyStore{
		algorithm:  stored.Algorithm,
		signingKey: signingKey,
		keySet:     pubSet,
	}
	fks.inner = inner
	return true, nil
}

// saveToDisk serializes the current private key to the backing file.
// Must be called with fks.mu held (write lock).
func (fks *FileKeyStore) saveToDisk() error {
	signingKey, err := fks.inner.GetSigningKey()
	if err != nil {
		return err
	}

	keyJSON, err := json.Marshal(signingKey)
	if err != nil {
		return fmt.Errorf("marshal signing key: %w", err)
	}

	stored := fileKeyStoreData{
		Algorithm:  fks.algorithm,
		PrivateKey: json.RawMessage(keyJSON),
	}
	data, err := json.MarshalIndent(stored, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal key data: %w", err)
	}

	return os.WriteFile(fks.filePath, data, 0o600)
}

// generateKey creates a new raw private key for the given algorithm.
func generateKey(algorithm Algorithm) (interface{}, error) {
	switch algorithm {
	case AlgorithmRS256:
		return rsa.GenerateKey(rand.Reader, 2048)
	case AlgorithmES256:
		return ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	default:
		return nil, fmt.Errorf("unsupported algorithm %q", algorithm)
	}
}

// setKeyAlgorithm assigns the JWA algorithm identifier to a JWK key.
func setKeyAlgorithm(key jwk.Key, algorithm Algorithm) error {
	switch algorithm {
	case AlgorithmRS256:
		return key.Set(jwk.AlgorithmKey, jwa.RS256)
	case AlgorithmES256:
		return key.Set(jwk.AlgorithmKey, jwa.ES256)
	default:
		return fmt.Errorf("unsupported algorithm %q", algorithm)
	}
}
