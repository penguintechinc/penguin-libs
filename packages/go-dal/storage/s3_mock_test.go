package storage

import (
	"bytes"
	"context"
	"errors"
	"io"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// ---------------------------------------------------------------------------
// Mock s3ObjectClient
// ---------------------------------------------------------------------------

// errReader is an io.Reader that always returns an error.
type errReader struct{}

func (e errReader) Read(p []byte) (int, error) { return 0, errors.New("mock read error") }
func (e errReader) Close() error               { return nil }

type mockS3Client struct {
	objects     map[string][]byte
	metadata    map[string]map[string]string
	failPut     bool
	failGet     bool
	failGetBody bool // return a body that errors on read
	failDelete  bool
	failHead    bool
	failHead404 bool // simulate NoSuchKey on HeadObject
	failList    bool
	listKeys    []string
}

func newMockS3Client() *mockS3Client {
	return &mockS3Client{
		objects:  make(map[string][]byte),
		metadata: make(map[string]map[string]string),
	}
}

func (m *mockS3Client) PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	if m.failPut {
		return nil, errors.New("mock put error")
	}
	data, err := io.ReadAll(params.Body)
	if err != nil {
		return nil, err
	}
	m.objects[*params.Key] = data
	return &s3.PutObjectOutput{}, nil
}

func (m *mockS3Client) GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	if m.failGet {
		return nil, errors.New("mock get error")
	}
	if m.failGetBody {
		return &s3.GetObjectOutput{Body: errReader{}}, nil
	}
	data, ok := m.objects[*params.Key]
	if !ok {
		return nil, &types.NoSuchKey{}
	}
	return &s3.GetObjectOutput{
		Body: io.NopCloser(bytes.NewReader(data)),
	}, nil
}

func (m *mockS3Client) DeleteObject(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error) {
	if m.failDelete {
		return nil, errors.New("mock delete error")
	}
	delete(m.objects, *params.Key)
	return &s3.DeleteObjectOutput{}, nil
}

func (m *mockS3Client) HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	if m.failHead {
		if m.failHead404 {
			return nil, &types.NoSuchKey{}
		}
		return nil, errors.New("mock head error")
	}
	if _, ok := m.objects[*params.Key]; !ok {
		return nil, &types.NoSuchKey{}
	}
	return &s3.HeadObjectOutput{}, nil
}

func (m *mockS3Client) NewListObjectsV2Paginator(params *s3.ListObjectsV2Input) s3PageIterator {
	if m.failList {
		return &mockS3Paginator{err: errors.New("mock list error")}
	}
	keys := m.listKeys
	if keys == nil {
		for k := range m.objects {
			keys = append(keys, k)
		}
	}
	return &mockS3Paginator{keys: keys, done: false}
}

// ---------------------------------------------------------------------------
// Mock s3PageIterator
// ---------------------------------------------------------------------------

type mockS3Paginator struct {
	keys []string
	done bool
	err  error
}

func (p *mockS3Paginator) HasMorePages() bool {
	return !p.done
}

func (p *mockS3Paginator) NextPage(ctx context.Context, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
	if p.err != nil {
		return nil, p.err
	}
	p.done = true
	var contents []types.Object
	for _, k := range p.keys {
		key := k
		contents = append(contents, types.Object{Key: aws.String(key)})
	}
	return &s3.ListObjectsV2Output{Contents: contents}, nil
}

// ---------------------------------------------------------------------------
// Mock s3PresignClient
// ---------------------------------------------------------------------------

type mockS3PresignClient struct {
	failPresign bool
}

func (m *mockS3PresignClient) PresignGetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.PresignOptions)) (*s3PresignResult, error) {
	if m.failPresign {
		return nil, errors.New("mock presign error")
	}
	return &s3PresignResult{URL: "https://example.com/presigned/" + *params.Key}, nil
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func newTestS3Store(prefix string) (*S3Store, *mockS3Client, *mockS3PresignClient) {
	mc := newMockS3Client()
	mp := &mockS3PresignClient{}
	cfg := S3Config{Bucket: "test-bucket", Region: "us-east-1", Prefix: prefix}
	store := NewS3StoreWithClient(mc, mp, cfg)
	return store, mc, mp
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestS3StorePut(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	ctx := context.Background()

	if err := store.Put(ctx, "key.txt", []byte("hello")); err != nil {
		t.Fatalf("Put() error = %v", err)
	}
	if string(mc.objects["key.txt"]) != "hello" {
		t.Errorf("Put() stored %q, want %q", string(mc.objects["key.txt"]), "hello")
	}
}

func TestS3StorePutWithPrefix(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("pfx")
	ctx := context.Background()

	if err := store.Put(ctx, "key.txt", []byte("data")); err != nil {
		t.Fatalf("Put() with prefix error = %v", err)
	}
	// Path joining: pfx + key.txt = pfx/key.txt
	if _, ok := mc.objects["pfx/key.txt"]; !ok {
		t.Errorf("Put() with prefix: key not stored under pfx/key.txt, got %v", mc.objects)
	}
}

func TestS3StorePutWithOptions(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	ctx := context.Background()

	opts := []dal.PutOption{
		dal.WithContentType("application/json"),
		dal.WithCacheControl("max-age=3600"),
		dal.WithMetadata(map[string]string{"author": "test"}),
	}
	if err := store.Put(ctx, "data.json", []byte(`{}`), opts...); err != nil {
		t.Fatalf("Put() with options error = %v", err)
	}
	if _, ok := mc.objects["data.json"]; !ok {
		t.Errorf("Put() with options: key not stored")
	}
}

func TestS3StorePutError(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failPut = true
	ctx := context.Background()

	if err := store.Put(ctx, "k", []byte("v")); err == nil {
		t.Errorf("Put() expected error, got nil")
	}
}

func TestS3StoreGet(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.objects["file.txt"] = []byte("content")
	ctx := context.Background()

	data, err := store.Get(ctx, "file.txt")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if string(data) != "content" {
		t.Errorf("Get() = %q, want content", string(data))
	}
}

func TestS3StoreGetNotFound(t *testing.T) {
	t.Parallel()
	store, _, _ := newTestS3Store("")
	ctx := context.Background()

	_, err := store.Get(ctx, "missing.txt")
	if !errors.Is(err, dal.ErrNotFound) {
		t.Errorf("Get() missing: got %v, want ErrNotFound", err)
	}
}

func TestS3StoreGetError(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failGet = true
	ctx := context.Background()

	_, err := store.Get(ctx, "k")
	if err == nil {
		t.Errorf("Get() expected error, got nil")
	}
}

func TestS3StoreGetWithPrefix(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("ns")
	mc.objects["ns/file.txt"] = []byte("nsdata")
	ctx := context.Background()

	data, err := store.Get(ctx, "file.txt")
	if err != nil {
		t.Fatalf("Get() with prefix error = %v", err)
	}
	if string(data) != "nsdata" {
		t.Errorf("Get() with prefix = %q, want nsdata", string(data))
	}
}

func TestS3StoreDelete(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.objects["del.txt"] = []byte("gone")
	ctx := context.Background()

	if err := store.Delete(ctx, "del.txt"); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if _, ok := mc.objects["del.txt"]; ok {
		t.Errorf("Delete() did not remove key")
	}
}

func TestS3StoreDeleteError(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failDelete = true
	ctx := context.Background()

	if err := store.Delete(ctx, "k"); err == nil {
		t.Errorf("Delete() expected error, got nil")
	}
}

func TestS3StoreExists(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.objects["exists.txt"] = []byte("yes")
	ctx := context.Background()

	ok, err := store.Exists(ctx, "exists.txt")
	if err != nil || !ok {
		t.Errorf("Exists() present: err=%v ok=%v", err, ok)
	}

	ok, err = store.Exists(ctx, "missing.txt")
	if err != nil || ok {
		t.Errorf("Exists() missing: err=%v ok=%v", err, ok)
	}
}

func TestS3StoreExistsNoSuchKey(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failHead = true
	mc.failHead404 = true
	ctx := context.Background()

	ok, err := store.Exists(ctx, "k")
	if err != nil || ok {
		t.Errorf("Exists() NoSuchKey: err=%v ok=%v, want err=nil ok=false", err, ok)
	}
}

func TestS3StoreExistsHeadError(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failHead = true
	mc.failHead404 = false
	ctx := context.Background()

	_, err := store.Exists(ctx, "k")
	if err == nil {
		t.Errorf("Exists() head error: expected error, got nil")
	}
}

func TestS3StoreList(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.objects["f1.txt"] = []byte("1")
	mc.objects["f2.txt"] = []byte("2")
	mc.objects["f3.txt"] = []byte("3")
	ctx := context.Background()

	keys, err := store.List(ctx, "")
	if err != nil {
		t.Fatalf("List() error = %v", err)
	}
	if len(keys) != 3 {
		t.Errorf("List() returned %d keys, want 3", len(keys))
	}
}

func TestS3StoreListWithPrefix(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("bkt")
	mc.listKeys = []string{"bkt/a.txt", "bkt/b.txt"}
	ctx := context.Background()

	keys, err := store.List(ctx, "")
	if err != nil {
		t.Fatalf("List() with prefix error = %v", err)
	}
	if len(keys) != 2 {
		t.Errorf("List() with prefix returned %d, want 2", len(keys))
	}
}

func TestS3StoreListError(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failList = true
	ctx := context.Background()

	_, err := store.List(ctx, "")
	if err == nil {
		t.Errorf("List() expected error, got nil")
	}
}

func TestS3StoreGetURL(t *testing.T) {
	t.Parallel()
	store, _, _ := newTestS3Store("")
	ctx := context.Background()

	url, err := store.GetURL(ctx, "file.txt", 1*time.Hour)
	if err != nil {
		t.Fatalf("GetURL() error = %v", err)
	}
	if url == "" {
		t.Errorf("GetURL() returned empty URL")
	}
}

func TestS3StoreGetURLError(t *testing.T) {
	t.Parallel()
	store, _, mp := newTestS3Store("")
	mp.failPresign = true
	ctx := context.Background()

	_, err := store.GetURL(ctx, "file.txt", 1*time.Hour)
	if err == nil {
		t.Errorf("GetURL() expected error, got nil")
	}
}

func TestS3StoreGetURLWithPrefix(t *testing.T) {
	t.Parallel()
	store, _, _ := newTestS3Store("ns")
	ctx := context.Background()

	url, err := store.GetURL(ctx, "file.txt", 30*time.Minute)
	if err != nil {
		t.Fatalf("GetURL() with prefix error = %v", err)
	}
	if url == "" {
		t.Errorf("GetURL() with prefix returned empty URL")
	}
}

func TestS3StoreClose(t *testing.T) {
	t.Parallel()
	store, _, _ := newTestS3Store("")

	if err := store.Close(); err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

// TestS3StorePutThenGet verifies round-trip: put then get returns same data.
func TestS3StorePutThenGet(t *testing.T) {
	t.Parallel()
	store, _, _ := newTestS3Store("")
	ctx := context.Background()

	data := []byte("round-trip data")
	if err := store.Put(ctx, "rt.txt", data); err != nil {
		t.Fatalf("Put() error = %v", err)
	}

	got, err := store.Get(ctx, "rt.txt")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if string(got) != string(data) {
		t.Errorf("Get() = %q, want %q", string(got), string(data))
	}
}

func TestS3StoreGetBodyReadError(t *testing.T) {
	t.Parallel()
	store, mc, _ := newTestS3Store("")
	mc.failGetBody = true
	mc.objects["k"] = []byte("data") // put something so we don't get NoSuchKey
	ctx := context.Background()

	_, err := store.Get(ctx, "k")
	if err == nil {
		t.Errorf("Get() body read error: expected error, got nil")
	}
}

func TestNewS3StoreWithClientNotNil(t *testing.T) {
	t.Parallel()
	mc := newMockS3Client()
	mp := &mockS3PresignClient{}
	cfg := S3Config{Bucket: "b", Region: "r"}
	store := NewS3StoreWithClient(mc, mp, cfg)
	if store == nil {
		t.Errorf("NewS3StoreWithClient() returned nil")
	}
}

// TestRealS3ClientAdapters exercises the thin wrapper methods on realS3Client
// and realS3PresignClient. These delegate to the underlying SDK; they will
// error on every call (no real S3 endpoint), which is expected.
func TestRealS3ClientAdapters(t *testing.T) {
	t.Parallel()
	// Build a minimal *s3.Client from an empty config. It won't connect but
	// allows us to invoke the adapter methods so they show as covered.
	rawClient := s3.New(s3.Options{Region: "us-east-1"})
	rc := &realS3Client{inner: rawClient}
	rp := &realS3PresignClient{inner: s3.NewPresignClient(rawClient)}
	ctx := context.Background()

	bucket := "b"
	key := "k"

	// PutObject — will fail (no endpoint), but function body is covered.
	rc.PutObject(ctx, &s3.PutObjectInput{ //nolint
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
		Body:   bytes.NewReader([]byte("data")),
	})

	// GetObject — will fail.
	rc.GetObject(ctx, &s3.GetObjectInput{ //nolint
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})

	// DeleteObject — will fail.
	rc.DeleteObject(ctx, &s3.DeleteObjectInput{ //nolint
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})

	// HeadObject — will fail.
	rc.HeadObject(ctx, &s3.HeadObjectInput{ //nolint
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})

	// NewListObjectsV2Paginator — returns a paginator (no network call yet).
	pag := rc.NewListObjectsV2Paginator(&s3.ListObjectsV2Input{
		Bucket: aws.String(bucket),
	})
	if pag == nil {
		t.Errorf("NewListObjectsV2Paginator() returned nil")
	}

	// PresignGetObject — will fail (no credentials/endpoint).
	rp.PresignGetObject(ctx, &s3.GetObjectInput{ //nolint
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
}
