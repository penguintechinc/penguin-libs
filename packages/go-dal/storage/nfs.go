package storage

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// NFSConfig configures an NFS storage backend.
type NFSConfig struct {
	MountPath  string
	CreateDirs bool
}

// NFSStore implements dal.StorageStore for NFS/iSCSI mounts.
type NFSStore struct {
	cfg NFSConfig
}

// NewNFSStore creates a new NFS storage backend.
func NewNFSStore(cfg NFSConfig) (*NFSStore, error) {
	if cfg.MountPath == "" {
		return nil, fmt.Errorf("go-dal: nfs: %w: mount path required", dal.ErrInvalidConfiguration)
	}

	info, err := os.Stat(cfg.MountPath)
	if err != nil {
		return nil, fmt.Errorf("go-dal: nfs: %w: mount path not accessible", dal.ErrConnectionFailed)
	}

	if !info.IsDir() {
		return nil, fmt.Errorf("go-dal: nfs: %w: mount path must be directory", dal.ErrInvalidConfiguration)
	}

	return &NFSStore{cfg: cfg}, nil
}

// Put writes data to NFS.
func (n *NFSStore) Put(ctx context.Context, key string, data []byte, opts ...dal.PutOption) error {
	fullPath := filepath.Join(n.cfg.MountPath, key)

	if n.cfg.CreateDirs {
		dir := filepath.Dir(fullPath)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("go-dal: nfs: put mkdir: %w", err)
		}
	}

	if err := os.WriteFile(fullPath, data, 0644); err != nil {
		return fmt.Errorf("go-dal: nfs: put write: %w", err)
	}

	return nil
}

// Get retrieves data from NFS.
func (n *NFSStore) Get(ctx context.Context, key string) ([]byte, error) {
	fullPath := filepath.Join(n.cfg.MountPath, key)

	data, err := os.ReadFile(fullPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("go-dal: nfs: get: %w", dal.ErrNotFound)
		}
		return nil, fmt.Errorf("go-dal: nfs: get read: %w", err)
	}

	return data, nil
}

// Delete removes a file from NFS.
func (n *NFSStore) Delete(ctx context.Context, key string) error {
	fullPath := filepath.Join(n.cfg.MountPath, key)

	if err := os.Remove(fullPath); err != nil {
		if os.IsNotExist(err) {
			return nil // idempotent
		}
		return fmt.Errorf("go-dal: nfs: delete: %w", err)
	}

	return nil
}

// Exists checks if a file exists on NFS.
func (n *NFSStore) Exists(ctx context.Context, key string) (bool, error) {
	fullPath := filepath.Join(n.cfg.MountPath, key)

	_, err := os.Stat(fullPath)
	if err == nil {
		return true, nil
	}

	if os.IsNotExist(err) {
		return false, nil
	}

	return false, fmt.Errorf("go-dal: nfs: exists: %w", err)
}

// List returns all files under a prefix.
func (n *NFSStore) List(ctx context.Context, prefix string) ([]string, error) {
	fullPrefix := filepath.Join(n.cfg.MountPath, prefix)

	var keys []string
	err := filepath.Walk(fullPrefix, func(fullPath string, info os.FileInfo, err error) error {
		if err != nil {
			if os.IsNotExist(err) {
				return nil // prefix not found; return empty list
			}
			return err
		}

		if !info.IsDir() {
			relPath, _ := filepath.Rel(n.cfg.MountPath, fullPath)
			keys = append(keys, relPath)
		}

		return nil
	})

	if err != nil && !os.IsNotExist(err) {
		return nil, fmt.Errorf("go-dal: nfs: list walk: %w", err)
	}

	return keys, nil
}

// GetURL returns a file:// URL for local access.
func (n *NFSStore) GetURL(ctx context.Context, key string, expiresIn time.Duration) (string, error) {
	fullPath := filepath.Join(n.cfg.MountPath, key)
	absPath, err := filepath.Abs(fullPath)
	if err != nil {
		return "", fmt.Errorf("go-dal: nfs: url abs: %w", err)
	}

	return "file://" + absPath, nil
}

// Close closes the NFS store (no-op).
func (n *NFSStore) Close() error {
	return nil
}
