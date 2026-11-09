package storage

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// unsafeKeys are storage keys that must never resolve outside the mount path.
var unsafeKeys = []string{
	"../escape.txt",
	"a/../../escape.txt",
	"..",
	"/etc/passwd",
	"nul\x00byte.txt",
	"",
}

// TestNFSStoreRejectsUnsafeKeys is a regression test for SEC-GO-03 path traversal.
func TestNFSStoreRejectsUnsafeKeys(t *testing.T) {
	t.Parallel()
	store, err := NewNFSStore(NFSConfig{MountPath: t.TempDir(), CreateDirs: true})
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}
	ctx := context.Background()

	for _, key := range unsafeKeys {
		t.Run("key="+key, func(t *testing.T) {
			if err := store.Put(ctx, key, []byte("x")); !errors.Is(err, dal.ErrInvalidKey) {
				t.Errorf("Put(%q) error = %v, want ErrInvalidKey", key, err)
			}
			if _, err := store.Get(ctx, key); !errors.Is(err, dal.ErrInvalidKey) {
				t.Errorf("Get(%q) error = %v, want ErrInvalidKey", key, err)
			}
			if err := store.Delete(ctx, key); !errors.Is(err, dal.ErrInvalidKey) {
				t.Errorf("Delete(%q) error = %v, want ErrInvalidKey", key, err)
			}
			if _, err := store.Exists(ctx, key); !errors.Is(err, dal.ErrInvalidKey) {
				t.Errorf("Exists(%q) error = %v, want ErrInvalidKey", key, err)
			}
			if _, err := store.GetURL(ctx, key, 0); !errors.Is(err, dal.ErrInvalidKey) {
				t.Errorf("GetURL(%q) error = %v, want ErrInvalidKey", key, err)
			}
		})
	}
}

// TestNFSStoreRejectsUnsafeListPrefix ensures List cannot walk outside the mount path.
func TestNFSStoreRejectsUnsafeListPrefix(t *testing.T) {
	t.Parallel()
	store, err := NewNFSStore(NFSConfig{MountPath: t.TempDir()})
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}
	if _, err := store.List(context.Background(), "../"); !errors.Is(err, dal.ErrInvalidKey) {
		t.Errorf("List(../) error = %v, want ErrInvalidKey", err)
	}
}

// TestNFSStoreRejectsSymlinkEscape ensures a symlink inside the mount cannot redirect writes outside it.
func TestNFSStoreRejectsSymlinkEscape(t *testing.T) {
	t.Parallel()
	mount := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(mount, "link")); err != nil {
		t.Skipf("symlinks unsupported: %v", err)
	}
	store, err := NewNFSStore(NFSConfig{MountPath: mount, CreateDirs: true})
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	if err := store.Put(context.Background(), "link/pwned.txt", []byte("x")); err == nil {
		t.Fatal("Put through escaping symlink succeeded, want error")
	}
	if _, err := os.Stat(filepath.Join(outside, "pwned.txt")); !os.IsNotExist(err) {
		t.Errorf("file escaped mount path: stat err = %v", err)
	}
}

// TestNFSStoreSafeNestedKeyStillWorks guards against over-rejection of valid nested keys with dot segments.
func TestNFSStoreSafeNestedKeyStillWorks(t *testing.T) {
	t.Parallel()
	store, err := NewNFSStore(NFSConfig{MountPath: t.TempDir(), CreateDirs: true})
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}
	ctx := context.Background()
	if err := store.Put(ctx, "tenant/./b/doc.txt", []byte("ok")); err != nil {
		t.Fatalf("Put() with dot-segment key error = %v", err)
	}
	got, err := store.Get(ctx, "tenant/b/doc.txt")
	if err != nil || string(got) != "ok" {
		t.Errorf("Get() = %q, %v; want ok", got, err)
	}
}

// TestNFSStoreRestrictivePermissions is a regression test for SEC-GO-04 (0755/0644 world-readable).
func TestNFSStoreRestrictivePermissions(t *testing.T) {
	t.Parallel()
	mount := t.TempDir()
	store, err := NewNFSStore(NFSConfig{MountPath: mount, CreateDirs: true})
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}
	if err := store.Put(context.Background(), "secure/dir/file.txt", []byte("s")); err != nil {
		t.Fatalf("Put() error = %v", err)
	}

	dirInfo, err := os.Stat(filepath.Join(mount, "secure", "dir"))
	if err != nil {
		t.Fatalf("stat dir: %v", err)
	}
	if perm := dirInfo.Mode().Perm(); perm&0o007 != 0 {
		t.Errorf("dir perm = %o, want no 'other' access", perm)
	}

	fileInfo, err := os.Stat(filepath.Join(mount, "secure", "dir", "file.txt"))
	if err != nil {
		t.Fatalf("stat file: %v", err)
	}
	if perm := fileInfo.Mode().Perm(); perm&0o007 != 0 || perm&0o020 != 0 {
		t.Errorf("file perm = %o, want no 'other' access and no group write", perm)
	}
}

// TestS3StoreMaxReadBytes is a regression test for SEC-GO-09: an unbounded io.ReadAll on object bodies.
func TestS3StoreMaxReadBytes(t *testing.T) {
	t.Parallel()
	ctx := context.Background()

	mc := newMockS3Client()
	mc.objects["big"] = make([]byte, 2048)
	mc.objects["small"] = make([]byte, 512)
	store := NewS3StoreWithClient(mc, &mockS3PresignClient{}, S3Config{Bucket: "b", Region: "r", MaxReadBytes: 1024})

	if _, err := store.Get(ctx, "big"); err == nil {
		t.Error("Get() of object over MaxReadBytes returned nil error")
	}
	if data, err := store.Get(ctx, "small"); err != nil || len(data) != 512 {
		t.Errorf("Get() under limit = len %d, err %v; want 512, nil", len(data), err)
	}
}

// TestS3StoreDefaultMaxReadBytes ensures a zero config still applies a finite default cap.
func TestS3StoreDefaultMaxReadBytes(t *testing.T) {
	t.Parallel()
	if got := (S3Config{}).maxReadBytes(); got <= 0 {
		t.Errorf("default maxReadBytes = %d, want > 0", got)
	}
}

// TestZeroValueNFSStoreReturnsErrorNotPanic is a regression test: a zero-value NFSStore had a nil root and panicked.
func TestZeroValueNFSStoreReturnsErrorNotPanic(t *testing.T) {
	t.Parallel()
	ctx := context.Background()
	n := &NFSStore{}

	checks := map[string]func() error{
		"Put":    func() error { return n.Put(ctx, "k", []byte("v")) },
		"Get":    func() error { _, err := n.Get(ctx, "k"); return err },
		"Delete": func() error { return n.Delete(ctx, "k") },
		"Exists": func() error { _, err := n.Exists(ctx, "k"); return err },
		"List":   func() error { _, err := n.List(ctx, ""); return err },
		"GetURL": func() error { _, err := n.GetURL(ctx, "k", 0); return err },
	}
	for name, call := range checks {
		t.Run(name, func(t *testing.T) {
			defer func() {
				if r := recover(); r != nil {
					t.Fatalf("%s panicked on zero-value NFSStore: %v", name, r)
				}
			}()
			if err := call(); !errors.Is(err, dal.ErrInvalidConfiguration) {
				t.Errorf("%s error = %v, want ErrInvalidConfiguration", name, err)
			}
		})
	}
}

// TestNFSStoreGetURLUsesRootAndValidatedKey is a regression test: GetURL must build its path from the opened root, not cfg.MountPath.
func TestNFSStoreGetURLUsesRootAndValidatedKey(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	n, err := NewNFSStore(NFSConfig{MountPath: dir})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = n.Close() }()
	n.cfg.MountPath = "/somewhere/else" // must not influence the URL

	got, err := n.GetURL(context.Background(), "a/b.txt", 0)
	if err != nil {
		t.Fatalf("GetURL error = %v", err)
	}
	want := "file://" + filepath.Join(n.root.Name(), "a", "b.txt")
	if got != want {
		t.Errorf("GetURL = %q, want %q", got, want)
	}
	for _, k := range unsafeKeys {
		if _, err := n.GetURL(context.Background(), k, 0); !errors.Is(err, dal.ErrInvalidKey) {
			t.Errorf("GetURL(%q) error = %v, want ErrInvalidKey", k, err)
		}
	}
}
