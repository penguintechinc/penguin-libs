package storage

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Permission modes applied to NFS-backed content. Group/other access is
// deliberately restricted: data on a shared mount must not be world-readable.
const (
	nfsDirPerm  os.FileMode = 0o750
	nfsFilePerm os.FileMode = 0o640
)

// NFSConfig configures an NFS storage backend.
type NFSConfig struct {
	MountPath  string
	CreateDirs bool
}

// NFSStore implements dal.StorageStore for NFS/iSCSI mounts.
//
// All file access goes through an os.Root opened on MountPath, so keys
// cannot escape the mount via "..", absolute paths, or symlinks. Directories
// are created 0750 and files 0640. Call Close to release the root handle.
type NFSStore struct {
	cfg  NFSConfig
	root *os.Root
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

	root, err := os.OpenRoot(cfg.MountPath)
	if err != nil {
		return nil, fmt.Errorf("go-dal: nfs: %w: open mount root", dal.ErrConnectionFailed)
	}

	return &NFSStore{cfg: cfg, root: root}, nil
}

// openRoot returns the mount root handle, or an error for a zero-value or
// otherwise unconfigured NFSStore (construct stores with NewNFSStore).
func (n *NFSStore) openRoot() (*os.Root, error) {
	if n == nil || n.root == nil {
		return nil, fmt.Errorf("go-dal: nfs: %w: store not initialised (use NewNFSStore)", dal.ErrInvalidConfiguration)
	}
	return n.root, nil
}

// cleanKey validates a storage key and returns its cleaned relative form.
// Rejects empty keys, absolute paths, NUL bytes, and any ".." segment.
func cleanKey(key string) (string, error) {
	if key == "" {
		return "", fmt.Errorf("go-dal: nfs: %w: empty key", dal.ErrInvalidKey)
	}
	if strings.ContainsRune(key, 0) {
		return "", fmt.Errorf("go-dal: nfs: %w: NUL byte in key", dal.ErrInvalidKey)
	}
	if filepath.IsAbs(key) || strings.HasPrefix(key, "/") || strings.HasPrefix(key, `\`) {
		return "", fmt.Errorf("go-dal: nfs: %w: absolute key", dal.ErrInvalidKey)
	}
	for _, seg := range strings.Split(filepath.ToSlash(key), "/") {
		if seg == ".." {
			return "", fmt.Errorf("go-dal: nfs: %w: parent segment in key", dal.ErrInvalidKey)
		}
	}
	clean := filepath.Clean(key)
	if clean == "." {
		return "", fmt.Errorf("go-dal: nfs: %w: key resolves to mount root", dal.ErrInvalidKey)
	}
	return clean, nil
}

// Put writes data to NFS.
func (n *NFSStore) Put(ctx context.Context, key string, data []byte, opts ...dal.PutOption) error {
	clean, err := cleanKey(key)
	if err != nil {
		return err
	}

	root, err := n.openRoot()
	if err != nil {
		return err
	}

	if n.cfg.CreateDirs {
		if dir := filepath.Dir(clean); dir != "." {
			if err := root.MkdirAll(dir, nfsDirPerm); err != nil {
				return fmt.Errorf("go-dal: nfs: put mkdir: %w", err)
			}
		}
	}

	if err := root.WriteFile(clean, data, nfsFilePerm); err != nil {
		return fmt.Errorf("go-dal: nfs: put write: %w", err)
	}

	return nil
}

// Get retrieves data from NFS.
func (n *NFSStore) Get(ctx context.Context, key string) ([]byte, error) {
	clean, err := cleanKey(key)
	if err != nil {
		return nil, err
	}

	root, err := n.openRoot()
	if err != nil {
		return nil, err
	}

	data, err := root.ReadFile(clean)
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
	clean, err := cleanKey(key)
	if err != nil {
		return err
	}

	root, err := n.openRoot()
	if err != nil {
		return err
	}

	if err := root.Remove(clean); err != nil {
		if os.IsNotExist(err) {
			return nil // idempotent
		}
		return fmt.Errorf("go-dal: nfs: delete: %w", err)
	}

	return nil
}

// Exists checks if a file exists on NFS.
func (n *NFSStore) Exists(ctx context.Context, key string) (bool, error) {
	clean, err := cleanKey(key)
	if err != nil {
		return false, err
	}

	root, err := n.openRoot()
	if err != nil {
		return false, err
	}

	_, err = root.Stat(clean)
	if err == nil {
		return true, nil
	}

	if os.IsNotExist(err) {
		return false, nil
	}

	return false, fmt.Errorf("go-dal: nfs: exists: %w", err)
}

// List returns all files under a prefix. An empty prefix lists the whole mount.
func (n *NFSStore) List(ctx context.Context, prefix string) ([]string, error) {
	root, err := n.openRoot()
	if err != nil {
		return nil, err
	}

	walkRoot := "."
	if prefix != "" {
		clean, err := cleanKey(prefix)
		if err != nil {
			return nil, err
		}
		walkRoot = path.Clean(filepath.ToSlash(clean))
	}

	var keys []string
	err = fs.WalkDir(root.FS(), walkRoot, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			if os.IsNotExist(err) {
				return nil // prefix not found; return empty list
			}
			return err
		}

		if !d.IsDir() {
			keys = append(keys, p)
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
	clean, err := cleanKey(key)
	if err != nil {
		return "", err
	}

	root, err := n.openRoot()
	if err != nil {
		return "", err
	}

	absPath, err := filepath.Abs(filepath.Join(root.Name(), clean))
	if err != nil {
		return "", fmt.Errorf("go-dal: nfs: url abs: %w", err)
	}

	return "file://" + absPath, nil
}

// Close releases the mount root handle. Operations after Close fail.
func (n *NFSStore) Close() error {
	if n.root == nil {
		return nil
	}
	return n.root.Close()
}
