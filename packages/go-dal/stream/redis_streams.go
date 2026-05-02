package stream

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"github.com/redis/go-redis/v9"
)

// redisStreamClient is the subset of redis.Cmdable used by Redis stream implementations.
type redisStreamClient interface {
	XAdd(ctx context.Context, a *redis.XAddArgs) *redis.StringCmd
	XReadGroup(ctx context.Context, a *redis.XReadGroupArgs) *redis.XStreamSliceCmd
	XGroupCreateMkStream(ctx context.Context, stream, group, start string) *redis.StatusCmd
	XInfoStream(ctx context.Context, key string) *redis.XInfoStreamCmd
	XAck(ctx context.Context, stream, group string, ids ...string) *redis.IntCmd
	Close() error
}

// RedisStreamConfig configures a Redis Streams backend.
type RedisStreamConfig struct {
	Addr         string
	Password     string
	DB           int
	GroupID      string
	ConsumerName string
	BatchSize    int64
}

// RedisStreamProducer implements dal.StreamProducer using Redis Streams.
type RedisStreamProducer struct {
	client redisStreamClient
}

// NewRedisStreamProducer creates a new Redis Streams producer.
func NewRedisStreamProducer(cfg RedisStreamConfig) (*RedisStreamProducer, error) {
	if cfg.Addr == "" {
		return nil, fmt.Errorf("go-dal: redis-stream: %w: address required", dal.ErrInvalidConfiguration)
	}

	opts := &redis.Options{
		Addr:         cfg.Addr,
		Password:     cfg.Password,
		DB:           cfg.DB,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  3 * time.Second,
		WriteTimeout: 3 * time.Second,
	}

	client := redis.NewClient(opts)

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("go-dal: redis-stream: connect: %w", err)
	}

	return &RedisStreamProducer{client: client}, nil
}

// NewRedisStreamProducerWithClient creates a producer using an injected client (for testing).
func NewRedisStreamProducerWithClient(client redisStreamClient) *RedisStreamProducer {
	return &RedisStreamProducer{client: client}
}

// Publish sends a message to a Redis Stream.
func (r *RedisStreamProducer) Publish(ctx context.Context, topic string, message []byte, opts ...dal.PublishOption) error {
	po := &dal.PublishOptions{}
	for _, opt := range opts {
		opt(po)
	}

	fields := map[string]interface{}{
		"value": message,
	}

	if len(po.Key) > 0 {
		fields["key"] = po.Key
	}

	if len(po.Headers) > 0 {
		headersJSON, _ := json.Marshal(po.Headers)
		fields["headers"] = headersJSON
	}

	if err := r.client.XAdd(ctx, &redis.XAddArgs{
		Stream: topic,
		Values: fields,
	}).Err(); err != nil {
		return fmt.Errorf("go-dal: redis-stream: publish: %w", err)
	}

	return nil
}

// Flush is a no-op for Redis Streams (immediate persistence).
func (r *RedisStreamProducer) Flush(ctx context.Context, timeout time.Duration) error {
	return nil
}

// Close closes the Redis client.
func (r *RedisStreamProducer) Close() error {
	return r.client.Close()
}

// RedisStreamConsumer implements dal.StreamConsumer using Redis Streams.
type RedisStreamConsumer struct {
	client     redisStreamClient
	cfg        RedisStreamConfig
	topics     []string
	pendingIDs map[string]string // topic → last ID
}

// NewRedisStreamConsumer creates a new Redis Streams consumer.
func NewRedisStreamConsumer(cfg RedisStreamConfig) (*RedisStreamConsumer, error) {
	if cfg.Addr == "" {
		return nil, fmt.Errorf("go-dal: redis-stream: %w: address required", dal.ErrInvalidConfiguration)
	}
	if cfg.GroupID == "" {
		return nil, fmt.Errorf("go-dal: redis-stream: %w: group id required", dal.ErrInvalidConfiguration)
	}
	if cfg.ConsumerName == "" {
		cfg.ConsumerName = "consumer-1"
	}
	if cfg.BatchSize == 0 {
		cfg.BatchSize = 10
	}

	opts := &redis.Options{
		Addr:         cfg.Addr,
		Password:     cfg.Password,
		DB:           cfg.DB,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  3 * time.Second,
		WriteTimeout: 3 * time.Second,
	}

	client := redis.NewClient(opts)

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("go-dal: redis-stream: connect: %w", err)
	}

	return &RedisStreamConsumer{
		client:     client,
		cfg:        cfg,
		pendingIDs: make(map[string]string),
	}, nil
}

// NewRedisStreamConsumerWithClient creates a consumer using an injected client (for testing).
func NewRedisStreamConsumerWithClient(client redisStreamClient, cfg RedisStreamConfig) *RedisStreamConsumer {
	if cfg.ConsumerName == "" {
		cfg.ConsumerName = "consumer-1"
	}
	if cfg.BatchSize == 0 {
		cfg.BatchSize = 10
	}
	return &RedisStreamConsumer{
		client:     client,
		cfg:        cfg,
		pendingIDs: make(map[string]string),
	}
}

// Subscribe subscribes to a list of topics (streams).
func (r *RedisStreamConsumer) Subscribe(topics []string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	for _, topic := range topics {
		// Create consumer group if it doesn't exist
		if err := r.client.XGroupCreateMkStream(ctx, topic, r.cfg.GroupID, "0").Err(); err != nil {
			// Group might already exist; check with XINFO
			if _, err := r.client.XInfoStream(ctx, topic).Result(); err != nil {
				return fmt.Errorf("go-dal: redis-stream: subscribe create group: %w", err)
			}
		}
	}

	r.topics = topics
	return nil
}

// Poll polls for messages from subscribed topics.
func (r *RedisStreamConsumer) Poll(ctx context.Context, timeout time.Duration) ([]dal.StreamMessage, error) {
	if len(r.topics) == 0 {
		return nil, fmt.Errorf("go-dal: redis-stream: %w: no topics subscribed", dal.ErrInvalidConfiguration)
	}

	// Build XREADGROUP arguments
	streams := make([]string, 0, len(r.topics)*2)
	for _, topic := range r.topics {
		streams = append(streams, topic, ">") // ">" = new messages only
	}

	results, err := r.client.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    r.cfg.GroupID,
		Consumer: r.cfg.ConsumerName,
		Streams:  streams,
		Count:    r.cfg.BatchSize,
		Block:    timeout,
	}).Result()

	if err != nil && err != redis.Nil {
		return nil, fmt.Errorf("go-dal: redis-stream: poll: %w", err)
	}

	var messages []dal.StreamMessage

	for _, result := range results {
		topic := result.Stream
		for _, msg := range result.Messages {
			// Parse message fields
			msgValue, _ := msg.Values["value"].(string)
			msgKey, _ := msg.Values["key"].(string)

			var headers map[string]string
			if headerJSON, ok := msg.Values["headers"].(string); ok {
				_ = json.Unmarshal([]byte(headerJSON), &headers)
			}
			if headers == nil {
				headers = make(map[string]string)
			}

			streamMsg := dal.StreamMessage{
				Topic:     topic,
				Partition: 0,
				Offset:    0,
				Key:       []byte(msgKey),
				Value:     []byte(msgValue),
				Headers:   headers,
				Timestamp: time.Now(),
			}

			messages = append(messages, streamMsg)
			r.pendingIDs[topic] = msg.ID
		}
	}

	return messages, nil
}

// Commit acknowledges pending messages.
func (r *RedisStreamConsumer) Commit(ctx context.Context) error {
	for topic, msgID := range r.pendingIDs {
		if err := r.client.XAck(ctx, topic, r.cfg.GroupID, msgID).Err(); err != nil {
			return fmt.Errorf("go-dal: redis-stream: commit: %w", err)
		}
	}

	r.pendingIDs = make(map[string]string)
	return nil
}

// Close closes the Redis client.
func (r *RedisStreamConsumer) Close() error {
	return r.client.Close()
}
