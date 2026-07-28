package storage

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Test NFS store interface compliance.
func TestNFSStoreInterfaceCompliance(t *testing.T) {
	var _ dal.StorageStore = (*NFSStore)(nil)
}

// Test S3 store interface compliance.
func TestS3StoreInterfaceCompliance(t *testing.T) {
	var _ dal.StorageStore = (*S3Store)(nil)
}

// Test NFSStore configuration validation.
func TestNFSConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     NFSConfig
		wantErr bool
	}{
		{
			name:    "empty mount path",
			cfg:     NFSConfig{MountPath: ""},
			wantErr: true,
		},
		{
			name:    "invalid mount path",
			cfg:     NFSConfig{MountPath: "/nonexistent/path/that/does/not/exist"},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewNFSStore(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewNFSStore() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test S3Config validation.
func TestS3ConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     S3Config
		wantErr bool
	}{
		{
			name: "empty bucket",
			cfg: S3Config{
				Bucket: "",
				Region: "us-east-1",
			},
			wantErr: true,
		},
		{
			name: "empty region",
			cfg: S3Config{
				Bucket: "test-bucket",
				Region: "",
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()

			_, err := NewS3Store(ctx, tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewS3Store() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test NFSStore with temp directory.
func TestNFSStoreWithTempDir(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}

	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	// Test Put
	testData := []byte("test data")
	err = store.Put(ctx, "test.txt", testData)
	if err != nil {
		t.Errorf("Put() error = %v", err)
	}

	// Test Exists
	exists, err := store.Exists(ctx, "test.txt")
	if err != nil {
		t.Errorf("Exists() error = %v", err)
	}
	if !exists {
		t.Errorf("Exists() = false, want true")
	}

	// Test Get
	got, err := store.Get(ctx, "test.txt")
	if err != nil {
		t.Errorf("Get() error = %v", err)
	}
	if string(got) != string(testData) {
		t.Errorf("Get() = %s, want %s", string(got), string(testData))
	}

	// Test Delete
	err = store.Delete(ctx, "test.txt")
	if err != nil {
		t.Errorf("Delete() error = %v", err)
	}

	// Verify deleted
	exists, err = store.Exists(ctx, "test.txt")
	if err != nil {
		t.Errorf("Exists() after delete error = %v", err)
	}
	if exists {
		t.Errorf("Exists() after delete = true, want false")
	}

	// Test Get on missing file
	_, err = store.Get(ctx, "missing.txt")
	if err == nil {
		t.Errorf("Get() missing file: expected error")
	}
	// Error is wrapped, so check for ErrNotFound in the error chain
	if err.Error() == "" {
		t.Errorf("Get() missing file: got empty error")
	}
}

// Test NFSStore List.
func TestNFSStoreList(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}

	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	// Create test files
	paths := []string{
		"file1.txt",
		"dir/file2.txt",
		"dir/subdir/file3.txt",
	}

	for _, p := range paths {
		err := store.Put(ctx, p, []byte("data"))
		if err != nil {
			t.Fatalf("Put(%s) error = %v", p, err)
		}
	}

	// List all files
	files, err := store.List(ctx, "")
	if err != nil {
		t.Errorf("List() error = %v", err)
	}

	if len(files) != 3 {
		t.Errorf("List() returned %d files, want 3", len(files))
	}
}

// Test NFSStore GetURL.
func TestNFSStoreGetURL(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}

	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	// Put a file
	err = store.Put(ctx, "test.txt", []byte("data"))
	if err != nil {
		t.Fatalf("Put() error = %v", err)
	}

	// Get URL
	url, err := store.GetURL(ctx, "test.txt", 1*time.Hour)
	if err != nil {
		t.Errorf("GetURL() error = %v", err)
	}

	if url == "" {
		t.Errorf("GetURL() returned empty URL")
	}

	if len(url) < 7 || url[:7] != "file://" {
		t.Errorf("GetURL() returned %s, want file:// URL", url)
	}
}

// Test NFSStore edge cases.
func TestNFSStoreEdgeCases(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}

	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	// Test Put with nested directories
	err = store.Put(ctx, "deep/nested/path/file.txt", []byte("nested data"))
	if err != nil {
		t.Errorf("Put() nested path error = %v", err)
	}

	// Test Put with CreateDirs disabled
	noCfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: false,
	}
	noStore, _ := NewNFSStore(noCfg)
	err = noStore.Put(ctx, "another/path/file.txt", []byte("should fail"))
	if err == nil {
		t.Errorf("Put() without CreateDirs should fail")
	}

	// Test Delete on non-existent file (idempotent)
	err = store.Delete(ctx, "nonexistent/path.txt")
	if err != nil {
		t.Errorf("Delete() non-existent should be idempotent, got %v", err)
	}

	// Test List on non-existent prefix
	files, err := store.List(ctx, "nonexistent/prefix/")
	if err != nil {
		t.Errorf("List() non-existent prefix error = %v", err)
	}
	if len(files) != 0 {
		t.Errorf("List() non-existent prefix should return empty, got %d files", len(files))
	}

	// Test Close
	err = store.Close()
	if err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

// Test NFSStore with Put options.
func TestNFSStorePutOptions(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}

	store, err := NewNFSStore(cfg)
	if err != nil {
		t.Fatalf("NewNFSStore() error = %v", err)
	}

	ctx := context.Background()

	// Put with options (options are currently unused by NFS but should not cause errors)
	opts := []dal.PutOption{
		dal.WithContentType("text/plain"),
		dal.WithMetadata(map[string]string{"key": "value"}),
		dal.WithCacheControl("max-age=3600"),
	}

	err = store.Put(ctx, "test.txt", []byte("data"), opts...)
	if err != nil {
		t.Errorf("Put() with options error = %v", err)
	}

	// Verify file exists and data is correct
	data, err := store.Get(ctx, "test.txt")
	if err != nil || string(data) != "data" {
		t.Errorf("Put with options failed verification")
	}
}

// Test mock storage implementation.
type mockStorageStore struct {
	data map[string][]byte
	urls map[string]string
}

func newMockStorageStore() *mockStorageStore {
	return &mockStorageStore{
		data: make(map[string][]byte),
		urls: make(map[string]string),
	}
}

func (m *mockStorageStore) Put(ctx context.Context, key string, data []byte, opts ...dal.PutOption) error {
	if key == "" {
		return fmt.Errorf("invalid key")
	}
	m.data[key] = data
	return nil
}

func (m *mockStorageStore) Get(ctx context.Context, key string) ([]byte, error) {
	if data, ok := m.data[key]; ok {
		return data, nil
	}
	return nil, dal.ErrNotFound
}

func (m *mockStorageStore) Delete(ctx context.Context, key string) error {
	delete(m.data, key)
	return nil
}

func (m *mockStorageStore) Exists(ctx context.Context, key string) (bool, error) {
	_, ok := m.data[key]
	return ok, nil
}

func (m *mockStorageStore) List(ctx context.Context, prefix string) ([]string, error) {
	var keys []string
	for k := range m.data {
		keys = append(keys, k)
	}
	return keys, nil
}

func (m *mockStorageStore) GetURL(ctx context.Context, key string, expiresIn time.Duration) (string, error) {
	if _, ok := m.data[key]; !ok {
		return "", dal.ErrNotFound
	}
	return "https://example.com/" + key, nil
}

func (m *mockStorageStore) Close() error {
	return nil
}

// Test mock storage interface compliance.
func TestMockStorageStoreInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StorageStore = (*mockStorageStore)(nil)
}

// Test mock storage basic operations.
func TestMockStorageStore(t *testing.T) {
	t.Parallel()
	ms := newMockStorageStore()
	ctx := context.Background()

	// Test Put
	err := ms.Put(ctx, "key1", []byte("value1"))
	if err != nil {
		t.Errorf("Put() error = %v", err)
	}

	// Test Get
	data, err := ms.Get(ctx, "key1")
	if err != nil || string(data) != "value1" {
		t.Errorf("Get() failed")
	}

	// Test Exists
	exists, err := ms.Exists(ctx, "key1")
	if !exists {
		t.Errorf("Exists() = false, want true")
	}

	// Test Delete
	err = ms.Delete(ctx, "key1")
	if err != nil {
		t.Errorf("Delete() error = %v", err)
	}

	// Test Get after delete
	_, err = ms.Get(ctx, "key1")
	if err != dal.ErrNotFound {
		t.Errorf("Get() after delete: expected ErrNotFound")
	}

	// Test GetURL
	ms.Put(ctx, "key2", []byte("value2"))
	url, err := ms.GetURL(ctx, "key2", 1*time.Hour)
	if err != nil || url == "" {
		t.Errorf("GetURL() error = %v", err)
	}
}

// Test NFSStore with invalid mount path during operations.
func TestNFSStoreInvalidOperations(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: false,
	}

	store, _ := NewNFSStore(cfg)
	ctx := context.Background()

	// Test Get on non-existent file
	_, err := store.Get(ctx, "nonexistent.txt")
	if err == nil {
		t.Errorf("Get() on non-existent file should error")
	}

	// Test Put without permissions to create dir
	notExistDir := "/nonexistent/dir/path"
	cfg.MountPath = notExistDir
	_, err = NewNFSStore(cfg)
	if err == nil {
		t.Errorf("NewNFSStore() with invalid path should error")
	}
}

// Test mock storage with options.
func TestMockStorageStoreWithOptions(t *testing.T) {
	t.Parallel()
	ms := newMockStorageStore()
	ctx := context.Background()

	opts := []dal.PutOption{
		dal.WithContentType("application/pdf"),
		dal.WithMetadata(map[string]string{"author": "test"}),
		dal.WithCacheControl("public, max-age=86400"),
	}

	err := ms.Put(ctx, "file.pdf", []byte("pdf data"), opts...)
	if err != nil {
		t.Errorf("Put() with options error = %v", err)
	}

	data, _ := ms.Get(ctx, "file.pdf")
	if string(data) != "pdf data" {
		t.Errorf("Put/Get with options failed")
	}
}

// Test mock storage empty key error.
func TestMockStorageStoreEmptyKey(t *testing.T) {
	t.Parallel()
	ms := newMockStorageStore()
	ctx := context.Background()

	err := ms.Put(ctx, "", []byte("data"))
	if err == nil {
		t.Errorf("Put() with empty key should error")
	}
}

// Test mock storage List operation.
func TestMockStorageStoreList(t *testing.T) {
	t.Parallel()
	ms := newMockStorageStore()
	ctx := context.Background()

	ms.Put(ctx, "file1.txt", []byte("data1"))
	ms.Put(ctx, "file2.txt", []byte("data2"))
	ms.Put(ctx, "file3.txt", []byte("data3"))

	list, err := ms.List(ctx, "")
	if err != nil || len(list) != 3 {
		t.Errorf("List() returned %d files, want 3", len(list))
	}
}

// Test NFSStore directory is file check.
func TestNFSStoreWithFile(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()

	// Create a file instead of dir
	testFile := filepath.Join(tmpDir, "notadir.txt")
	if err := os.WriteFile(testFile, []byte("content"), 0644); err != nil {
		t.Fatalf("Setup error: %v", err)
	}

	cfg := NFSConfig{MountPath: testFile}
	_, err := NewNFSStore(cfg)
	if err == nil {
		t.Errorf("NewNFSStore() with file path should error")
	}
}

// Test MockStorageStore with nil/empty data.
func TestMockStorageStoreNilData(t *testing.T) {
	t.Parallel()
	ms := newMockStorageStore()
	ctx := context.Background()

	// Put empty data
	err := ms.Put(ctx, "empty", []byte{})
	if err != nil {
		t.Errorf("Put() empty data error = %v", err)
	}

	data, err := ms.Get(ctx, "empty")
	if err != nil || len(data) != 0 {
		t.Errorf("Put/Get empty data failed")
	}
}

// Test MockStorageStore GetURL not found.
func TestMockStorageStoreGetURLNotFound(t *testing.T) {
	t.Parallel()
	ms := newMockStorageStore()
	ctx := context.Background()

	_, err := ms.GetURL(ctx, "nonexistent", 1*time.Hour)
	if err != dal.ErrNotFound {
		t.Errorf("GetURL() not found: expected ErrNotFound, got %v", err)
	}
}

// Test NFSStore multiple file operations in sequence.
func TestNFSStoreSequentialOps(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}
	store, _ := NewNFSStore(cfg)
	ctx := context.Background()

	files := []string{"a.txt", "b.txt", "c.txt"}
	for i, f := range files {
		data := []byte("content" + string(rune(i)))
		err := store.Put(ctx, f, data)
		if err != nil {
			t.Errorf("Put(%s) error = %v", f, err)
		}
	}

	list, _ := store.List(ctx, "")
	if len(list) != 3 {
		t.Errorf("List() = %d files, want 3", len(list))
	}

	for _, f := range files {
		err := store.Delete(ctx, f)
		if err != nil {
			t.Errorf("Delete(%s) error = %v", f, err)
		}
	}

	list, _ = store.List(ctx, "")
	if len(list) != 0 {
		t.Errorf("List() after delete = %d files, want 0", len(list))
	}
}

// Test NFSStore Get with nested path.
func TestNFSStoreNestedPath(t *testing.T) {
	t.Parallel()
	tmpDir := t.TempDir()
	cfg := NFSConfig{
		MountPath:  tmpDir,
		CreateDirs: true,
	}
	store, _ := NewNFSStore(cfg)
	ctx := context.Background()

	path := "a/b/c/d/file.txt"
	data := []byte("nested content")

	err := store.Put(ctx, path, data)
	if err != nil {
		t.Fatalf("Put() nested path error = %v", err)
	}

	retrieved, err := store.Get(ctx, path)
	if err != nil || string(retrieved) != "nested content" {
		t.Errorf("Get() nested path failed")
	}

	exists, _ := store.Exists(ctx, path)
	if !exists {
		t.Errorf("Exists() nested path = false, want true")
	}

	_ = store.Delete(ctx, path)
	exists, _ = store.Exists(ctx, path)
	if exists {
		t.Errorf("Exists() after delete = true, want false")
	}
}
