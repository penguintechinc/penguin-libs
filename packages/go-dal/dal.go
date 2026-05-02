// Package dal provides a universal data abstraction layer for databases,
// object storage, caching, message streaming, and document stores.
package dal

import (
	"context"
	"errors"
	"time"
)

// StorageStore abstracts object/file storage (S3, NFS, iSCSI).
type StorageStore interface {
	Put(ctx context.Context, key string, data []byte, opts ...PutOption) error
	Get(ctx context.Context, key string) ([]byte, error)
	Delete(ctx context.Context, key string) error
	Exists(ctx context.Context, key string) (bool, error)
	List(ctx context.Context, prefix string) ([]string, error)
	GetURL(ctx context.Context, key string, expiresIn time.Duration) (string, error)
	Close() error
}

// CacheStore abstracts key-value caches (Redis, Valkey, Memcache).
type CacheStore interface {
	Get(ctx context.Context, key string) ([]byte, error)
	Set(ctx context.Context, key string, value []byte, ttl time.Duration) error
	Delete(ctx context.Context, key string) error
	Exists(ctx context.Context, key string) (bool, error)
	Increment(ctx context.Context, key string, amount int64) (int64, error)
	GetMany(ctx context.Context, keys []string) (map[string][]byte, error)
	SetMany(ctx context.Context, mapping map[string][]byte, ttl time.Duration) error
	Flush(ctx context.Context, prefix string) error
	Close() error
}

// StreamProducer publishes messages to a streaming backend.
type StreamProducer interface {
	Publish(ctx context.Context, topic string, message []byte, opts ...PublishOption) error
	Flush(ctx context.Context, timeout time.Duration) error
	Close() error
}

// StreamConsumer receives messages from a streaming backend.
type StreamConsumer interface {
	Subscribe(topics []string) error
	Poll(ctx context.Context, timeout time.Duration) ([]StreamMessage, error)
	Commit(ctx context.Context) error
	Close() error
}

// DocumentStore abstracts document databases (MongoDB).
type DocumentStore interface {
	InsertOne(ctx context.Context, collection string, document interface{}) (string, error)
	FindOne(ctx context.Context, collection string, filter interface{}) (map[string]interface{}, error)
	Find(ctx context.Context, collection string, filter interface{}, opts ...FindOption) ([]map[string]interface{}, error)
	UpdateOne(ctx context.Context, collection string, filter, update interface{}) (int64, error)
	DeleteOne(ctx context.Context, collection string, filter interface{}) (int64, error)
	Count(ctx context.Context, collection string, filter interface{}) (int64, error)
	CreateIndex(ctx context.Context, collection string, keys []IndexKey, unique bool) error
	Close(ctx context.Context) error
}

// StreamMessage represents a message received from a stream.
type StreamMessage struct {
	Topic     string
	Partition int32
	Offset    int64
	Key       []byte
	Value     []byte
	Headers   map[string]string
	Timestamp time.Time
}

// IndexKey for document store index creation.
type IndexKey struct {
	Field     string
	Direction int // 1 = ascending, -1 = descending
}

// Option types for fluent API.
type PutOption func(*PutOptions)
type PublishOption func(*PublishOptions)
type FindOption func(*FindOptions)

// PutOptions holds options for Put operations.
type PutOptions struct {
	ContentType  string
	Metadata     map[string]string
	CacheControl string
}

// PublishOptions holds options for Publish operations.
type PublishOptions struct {
	Key     []byte
	Headers map[string]string
}

// FindOptions holds options for Find operations.
type FindOptions struct {
	Limit int64
	Skip  int64
	Sort  []IndexKey
}

// Sentinel errors.
var (
	ErrNotFound              = errors.New("dal: key not found")
	ErrUnsupportedOperation  = errors.New("dal: unsupported operation")
	ErrConnectionFailed      = errors.New("dal: connection failed")
	ErrInvalidConfiguration  = errors.New("dal: invalid configuration")
	ErrAlreadyExists         = errors.New("dal: already exists")
)

// WithContentType sets the content type for storage puts.
func WithContentType(ct string) PutOption {
	return func(po *PutOptions) {
		po.ContentType = ct
	}
}

// WithMetadata sets custom metadata for storage puts.
func WithMetadata(m map[string]string) PutOption {
	return func(po *PutOptions) {
		po.Metadata = m
	}
}

// WithCacheControl sets cache control header for storage puts.
func WithCacheControl(cc string) PutOption {
	return func(po *PutOptions) {
		po.CacheControl = cc
	}
}

// WithPublishKey sets the message key for publish operations.
func WithPublishKey(key []byte) PublishOption {
	return func(pso *PublishOptions) {
		pso.Key = key
	}
}

// WithPublishHeaders sets headers for publish operations.
func WithPublishHeaders(headers map[string]string) PublishOption {
	return func(pso *PublishOptions) {
		pso.Headers = headers
	}
}

// WithLimit sets the result limit for find operations.
func WithLimit(n int64) FindOption {
	return func(fo *FindOptions) {
		fo.Limit = n
	}
}

// WithSkip sets the result skip/offset for find operations.
func WithSkip(n int64) FindOption {
	return func(fo *FindOptions) {
		fo.Skip = n
	}
}

// WithSort sets sort order for find operations.
func WithSort(keys []IndexKey) FindOption {
	return func(fo *FindOptions) {
		fo.Sort = keys
	}
}
