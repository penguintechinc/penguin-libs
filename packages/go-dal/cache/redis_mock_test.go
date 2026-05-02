package cache

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"github.com/redis/go-redis/v9"
)

// ---------------------------------------------------------------------------
// mockRedisClient implements redisClient for unit tests.
// ---------------------------------------------------------------------------

type mockRedisClient struct {
	data       map[string]string
	counters   map[string]int64
	failGet    bool
	failSet    bool
	failDel    bool
	failExists bool
	failIncrBy bool
	failMGet   bool
	failFlush  bool
	failScan   bool
	failDelBatch bool
	// scanResults, if set, are keys returned by the mock Scan
	scanResults []string
}

func newMockRedisClient() *mockRedisClient {
	return &mockRedisClient{
		data:     make(map[string]string),
		counters: make(map[string]int64),
	}
}

func (m *mockRedisClient) Get(ctx context.Context, key string) *redis.StringCmd {
	cmd := redis.NewStringCmd(ctx)
	if m.failGet {
		cmd.SetErr(errors.New("mock get error"))
		return cmd
	}
	v, ok := m.data[key]
	if !ok {
		cmd.SetErr(redis.Nil)
		return cmd
	}
	cmd.SetVal(v)
	return cmd
}

func (m *mockRedisClient) Set(ctx context.Context, key string, value interface{}, expiration time.Duration) *redis.StatusCmd {
	cmd := redis.NewStatusCmd(ctx)
	if m.failSet {
		cmd.SetErr(errors.New("mock set error"))
		return cmd
	}
	switch v := value.(type) {
	case []byte:
		m.data[key] = string(v)
	case string:
		m.data[key] = v
	default:
		m.data[key] = fmt.Sprintf("%v", v)
	}
	cmd.SetVal("OK")
	return cmd
}

func (m *mockRedisClient) Del(ctx context.Context, keys ...string) *redis.IntCmd {
	cmd := redis.NewIntCmd(ctx)
	if m.failDel {
		cmd.SetErr(errors.New("mock del error"))
		return cmd
	}
	var n int64
	for _, k := range keys {
		if _, ok := m.data[k]; ok {
			delete(m.data, k)
			n++
		}
	}
	cmd.SetVal(n)
	return cmd
}

func (m *mockRedisClient) Exists(ctx context.Context, keys ...string) *redis.IntCmd {
	cmd := redis.NewIntCmd(ctx)
	if m.failExists {
		cmd.SetErr(errors.New("mock exists error"))
		return cmd
	}
	var n int64
	for _, k := range keys {
		if _, ok := m.data[k]; ok {
			n++
		}
	}
	cmd.SetVal(n)
	return cmd
}

func (m *mockRedisClient) IncrBy(ctx context.Context, key string, value int64) *redis.IntCmd {
	cmd := redis.NewIntCmd(ctx)
	if m.failIncrBy {
		cmd.SetErr(errors.New("mock incrby error"))
		return cmd
	}
	m.counters[key] += value
	cmd.SetVal(m.counters[key])
	return cmd
}

func (m *mockRedisClient) MGet(ctx context.Context, keys ...string) *redis.SliceCmd {
	cmd := redis.NewSliceCmd(ctx)
	if m.failMGet {
		cmd.SetErr(errors.New("mock mget error"))
		return cmd
	}
	vals := make([]interface{}, len(keys))
	for i, k := range keys {
		if v, ok := m.data[k]; ok {
			vals[i] = v
		} else {
			vals[i] = nil
		}
	}
	cmd.SetVal(vals)
	return cmd
}

func (m *mockRedisClient) FlushDB(ctx context.Context) *redis.StatusCmd {
	cmd := redis.NewStatusCmd(ctx)
	if m.failFlush {
		cmd.SetErr(errors.New("mock flushdb error"))
		return cmd
	}
	m.data = make(map[string]string)
	cmd.SetVal("OK")
	return cmd
}

func (m *mockRedisClient) Scan(ctx context.Context, cursor uint64, match string, count int64) *redis.ScanCmd {
	if m.failScan {
		return redis.NewScanCmdResult(nil, 0, errors.New("mock scan error"))
	}
	if len(m.scanResults) > 0 {
		// Return all keys in one page (cursor=0 means done).
		return redis.NewScanCmdResult(m.scanResults, 0, nil)
	}
	// Return empty scan — iterator terminates immediately.
	return redis.NewScanCmdResult(nil, 0, nil)
}

func (m *mockRedisClient) DelBatch(ctx context.Context, keys ...string) *redis.IntCmd {
	cmd := redis.NewIntCmd(ctx)
	if m.failDelBatch {
		cmd.SetErr(errors.New("mock del batch error"))
		return cmd
	}
	var n int64
	for _, k := range keys {
		if _, ok := m.data[k]; ok {
			delete(m.data, k)
			n++
		}
	}
	cmd.SetVal(n)
	return cmd
}

func (m *mockRedisClient) Close() error {
	return nil
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestRedisCacheGet(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["pfx:hello"] = "world"
	rc := NewRedisCacheWithClient(m, "pfx")
	ctx := context.Background()

	val, err := rc.Get(ctx, "hello")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if string(val) != "world" {
		t.Errorf("Get() = %q, want %q", string(val), "world")
	}
}

func TestRedisCacheGetNotFound(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	_, err := rc.Get(ctx, "missing")
	if !errors.Is(err, dal.ErrNotFound) {
		t.Errorf("Get() missing key: got %v, want ErrNotFound", err)
	}
}

func TestRedisCacheGetError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failGet = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	_, err := rc.Get(ctx, "key")
	if err == nil {
		t.Errorf("Get() expected error, got nil")
	}
}

func TestRedisCacheSet(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "pfx")
	ctx := context.Background()

	if err := rc.Set(ctx, "k", []byte("v"), 0); err != nil {
		t.Fatalf("Set() error = %v", err)
	}
	if m.data["pfx:k"] != "v" {
		t.Errorf("Set() stored %q, want %q", m.data["pfx:k"], "v")
	}
}

func TestRedisCacheSetError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failSet = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Set(ctx, "k", []byte("v"), 0); err == nil {
		t.Errorf("Set() expected error, got nil")
	}
}

func TestRedisCacheSetWithTTL(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Set(ctx, "expiring", []byte("data"), 5*time.Minute); err != nil {
		t.Fatalf("Set() with TTL error = %v", err)
	}
	if m.data["expiring"] != "data" {
		t.Errorf("Set() with TTL stored %q, want data", m.data["expiring"])
	}
}

func TestRedisCacheDelete(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["k"] = "v"
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Delete(ctx, "k"); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if _, ok := m.data["k"]; ok {
		t.Errorf("Delete() did not remove key")
	}
}

func TestRedisCacheDeleteError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failDel = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Delete(ctx, "k"); err == nil {
		t.Errorf("Delete() expected error, got nil")
	}
}

func TestRedisCacheDeleteMissingKey(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Delete(ctx, "nothere"); err != nil {
		t.Errorf("Delete() non-existent key error = %v", err)
	}
}

func TestRedisCacheDeleteWithPrefix(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["ns:key"] = "v"
	rc := NewRedisCacheWithClient(m, "ns")
	ctx := context.Background()

	if err := rc.Delete(ctx, "key"); err != nil {
		t.Fatalf("Delete() with prefix error = %v", err)
	}
	if _, ok := m.data["ns:key"]; ok {
		t.Errorf("Delete() with prefix did not remove key")
	}
}

func TestRedisCacheExists(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["k"] = "v"
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	exists, err := rc.Exists(ctx, "k")
	if err != nil {
		t.Fatalf("Exists() error = %v", err)
	}
	if !exists {
		t.Errorf("Exists() = false, want true")
	}

	exists, err = rc.Exists(ctx, "missing")
	if err != nil {
		t.Fatalf("Exists() error = %v", err)
	}
	if exists {
		t.Errorf("Exists() missing = true, want false")
	}
}

func TestRedisCacheExistsError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failExists = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	_, err := rc.Exists(ctx, "k")
	if err == nil {
		t.Errorf("Exists() expected error, got nil")
	}
}

func TestRedisCacheExistsWithPrefix(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["ns:key"] = "v"
	rc := NewRedisCacheWithClient(m, "ns")
	ctx := context.Background()

	exists, err := rc.Exists(ctx, "key")
	if err != nil || !exists {
		t.Errorf("Exists() with prefix: err=%v exists=%v", err, exists)
	}
}

func TestRedisCacheIncrement(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	n, err := rc.Increment(ctx, "counter", 5)
	if err != nil {
		t.Fatalf("Increment() error = %v", err)
	}
	if n != 5 {
		t.Errorf("Increment() = %d, want 5", n)
	}

	n, err = rc.Increment(ctx, "counter", 3)
	if err != nil {
		t.Fatalf("Increment() error = %v", err)
	}
	if n != 8 {
		t.Errorf("Increment() = %d, want 8", n)
	}
}

func TestRedisCacheIncrementError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failIncrBy = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	_, err := rc.Increment(ctx, "counter", 1)
	if err == nil {
		t.Errorf("Increment() expected error, got nil")
	}
}

func TestRedisCacheIncrementWithPrefix(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "ns")
	ctx := context.Background()

	n, err := rc.Increment(ctx, "counter", 10)
	if err != nil || n != 10 {
		t.Errorf("Increment() with prefix: err=%v n=%d", err, n)
	}
}

func TestRedisCacheGetMany(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["k1"] = "v1"
	m.data["k2"] = "v2"
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	result, err := rc.GetMany(ctx, []string{"k1", "k2", "missing"})
	if err != nil {
		t.Fatalf("GetMany() error = %v", err)
	}
	if len(result) != 2 {
		t.Errorf("GetMany() returned %d keys, want 2", len(result))
	}
	if string(result["k1"]) != "v1" {
		t.Errorf("GetMany()[k1] = %q, want v1", string(result["k1"]))
	}
}

func TestRedisCacheGetManyError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failMGet = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	_, err := rc.GetMany(ctx, []string{"k1"})
	if err == nil {
		t.Errorf("GetMany() expected error, got nil")
	}
}

func TestRedisCacheGetManyWithPrefix(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["pfx:k1"] = "v1"
	rc := NewRedisCacheWithClient(m, "pfx")
	ctx := context.Background()

	result, err := rc.GetMany(ctx, []string{"k1"})
	if err != nil {
		t.Fatalf("GetMany() error = %v", err)
	}
	if string(result["k1"]) != "v1" {
		t.Errorf("GetMany()[k1] = %q, want v1", string(result["k1"]))
	}
}

func TestRedisCacheGetManyAllMissing(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	result, err := rc.GetMany(ctx, []string{"miss1", "miss2"})
	if err != nil {
		t.Fatalf("GetMany() error = %v", err)
	}
	if len(result) != 0 {
		t.Errorf("GetMany() all missing: got %d, want 0", len(result))
	}
}

func TestRedisCacheSetMany(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	mapping := map[string][]byte{
		"k1": []byte("v1"),
		"k2": []byte("v2"),
	}
	if err := rc.SetMany(ctx, mapping, 0); err != nil {
		t.Fatalf("SetMany() error = %v", err)
	}
	if m.data["k1"] != "v1" {
		t.Errorf("SetMany() k1 = %q, want v1", m.data["k1"])
	}
	if m.data["k2"] != "v2" {
		t.Errorf("SetMany() k2 = %q, want v2", m.data["k2"])
	}
}

func TestRedisCacheSetManyWithTTL(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "ns")
	ctx := context.Background()

	mapping := map[string][]byte{"k": []byte("v")}
	if err := rc.SetMany(ctx, mapping, 10*time.Minute); err != nil {
		t.Fatalf("SetMany() with TTL error = %v", err)
	}
	if m.data["ns:k"] != "v" {
		t.Errorf("SetMany() with prefix stored at wrong key")
	}
}

func TestRedisCacheSetManyError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failSet = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.SetMany(ctx, map[string][]byte{"k": []byte("v")}, 0); err == nil {
		t.Errorf("SetMany() expected error, got nil")
	}
}

func TestRedisCacheSetManyEmpty(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.SetMany(ctx, map[string][]byte{}, 0); err != nil {
		t.Errorf("SetMany() empty should succeed, got %v", err)
	}
}

func TestRedisCacheFlushDB(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["k1"] = "v1"
	m.data["k2"] = "v2"
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Flush(ctx, ""); err != nil {
		t.Fatalf("Flush() error = %v", err)
	}
	if len(m.data) != 0 {
		t.Errorf("Flush() did not clear data")
	}
}

func TestRedisCacheFlushDBError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failFlush = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Flush(ctx, ""); err == nil {
		t.Errorf("Flush() expected error, got nil")
	}
}

func TestRedisCacheFlushPrefix(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	// Mock Scan returns empty ScanCmd (cursor=0, no keys), iterator terminates immediately.
	if err := rc.Flush(ctx, "myprefix"); err != nil {
		t.Errorf("Flush() with prefix error = %v", err)
	}
}

func TestRedisCacheFlushPrefixWithGlobalPrefix(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "ns")
	ctx := context.Background()

	if err := rc.Flush(ctx, "sub"); err != nil {
		t.Errorf("Flush() prefix+global prefix error = %v", err)
	}
}

func TestRedisCacheFlushPrefixScanError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.failScan = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	// Scan failure surfaces through iterator.Err().
	err := rc.Flush(ctx, "prefix")
	if err == nil {
		t.Errorf("Flush() with scan error: expected error, got nil")
	}
}

func TestRedisCacheFlushPrefixWithKeys(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	// Populate some keys in the mock data and scanResults
	m.data["pfx:k1"] = "v1"
	m.data["pfx:k2"] = "v2"
	m.scanResults = []string{"pfx:k1", "pfx:k2"}
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	if err := rc.Flush(ctx, "pfx"); err != nil {
		t.Fatalf("Flush() with keys error = %v", err)
	}
	if len(m.data) != 0 {
		t.Errorf("Flush() with keys: data not cleared, got %d keys", len(m.data))
	}
}

func TestRedisCacheFlushPrefixDelError(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	m.data["k"] = "v"
	m.scanResults = []string{"k"}
	m.failDel = true
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	err := rc.Flush(ctx, "prefix")
	if err == nil {
		t.Errorf("Flush() with del error: expected error, got nil")
	}
}

func TestRedisCacheClose(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")

	if err := rc.Close(); err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

func TestRedisCacheKeyPrefixNoPrefix(t *testing.T) {
	t.Parallel()
	rc := &RedisCache{cfg: RedisConfig{Prefix: ""}}
	if got := rc.key("mykey"); got != "mykey" {
		t.Errorf("key() without prefix = %q, want %q", got, "mykey")
	}
}

func TestRedisCacheKeyPrefixWithPrefix(t *testing.T) {
	t.Parallel()
	rc := &RedisCache{cfg: RedisConfig{Prefix: "ns"}}
	if got := rc.key("mykey"); got != "ns:mykey" {
		t.Errorf("key() with prefix = %q, want %q", got, "ns:mykey")
	}
}

func TestNewRedisConfigEmptyAddr(t *testing.T) {
	t.Parallel()
	_, err := NewRedisCache(RedisConfig{Addr: ""})
	if err == nil {
		t.Errorf("NewRedisCache() with empty addr should error")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewRedisCache() error type: got %v, want ErrInvalidConfiguration", err)
	}
}

// Round-trip: Set then Get via mock.
func TestRedisCacheSetThenGet(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "app")
	ctx := context.Background()

	if err := rc.Set(ctx, "user:1", []byte(`{"id":1}`), 0); err != nil {
		t.Fatalf("Set() error = %v", err)
	}
	val, err := rc.Get(ctx, "user:1")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if string(val) != `{"id":1}` {
		t.Errorf("Get() = %q, want %q", string(val), `{"id":1}`)
	}
}

// TestRedisCacheSetManyThenGetMany verifies SetMany stores values GetMany can retrieve.
func TestRedisCacheSetManyThenGetMany(t *testing.T) {
	t.Parallel()
	m := newMockRedisClient()
	rc := NewRedisCacheWithClient(m, "")
	ctx := context.Background()

	mapping := map[string][]byte{
		"a": []byte("1"),
		"b": []byte("2"),
		"c": []byte("3"),
	}
	if err := rc.SetMany(ctx, mapping, 0); err != nil {
		t.Fatalf("SetMany() error = %v", err)
	}

	result, err := rc.GetMany(ctx, []string{"a", "b", "c"})
	if err != nil {
		t.Fatalf("GetMany() error = %v", err)
	}
	if len(result) != 3 {
		t.Errorf("GetMany() returned %d, want 3", len(result))
	}
}
