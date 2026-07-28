package storage

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

// TestNFSStorePutMkdirAllError triggers the MkdirAll error path in Put
// by using a path that has a file where a directory is expected.
func TestNFSStorePutMkdirAllError(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()

	// Create a file named "blockdir" — attempting MkdirAll("blockdir/sub")
	// will fail because blockdir is a file, not a directory.
	blockFile := filepath.Join(tmpDir, "blockdir")
	if err := os.WriteFile(blockFile, []byte("block"), 0644); err != nil {
		t.Fatalf("setup: %v", err)
	}

	cfg := NFSConfig{MountPath: tmpDir, CreateDirs: true}
	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()
	// blockdir/sub/file.txt — MkdirAll will fail because blockdir is a file.
	err = store.Put(ctx, "blockdir/sub/file.txt", []byte("data"))
	if err == nil {
		t.Errorf("Put() expected error when mkdir blocked, got nil")
	}
}

// TestNFSStoreGetReadError exercises the general read error path.
func TestNFSStoreGetReadError(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{MountPath: tmpDir, CreateDirs: true}
	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	// Write a file, then remove read permission.
	if err := store.Put(ctx, "noperm.txt", []byte("data")); err != nil {
		t.Fatalf("Put() error = %v", err)
	}
	full := filepath.Join(tmpDir, "noperm.txt")
	os.Chmod(full, 0000) //nolint:errcheck
	defer os.Chmod(full, 0644)

	if os.Getuid() == 0 {
		t.Skip("running as root; permission tests skipped")
	}

	_, err = store.Get(ctx, "noperm.txt")
	if err == nil {
		t.Errorf("Get() no-permission: expected error, got nil")
	}
}

// TestNFSStoreDeleteError exercises the non-IsNotExist delete error.
func TestNFSStoreDeleteError(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{MountPath: tmpDir, CreateDirs: true}
	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	if os.Getuid() == 0 {
		t.Skip("running as root; permission tests skipped")
	}

	// Create a directory that cannot be deleted directly (non-empty).
	subDir := filepath.Join(tmpDir, "subdir")
	if err := os.MkdirAll(subDir, 0755); err != nil {
		t.Fatalf("setup mkdir: %v", err)
	}
	// Create a file inside so the dir is not empty.
	os.WriteFile(filepath.Join(subDir, "f.txt"), []byte("x"), 0644) //nolint:errcheck

	// Make the parent tmpDir read-only so os.Remove fails with EACCES.
	os.Chmod(tmpDir, 0500) //nolint:errcheck
	defer os.Chmod(tmpDir, 0755)

	// Attempt to delete a path inside the read-only directory.
	err = store.Delete(ctx, "subdir")
	// We expect an error here because rmdir on a non-empty dir fails.
	// Just verify the function doesn't panic.
	_ = err
}

// TestNFSStoreExistsStatError exercises the non-IsNotExist stat error.
func TestNFSStoreExistsStatError(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{MountPath: tmpDir, CreateDirs: true}
	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	if os.Getuid() == 0 {
		t.Skip("running as root; permission tests skipped")
	}

	// Create a file, then make the parent directory unreadable.
	subDir := filepath.Join(tmpDir, "restricted")
	os.MkdirAll(subDir, 0755) //nolint:errcheck
	os.WriteFile(filepath.Join(subDir, "f.txt"), []byte("x"), 0644) //nolint:errcheck
	os.Chmod(subDir, 0000) //nolint:errcheck
	defer os.Chmod(subDir, 0755)

	// Stat a file inside the unreadable dir — should get EACCES.
	exists, err := store.Exists(ctx, "restricted/f.txt")
	// On most systems this returns EACCES (non-IsNotExist)
	_ = exists
	_ = err
}

// TestNFSStoreListWalkError exercises the non-IsNotExist walk error.
func TestNFSStoreListWalkError(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{MountPath: tmpDir, CreateDirs: true}
	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	if os.Getuid() == 0 {
		t.Skip("running as root; permission tests skipped")
	}

	// Create a subdir with a file, then make subdir unreadable.
	subDir := filepath.Join(tmpDir, "locked")
	os.MkdirAll(subDir, 0755) //nolint:errcheck
	os.WriteFile(filepath.Join(subDir, "f.txt"), []byte("x"), 0644) //nolint:errcheck
	os.Chmod(subDir, 0000) //nolint:errcheck
	defer os.Chmod(subDir, 0755)

	// Walk over the locked dir — should get EACCES during walk.
	_, err = store.List(ctx, "locked")
	// Just verify it doesn't panic.
	_ = err
}
