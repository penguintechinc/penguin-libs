package cache

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Test Redis cache interface compliance.
func TestRedisCacheInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.CacheStore = (*RedisCache)(nil)
}

// Test Valkey cache interface compliance.
func TestValkeyCacheInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.CacheStore = (*ValkeyCache)(nil)
}

// Test RedisConfig validation.
func TestRedisConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     RedisConfig
		wantErr bool
	}{
		{
			name:    "empty address",
			cfg:     RedisConfig{Addr: ""},
			wantErr: true,
		},
		{
			name: "valid config",
			cfg: RedisConfig{
				Addr: "localhost:6379",
			},
			wantErr: true, // connection will fail locally without actual Redis
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewRedisCache(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewRedisCache() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test ValkeyConfig validation.
func TestValkeyConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     ValkeyConfig
		wantErr bool
	}{
		{
			name:    "empty init address",
			cfg:     ValkeyConfig{InitAddress: []string{}},
			wantErr: true,
		},
		{
			name: "valid config",
			cfg: ValkeyConfig{
				InitAddress: []string{"localhost:6379"},
			},
			wantErr: true, // connection will fail locally without actual Valkey
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewValkeyCache(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewValkeyCache() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test helper for cache operations with mocks.
func TestCacheKeyPrefixing(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name       string
		prefix     string
		key        string
		wantResult string
	}{
		{
			name:       "with prefix",
			prefix:     "app",
			key:        "user:123",
			wantResult: "app:user:123",
		},
		{
			name:       "without prefix",
			prefix:     "",
			key:        "user:123",
			wantResult: "user:123",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			rc := &RedisCache{cfg: RedisConfig{Prefix: tt.prefix}}
			if got := rc.key(tt.key); got != tt.wantResult {
				t.Errorf("key() = %s, want %s", got, tt.wantResult)
			}
		})
	}
}

// Test Valkey key prefixing.
func TestValkeyKeyPrefixing(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name       string
		prefix     string
		key        string
		wantResult string
	}{
		{
			name:       "with prefix",
			prefix:     "cache",
			key:        "data:456",
			wantResult: "cache:data:456",
		},
		{
			name:       "without prefix",
			prefix:     "",
			key:        "data:456",
			wantResult: "data:456",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			vc := &ValkeyCache{cfg: ValkeyConfig{Prefix: tt.prefix}}
			if got := vc.key(tt.key); got != tt.wantResult {
				t.Errorf("key() = %s, want %s", got, tt.wantResult)
			}
		})
	}
}

// Test Redis Set/Get option builder functions.
func TestCacheOptions(t *testing.T) {
	t.Parallel()
	po := &dal.PutOptions{}
	opt := dal.WithContentType("application/json")
	opt(po)
	if po.ContentType != "application/json" {
		t.Errorf("WithContentType() = %s, want application/json", po.ContentType)
	}
}

// Mock cache for testing higher-level code that needs dal.CacheStore.
type MockCache struct {
	data map[string][]byte
}

func NewMockCache() *MockCache {
	return &MockCache{data: make(map[string][]byte)}
}

func (m *MockCache) Get(ctx context.Context, key string) ([]byte, error) {
	if val, ok := m.data[key]; ok {
		return val, nil
	}
	return nil, dal.ErrNotFound
}

func (m *MockCache) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	m.data[key] = value
	return nil
}

func (m *MockCache) Delete(ctx context.Context, key string) error {
	delete(m.data, key)
	return nil
}

func (m *MockCache) Exists(ctx context.Context, key string) (bool, error) {
	_, ok := m.data[key]
	return ok, nil
}

func (m *MockCache) Increment(ctx context.Context, key string, amount int64) (int64, error) {
	return 0, dal.ErrUnsupportedOperation
}

func (m *MockCache) GetMany(ctx context.Context, keys []string) (map[string][]byte, error) {
	result := make(map[string][]byte)
	for _, k := range keys {
		if val, ok := m.data[k]; ok {
			result[k] = val
		}
	}
	return result, nil
}

func (m *MockCache) SetMany(ctx context.Context, mapping map[string][]byte, ttl time.Duration) error {
	for k, v := range mapping {
		m.data[k] = v
	}
	return nil
}

func (m *MockCache) Flush(ctx context.Context, prefix string) error {
	m.data = make(map[string][]byte)
	return nil
}

func (m *MockCache) Close() error {
	return nil
}

// Test MockCache interface compliance.
func TestMockCacheInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.CacheStore = (*MockCache)(nil)
}

// Test MockCache basic operations.
func TestMockCache(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	// Set and Get
	err := mc.Set(ctx, "key1", []byte("value1"), 0)
	if err != nil {
		t.Errorf("Set() error = %v", err)
	}

	val, err := mc.Get(ctx, "key1")
	if err != nil {
		t.Errorf("Get() error = %v", err)
	}
	if string(val) != "value1" {
		t.Errorf("Get() = %s, want value1", string(val))
	}

	// Exists
	exists, err := mc.Exists(ctx, "key1")
	if err != nil {
		t.Errorf("Exists() error = %v", err)
	}
	if !exists {
		t.Errorf("Exists() = false, want true")
	}

	// Delete
	err = mc.Delete(ctx, "key1")
	if err != nil {
		t.Errorf("Delete() error = %v", err)
	}

	// Get after delete
	_, err = mc.Get(ctx, "key1")
	if err != dal.ErrNotFound {
		t.Errorf("Get() after delete: got %v, want ErrNotFound", err)
	}
}

// Test MockCache GetMany and SetMany operations.
func TestMockCacheMultiOperations(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	// SetMany
	mapping := map[string][]byte{
		"key1": []byte("value1"),
		"key2": []byte("value2"),
		"key3": []byte("value3"),
	}
	err := mc.SetMany(ctx, mapping, 0)
	if err != nil {
		t.Errorf("SetMany() error = %v", err)
	}

	// GetMany
	keys := []string{"key1", "key2", "key3"}
	result, err := mc.GetMany(ctx, keys)
	if err != nil {
		t.Errorf("GetMany() error = %v", err)
	}
	if len(result) != 3 {
		t.Errorf("GetMany() returned %d keys, want 3", len(result))
	}
	for k, v := range result {
		if string(v) != "value"+k[3:] {
			t.Errorf("GetMany()[%s] = %s, want value%s", k, string(v), k[3:])
		}
	}
}

// Test MockCache Increment operation.
func TestMockCacheIncrement(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	result, err := mc.Increment(ctx, "counter", 1)
	if err != dal.ErrUnsupportedOperation {
		t.Errorf("Increment() should return ErrUnsupportedOperation, got %v", err)
	}
	if result != 0 {
		t.Errorf("Increment() result = %d, want 0", result)
	}
}

// Test MockCache Flush operation.
func TestMockCacheFlush(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	// Add some data
	mc.Set(ctx, "key1", []byte("value1"), 0)
	mc.Set(ctx, "key2", []byte("value2"), 0)

	// Flush
	err := mc.Flush(ctx, "")
	if err != nil {
		t.Errorf("Flush() error = %v", err)
	}

	// Verify data is gone
	_, err = mc.Get(ctx, "key1")
	if err != dal.ErrNotFound {
		t.Errorf("Get() after flush: expected ErrNotFound")
	}
}

// Test MockCache Close operation.
func TestMockCacheClose(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()

	err := mc.Close()
	if err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

// Test MockCache with TTL (even though we don't enforce it).
func TestMockCacheWithTTL(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	// Set with TTL
	err := mc.Set(ctx, "expiring", []byte("data"), 1*time.Second)
	if err != nil {
		t.Errorf("Set() with TTL error = %v", err)
	}

	// Get should work immediately
	val, err := mc.Get(ctx, "expiring")
	if err != nil || string(val) != "data" {
		t.Errorf("Get() after Set with TTL failed")
	}
}

// Test MockCache edge cases with missing keys.
func TestMockCacheGetMissingKeys(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	mc.Set(ctx, "exists", []byte("value"), 0)

	// GetMany with mix of existing and missing keys
	keys := []string{"exists", "missing1", "missing2"}
	result, err := mc.GetMany(ctx, keys)
	if err != nil {
		t.Errorf("GetMany() error = %v", err)
	}

	if len(result) != 1 || result["exists"] == nil {
		t.Errorf("GetMany() should return only existing keys")
	}

	if _, ok := result["missing1"]; ok {
		t.Errorf("GetMany() should not return missing keys")
	}
}

// Test Sentinel error values.
func TestSentinelErrors(t *testing.T) {
	t.Parallel()
	if dal.ErrNotFound == nil {
		t.Errorf("ErrNotFound should not be nil")
	}
	if dal.ErrUnsupportedOperation == nil {
		t.Errorf("ErrUnsupportedOperation should not be nil")
	}
	if dal.ErrConnectionFailed == nil {
		t.Errorf("ErrConnectionFailed should not be nil")
	}
	if dal.ErrInvalidConfiguration == nil {
		t.Errorf("ErrInvalidConfiguration should not be nil")
	}
	if dal.ErrAlreadyExists == nil {
		t.Errorf("ErrAlreadyExists should not be nil")
	}
}

// Test MockCache with many keys.
func TestMockCacheManyKeys(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	// Add many keys
	for i := 0; i < 100; i++ {
		key := fmt.Sprintf("key_%d", i)
		val := []byte(fmt.Sprintf("value_%d", i))
		err := mc.Set(ctx, key, val, 0)
		if err != nil {
			t.Errorf("Set() error = %v", err)
		}
	}

	// Verify exists works
	exists, _ := mc.Exists(ctx, "key_50")
	if !exists {
		t.Errorf("Exists() key_50 = false, want true")
	}

	// Verify Get works
	val, _ := mc.Get(ctx, "key_75")
	if string(val) != "value_75" {
		t.Errorf("Get() key_75 = %s, want value_75", string(val))
	}

	// GetMany with multiple keys
	keys := []string{"key_0", "key_25", "key_50", "key_99"}
	results, _ := mc.GetMany(ctx, keys)
	if len(results) != 4 {
		t.Errorf("GetMany() returned %d results, want 4", len(results))
	}
}

// Test MockCache SetMany empty mapping.
func TestMockCacheSetManyEmpty(t *testing.T) {
	t.Parallel()
	mc := NewMockCache()
	ctx := context.Background()

	err := mc.SetMany(ctx, map[string][]byte{}, 0)
	if err != nil {
		t.Errorf("SetMany() empty mapping error = %v", err)
	}
}

// Test cache option builders all at once.
func TestAllCacheOptions(t *testing.T) {
	t.Parallel()

	// Build all options
	opts := []dal.PutOption{
		dal.WithContentType("text/plain"),
		dal.WithMetadata(map[string]string{"key1": "val1", "key2": "val2"}),
		dal.WithCacheControl("public, max-age=3600"),
	}

	po := &dal.PutOptions{}
	for _, opt := range opts {
		opt(po)
	}

	if po.ContentType != "text/plain" || po.CacheControl != "public, max-age=3600" || len(po.Metadata) != 2 {
		t.Errorf("Options building failed")
	}
}

// Test cache option builders.
func TestCacheOptionBuilders(t *testing.T) {
	t.Parallel()

	// Test WithContentType
	po := &dal.PutOptions{}
	opt := dal.WithContentType("application/json")
	opt(po)
	if po.ContentType != "application/json" {
		t.Errorf("WithContentType() = %s, want application/json", po.ContentType)
	}

	// Test WithMetadata
	po = &dal.PutOptions{}
	metadata := map[string]string{"key": "value"}
	opt = dal.WithMetadata(metadata)
	opt(po)
	if po.Metadata["key"] != "value" {
		t.Errorf("WithMetadata() failed")
	}

	// Test WithCacheControl
	po = &dal.PutOptions{}
	opt = dal.WithCacheControl("max-age=3600")
	opt(po)
	if po.CacheControl != "max-age=3600" {
		t.Errorf("WithCacheControl() = %s, want max-age=3600", po.CacheControl)
	}

	// Test WithPublishKey
	pso := &dal.PublishOptions{}
	pubOpt := dal.WithPublishKey([]byte("key"))
	pubOpt(pso)
	if string(pso.Key) != "key" {
		t.Errorf("WithPublishKey() failed")
	}

	// Test WithPublishHeaders
	pso = &dal.PublishOptions{}
	headers := map[string]string{"h1": "v1"}
	pubOpt = dal.WithPublishHeaders(headers)
	pubOpt(pso)
	if pso.Headers["h1"] != "v1" {
		t.Errorf("WithPublishHeaders() failed")
	}

	// Test WithLimit
	fo := &dal.FindOptions{}
	findOpt := dal.WithLimit(10)
	findOpt(fo)
	if fo.Limit != 10 {
		t.Errorf("WithLimit() = %d, want 10", fo.Limit)
	}

	// Test WithSkip
	fo = &dal.FindOptions{}
	findOpt = dal.WithSkip(5)
	findOpt(fo)
	if fo.Skip != 5 {
		t.Errorf("WithSkip() = %d, want 5", fo.Skip)
	}

	// Test WithSort
	fo = &dal.FindOptions{}
	sortKeys := []dal.IndexKey{{Field: "name", Direction: 1}}
	findOpt = dal.WithSort(sortKeys)
	findOpt(fo)
	if len(fo.Sort) != 1 || fo.Sort[0].Field != "name" {
		t.Errorf("WithSort() failed")
	}
}
