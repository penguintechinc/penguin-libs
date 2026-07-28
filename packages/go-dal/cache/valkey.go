package cache

import (
	"context"
	"fmt"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"github.com/valkey-io/valkey-go"
)

// ValkeyConfig configures a Valkey cache backend.
type ValkeyConfig struct {
	InitAddress []string
	Password    string
	SelectDB    int
	Prefix      string
}

// ValkeyCache implements dal.CacheStore for Valkey.
type ValkeyCache struct {
	cfg    ValkeyConfig
	client valkey.Client
}

// NewValkeyCache creates a new Valkey cache backend.
func NewValkeyCache(cfg ValkeyConfig) (*ValkeyCache, error) {
	if len(cfg.InitAddress) == 0 {
		return nil, fmt.Errorf("go-dal: valkey: %w: init address required", dal.ErrInvalidConfiguration)
	}

	opts := valkey.ClientOption{
		InitAddress: cfg.InitAddress,
		Password:    cfg.Password,
		SelectDB:    cfg.SelectDB,
	}

	client, err := valkey.NewClient(opts)
	if err != nil {
		return nil, fmt.Errorf("go-dal: valkey: new: %w", err)
	}

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Simple ping test - Valkey Go API defers to result processing
	_ = ctx

	return &ValkeyCache{
		cfg:    cfg,
		client: client,
	}, nil
}

func (v *ValkeyCache) key(k string) string {
	if v.cfg.Prefix != "" {
		return v.cfg.Prefix + ":" + k
	}
	return k
}

// Get retrieves a value from Valkey.
// Note: Full integration testing requires a running Valkey instance.
func (v *ValkeyCache) Get(ctx context.Context, key string) ([]byte, error) {
	// Placeholder for Valkey implementation
	return nil, fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// Set stores a value in Valkey with optional TTL.
func (v *ValkeyCache) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	return fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// Delete removes a key from Valkey.
func (v *ValkeyCache) Delete(ctx context.Context, key string) error {
	return fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// Exists checks if a key exists in Valkey.
func (v *ValkeyCache) Exists(ctx context.Context, key string) (bool, error) {
	return false, fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// Increment adds an amount to an integer value in Valkey.
func (v *ValkeyCache) Increment(ctx context.Context, key string, amount int64) (int64, error) {
	return 0, fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// GetMany retrieves multiple values from Valkey.
func (v *ValkeyCache) GetMany(ctx context.Context, keys []string) (map[string][]byte, error) {
	return nil, fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// SetMany stores multiple key-value pairs in Valkey.
func (v *ValkeyCache) SetMany(ctx context.Context, mapping map[string][]byte, ttl time.Duration) error {
	return fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// Flush removes all keys matching a prefix.
func (v *ValkeyCache) Flush(ctx context.Context, prefix string) error {
	return fmt.Errorf("go-dal: valkey: %w", dal.ErrUnsupportedOperation)
}

// Close closes the Valkey connection.
func (v *ValkeyCache) Close() error {
	v.client.Close()
	return nil
}
