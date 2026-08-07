package storage

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
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

// validatePath ensures the key does not escape the mount path via directory traversal.
func (n *NFSStore) validatePath(key string) error {
	// Reject paths with directory traversal attempts
	if strings.Contains(key, "..") {
		return fmt.Errorf("go-dal: nfs: %w: path traversal detected", dal.ErrInvalidConfiguration)
	}
	// Ensure the resolved path is under MountPath
	fullPath := filepath.Join(n.cfg.MountPath, key)
	absMount, err := filepath.Abs(n.cfg.MountPath)
	if err != nil {
		return fmt.Errorf("go-dal: nfs: %w: mount path resolution failed", dal.ErrConnectionFailed)
	}
	absPath, err := filepath.Abs(fullPath)
	if err != nil {
		return fmt.Errorf("go-dal: nfs: %w: path resolution failed", dal.ErrConnectionFailed)
	}
	// Ensure absPath is under absMount (check prefix + is not equal to mount root)
	if !strings.HasPrefix(absPath+string(filepath.Separator), absMount+string(filepath.Separator)) {
		return fmt.Errorf("go-dal: nfs: %w: path escapes mount directory", dal.ErrInvalidConfiguration)
	}
	return nil
}

// Put writes data to NFS.
func (n *NFSStore) Put(ctx context.Context, key string, data []byte, opts ...dal.PutOption) error {
	if err := n.validatePath(key); err != nil {
		return err
	}
	fullPath := filepath.Join(n.cfg.MountPath, key)

	if n.cfg.CreateDirs {
		dir := filepath.Dir(fullPath)
		if err := os.MkdirAll(dir, 0700); err != nil {
			return fmt.Errorf("go-dal: nfs: put mkdir: %w", err)
		}
	}

	if err := os.WriteFile(fullPath, data, 0600); err != nil {
		return fmt.Errorf("go-dal: nfs: put write: %w", err)
	}

	return nil
}

// Get retrieves data from NFS.
func (n *NFSStore) Get(ctx context.Context, key string) ([]byte, error) {
	if err := n.validatePath(key); err != nil {
		return nil, err
	}
	fullPath := filepath.Join(n.cfg.MountPath, key)

	//nolint:gosec // G304: validatePath() guards against directory traversal and escape sequences
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
	if err := n.validatePath(key); err != nil {
		return err
	}
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
	if err := n.validatePath(key); err != nil {
		return false, err
	}
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
	if err := n.validatePath(prefix); err != nil {
		return nil, err
	}
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
	if err := n.validatePath(key); err != nil {
		return "", err
	}
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
