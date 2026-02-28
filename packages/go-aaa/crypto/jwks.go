package crypto

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// JWKSBytes serializes the public key set from ks as a JWKS JSON document.
func JWKSBytes(ks KeyStore) ([]byte, error) {
	keySet, err := ks.GetKeySet()
	if err != nil {
		return nil, fmt.Errorf("jwks: failed to retrieve key set: %w", err)
	}

	data, err := json.Marshal(keySet)
	if err != nil {
		return nil, fmt.Errorf("jwks: failed to serialize key set: %w", err)
	}

	return data, nil
}

// JWKSHandler returns an http.HandlerFunc that serves the JWKS endpoint for ks.
// It sets the Content-Type header to application/json and responds with the
// public key set. On error it returns HTTP 500.
func JWKSHandler(ks KeyStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		data, err := JWKSBytes(ks)
		if err != nil {
			http.Error(w, "failed to retrieve keys", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "public, max-age=3600")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	}
}
