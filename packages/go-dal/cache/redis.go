package cache

import (
	"context"
	"fmt"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"github.com/redis/go-redis/v9"
)

// redisClient is the subset of redis.Cmdable used by RedisCache.
// Defining this interface enables mock-based unit testing.
type redisClient interface {
	Get(ctx context.Context, key string) *redis.StringCmd
	Set(ctx context.Context, key string, value interface{}, expiration time.Duration) *redis.StatusCmd
	Del(ctx context.Context, keys ...string) *redis.IntCmd
	Exists(ctx context.Context, keys ...string) *redis.IntCmd
	IncrBy(ctx context.Context, key string, value int64) *redis.IntCmd
	MGet(ctx context.Context, keys ...string) *redis.SliceCmd
	FlushDB(ctx context.Context) *redis.StatusCmd
	Scan(ctx context.Context, cursor uint64, match string, count int64) *redis.ScanCmd
	Close() error
}

// RedisConfig configures a Redis cache backend.
type RedisConfig struct {
	Addr         string
	Password     string
	DB           int
	Prefix       string
	PoolSize     int
	DialTimeout  time.Duration
	ReadTimeout  time.Duration
	WriteTimeout time.Duration
}

// RedisCache implements dal.CacheStore for Redis.
type RedisCache struct {
	cfg    RedisConfig
	client redisClient
}

// NewRedisCache creates a new Redis cache backend.
func NewRedisCache(cfg RedisConfig) (*RedisCache, error) {
	if cfg.Addr == "" {
		return nil, fmt.Errorf("go-dal: redis: %w: address required", dal.ErrInvalidConfiguration)
	}

	if cfg.PoolSize == 0 {
		cfg.PoolSize = 10
	}
	if cfg.DialTimeout == 0 {
		cfg.DialTimeout = 5 * time.Second
	}
	if cfg.ReadTimeout == 0 {
		cfg.ReadTimeout = 3 * time.Second
	}
	if cfg.WriteTimeout == 0 {
		cfg.WriteTimeout = 3 * time.Second
	}

	opts := &redis.Options{
		Addr:         cfg.Addr,
		Password:     cfg.Password,
		DB:           cfg.DB,
		PoolSize:     cfg.PoolSize,
		DialTimeout:  cfg.DialTimeout,
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
	}

	client := redis.NewClient(opts)

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), cfg.DialTimeout)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("go-dal: redis: connect: %w", err)
	}

	return &RedisCache{
		cfg:    cfg,
		client: client,
	}, nil
}

// NewRedisCacheWithClient creates a RedisCache using an injected client (for testing).
func NewRedisCacheWithClient(client redisClient, prefix string) *RedisCache {
	return &RedisCache{
		cfg:    RedisConfig{Prefix: prefix},
		client: client,
	}
}

func (r *RedisCache) key(k string) string {
	if r.cfg.Prefix != "" {
		return r.cfg.Prefix + ":" + k
	}
	return k
}

// Get retrieves a value from Redis.
func (r *RedisCache) Get(ctx context.Context, key string) ([]byte, error) {
	val, err := r.client.Get(ctx, r.key(key)).Bytes()
	if err == redis.Nil {
		return nil, fmt.Errorf("go-dal: redis: get: %w", dal.ErrNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("go-dal: redis: get: %w", err)
	}

	return val, nil
}

// Set stores a value in Redis with optional TTL.
func (r *RedisCache) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	if err := r.client.Set(ctx, r.key(key), value, ttl).Err(); err != nil {
		return fmt.Errorf("go-dal: redis: set: %w", err)
	}

	return nil
}

// Delete removes a key from Redis.
func (r *RedisCache) Delete(ctx context.Context, key string) error {
	if err := r.client.Del(ctx, r.key(key)).Err(); err != nil {
		return fmt.Errorf("go-dal: redis: delete: %w", err)
	}

	return nil
}

// Exists checks if a key exists in Redis.
func (r *RedisCache) Exists(ctx context.Context, key string) (bool, error) {
	n, err := r.client.Exists(ctx, r.key(key)).Result()
	if err != nil {
		return false, fmt.Errorf("go-dal: redis: exists: %w", err)
	}

	return n > 0, nil
}

// Increment adds an amount to an integer value in Redis.
func (r *RedisCache) Increment(ctx context.Context, key string, amount int64) (int64, error) {
	val, err := r.client.IncrBy(ctx, r.key(key), amount).Result()
	if err != nil {
		return 0, fmt.Errorf("go-dal: redis: incr: %w", err)
	}

	return val, nil
}

// GetMany retrieves multiple values from Redis.
func (r *RedisCache) GetMany(ctx context.Context, keys []string) (map[string][]byte, error) {
	prefixedKeys := make([]string, len(keys))
	for i, k := range keys {
		prefixedKeys[i] = r.key(k)
	}

	vals, err := r.client.MGet(ctx, prefixedKeys...).Result()
	if err != nil {
		return nil, fmt.Errorf("go-dal: redis: mget: %w", err)
	}

	result := make(map[string][]byte)
	for i, val := range vals {
		if val != nil {
			result[keys[i]] = []byte(val.(string))
		}
	}

	return result, nil
}

// SetMany stores multiple key-value pairs in Redis.
// Each key is set individually to avoid the need for a pipeline interface.
func (r *RedisCache) SetMany(ctx context.Context, mapping map[string][]byte, ttl time.Duration) error {
	for k, v := range mapping {
		if err := r.client.Set(ctx, r.key(k), v, ttl).Err(); err != nil {
			return fmt.Errorf("go-dal: redis: mset: %w", err)
		}
	}
	return nil
}

// Flush removes all keys matching a prefix.
func (r *RedisCache) Flush(ctx context.Context, prefix string) error {
	if prefix == "" {
		// Flush entire DB
		if err := r.client.FlushDB(ctx).Err(); err != nil {
			return fmt.Errorf("go-dal: redis: flush db: %w", err)
		}
		return nil
	}

	// Scan and collect keys, then delete in batches.
	pattern := r.key(prefix) + "*"
	iter := r.client.Scan(ctx, 0, pattern, 100).Iterator()

	var batch []string
	for iter.Next(ctx) {
		batch = append(batch, iter.Val())
		if len(batch) >= 1000 {
			if err := r.client.Del(ctx, batch...).Err(); err != nil {
				return fmt.Errorf("go-dal: redis: flush delete: %w", err)
			}
			batch = batch[:0]
		}
	}

	if len(batch) > 0 {
		if err := r.client.Del(ctx, batch...).Err(); err != nil {
			return fmt.Errorf("go-dal: redis: flush delete: %w", err)
		}
	}

	if err := iter.Err(); err != nil {
		return fmt.Errorf("go-dal: redis: flush iter: %w", err)
	}

	return nil
}

// Close closes the Redis connection.
func (r *RedisCache) Close() error {
	return r.client.Close()
}
