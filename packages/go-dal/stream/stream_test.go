package stream

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Test Kafka producer interface compliance.
func TestKafkaProducerInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StreamProducer = (*KafkaProducer)(nil)
}

// Test Kafka consumer interface compliance.
func TestKafkaConsumerInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StreamConsumer = (*KafkaConsumer)(nil)
}

// Test Redis Streams producer interface compliance.
func TestRedisStreamProducerInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StreamProducer = (*RedisStreamProducer)(nil)
}

// Test Redis Streams consumer interface compliance.
func TestRedisStreamConsumerInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StreamConsumer = (*RedisStreamConsumer)(nil)
}

// Test KafkaConfig validation.
func TestKafkaProducerConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     KafkaConfig
		wantErr bool
	}{
		{
			name:    "empty bootstrap servers",
			cfg:     KafkaConfig{BootstrapServers: ""},
			wantErr: true,
		},
		{
			name: "valid config (may connect lazily)",
			cfg: KafkaConfig{
				BootstrapServers: "localhost:9092",
			},
			wantErr: false, // Kafka producer is lazily connected
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewKafkaProducer(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewKafkaProducer() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test KafkaConsumer config validation.
func TestKafkaConsumerConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     KafkaConfig
		wantErr bool
	}{
		{
			name: "empty bootstrap servers",
			cfg: KafkaConfig{
				BootstrapServers: "",
				GroupID:          "test-group",
			},
			wantErr: true,
		},
		{
			name: "empty group id",
			cfg: KafkaConfig{
				BootstrapServers: "localhost:9092",
				GroupID:          "",
			},
			wantErr: true,
		},
		{
			name: "valid config (may connect lazily)",
			cfg: KafkaConfig{
				BootstrapServers: "localhost:9092",
				GroupID:          "test-group",
			},
			wantErr: false, // Kafka consumer is lazily connected
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewKafkaConsumer(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewKafkaConsumer() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test RedisStreamConfig validation.
func TestRedisStreamProducerConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     RedisStreamConfig
		wantErr bool
	}{
		{
			name:    "empty address",
			cfg:     RedisStreamConfig{Addr: ""},
			wantErr: true,
		},
		{
			name: "valid config",
			cfg: RedisStreamConfig{
				Addr: "localhost:6379",
			},
			wantErr: true, // connection will fail locally without actual Redis
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewRedisStreamProducer(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewRedisStreamProducer() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test RedisStreamConsumer config validation.
func TestRedisStreamConsumerConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     RedisStreamConfig
		wantErr bool
	}{
		{
			name: "empty address",
			cfg: RedisStreamConfig{
				Addr:    "",
				GroupID: "test-group",
			},
			wantErr: true,
		},
		{
			name: "empty group id",
			cfg: RedisStreamConfig{
				Addr:    "localhost:6379",
				GroupID: "",
			},
			wantErr: true,
		},
		{
			name: "valid config",
			cfg: RedisStreamConfig{
				Addr:    "localhost:6379",
				GroupID: "test-group",
			},
			wantErr: true, // connection will fail locally without actual Redis
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			_, err := NewRedisStreamConsumer(tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewRedisStreamConsumer() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test StreamMessage structure.
func TestStreamMessage(t *testing.T) {
	t.Parallel()
	msg := dal.StreamMessage{
		Topic:     "test-topic",
		Partition: 0,
		Offset:    100,
		Key:       []byte("test-key"),
		Value:     []byte("test-value"),
		Headers: map[string]string{
			"content-type": "application/json",
		},
		Timestamp: time.Now(),
	}

	if msg.Topic != "test-topic" {
		t.Errorf("Topic = %s, want test-topic", msg.Topic)
	}
	if string(msg.Key) != "test-key" {
		t.Errorf("Key = %s, want test-key", string(msg.Key))
	}
	if msg.Headers["content-type"] != "application/json" {
		t.Errorf("Headers[content-type] = %s, want application/json", msg.Headers["content-type"])
	}
}

// Mock stream producer/consumer for testing higher-level code.
type MockStreamProducer struct {
	messages []dal.StreamMessage
}

func NewMockStreamProducer() *MockStreamProducer {
	return &MockStreamProducer{messages: []dal.StreamMessage{}}
}

func (m *MockStreamProducer) Publish(ctx context.Context, topic string, message []byte, opts ...dal.PublishOption) error {
	po := &dal.PublishOptions{}
	for _, opt := range opts {
		opt(po)
	}

	msg := dal.StreamMessage{
		Topic:     topic,
		Value:     message,
		Key:       po.Key,
		Headers:   po.Headers,
		Timestamp: time.Now(),
	}

	m.messages = append(m.messages, msg)
	return nil
}

func (m *MockStreamProducer) Flush(ctx context.Context, timeout time.Duration) error {
	return nil
}

func (m *MockStreamProducer) Close() error {
	return nil
}

// Test MockStreamProducer interface compliance.
func TestMockStreamProducerInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StreamProducer = (*MockStreamProducer)(nil)
}

// Test MockStreamProducer.
func TestMockStreamProducer(t *testing.T) {
	t.Parallel()
	mp := NewMockStreamProducer()
	ctx := context.Background()

	err := mp.Publish(ctx, "test-topic", []byte("test-value"))
	if err != nil {
		t.Errorf("Publish() error = %v", err)
	}

	if len(mp.messages) != 1 {
		t.Errorf("Publish() stored %d messages, want 1", len(mp.messages))
	}

	if mp.messages[0].Topic != "test-topic" {
		t.Errorf("Topic = %s, want test-topic", mp.messages[0].Topic)
	}

	if string(mp.messages[0].Value) != "test-value" {
		t.Errorf("Value = %s, want test-value", string(mp.messages[0].Value))
	}
}

// Test MockStreamProducer with options.
func TestMockStreamProducerWithOptions(t *testing.T) {
	t.Parallel()
	mp := NewMockStreamProducer()
	ctx := context.Background()

	opts := []dal.PublishOption{
		dal.WithPublishKey([]byte("msg-key")),
		dal.WithPublishHeaders(map[string]string{"type": "event"}),
	}

	err := mp.Publish(ctx, "events", []byte("event-data"), opts...)
	if err != nil {
		t.Errorf("Publish() with options error = %v", err)
	}

	if len(mp.messages) != 1 {
		t.Errorf("Expected 1 message")
	}

	msg := mp.messages[0]
	if string(msg.Key) != "msg-key" {
		t.Errorf("Key = %s, want msg-key", string(msg.Key))
	}
	if msg.Headers["type"] != "event" {
		t.Errorf("Headers[type] = %s, want event", msg.Headers["type"])
	}
}

// Test MockStreamProducer Flush.
func TestMockStreamProducerFlush(t *testing.T) {
	t.Parallel()
	mp := NewMockStreamProducer()
	ctx := context.Background()

	err := mp.Flush(ctx, 5*time.Second)
	if err != nil {
		t.Errorf("Flush() error = %v", err)
	}
}

// Test MockStreamProducer Close.
func TestMockStreamProducerClose(t *testing.T) {
	t.Parallel()
	mp := NewMockStreamProducer()

	err := mp.Close()
	if err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

// Mock stream consumer for testing.
type MockStreamConsumer struct {
	messages []dal.StreamMessage
	index    int
	groupID  string
}

func NewMockStreamConsumer() *MockStreamConsumer {
	return &MockStreamConsumer{
		messages: []dal.StreamMessage{},
		index:    0,
	}
}

func (m *MockStreamConsumer) Subscribe(topics []string) error {
	if len(topics) == 0 {
		return fmt.Errorf("no topics provided")
	}
	return nil
}

func (m *MockStreamConsumer) Poll(ctx context.Context, timeout time.Duration) ([]dal.StreamMessage, error) {
	if m.index >= len(m.messages) {
		return []dal.StreamMessage{}, nil
	}

	result := []dal.StreamMessage{m.messages[m.index]}
	m.index++
	return result, nil
}

func (m *MockStreamConsumer) Commit(ctx context.Context) error {
	return nil
}

func (m *MockStreamConsumer) Close() error {
	return nil
}

// Test MockStreamConsumer interface compliance.
func TestMockStreamConsumerInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.StreamConsumer = (*MockStreamConsumer)(nil)
}

// Test MockStreamConsumer basic operations.
func TestMockStreamConsumer(t *testing.T) {
	t.Parallel()
	mc := NewMockStreamConsumer()
	ctx := context.Background()

	// Subscribe
	err := mc.Subscribe([]string{"test-topic"})
	if err != nil {
		t.Errorf("Subscribe() error = %v", err)
	}

	// Add some messages
	mc.messages = []dal.StreamMessage{
		{
			Topic:     "test-topic",
			Partition: 0,
			Offset:    0,
			Key:       []byte("key1"),
			Value:     []byte("value1"),
		},
		{
			Topic:     "test-topic",
			Partition: 0,
			Offset:    1,
			Key:       []byte("key2"),
			Value:     []byte("value2"),
		},
	}

	// Poll
	msgs, err := mc.Poll(ctx, 1*time.Second)
	if err != nil {
		t.Errorf("Poll() error = %v", err)
	}
	if len(msgs) != 1 {
		t.Errorf("Poll() returned %d messages, want 1", len(msgs))
	}

	// Commit
	err = mc.Commit(ctx)
	if err != nil {
		t.Errorf("Commit() error = %v", err)
	}

	// Close
	err = mc.Close()
	if err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

// Test MockStreamConsumer empty subscription.
func TestMockStreamConsumerEmptySubscription(t *testing.T) {
	t.Parallel()
	mc := NewMockStreamConsumer()

	err := mc.Subscribe([]string{})
	if err == nil {
		t.Errorf("Subscribe() empty topics should error")
	}
}

// Test MockStreamConsumer poll past end.
func TestMockStreamConsumerPollPastEnd(t *testing.T) {
	t.Parallel()
	mc := NewMockStreamConsumer()
	ctx := context.Background()

	mc.messages = []dal.StreamMessage{
		{Topic: "test", Value: []byte("msg1")},
	}

	// First poll
	msgs, _ := mc.Poll(ctx, 1*time.Second)
	if len(msgs) != 1 {
		t.Errorf("First poll should return 1 message")
	}

	// Second poll should return empty (past end)
	msgs, _ = mc.Poll(ctx, 1*time.Second)
	if len(msgs) != 0 {
		t.Errorf("Poll past end should return empty")
	}
}

// Test StreamMessage structure with all fields.
func TestStreamMessageStructure(t *testing.T) {
	t.Parallel()
	now := time.Now()
	msg := dal.StreamMessage{
		Topic:     "orders",
		Partition: 2,
		Offset:    1000,
		Key:       []byte("order-123"),
		Value:     []byte(`{"id":123,"amount":99.99}`),
		Headers: map[string]string{
			"correlation-id": "corr-456",
			"version":        "1.0",
		},
		Timestamp: now,
	}

	if msg.Topic != "orders" || msg.Partition != 2 || msg.Offset != 1000 {
		t.Errorf("StreamMessage fields mismatch")
	}
	if string(msg.Key) != "order-123" {
		t.Errorf("Key = %s, want order-123", string(msg.Key))
	}
	if len(msg.Headers) != 2 {
		t.Errorf("Headers count = %d, want 2", len(msg.Headers))
	}
	if msg.Timestamp != now {
		t.Errorf("Timestamp mismatch")
	}
}

// Test MockStreamProducer multiple messages.
func TestMockStreamProducerMultipleMessages(t *testing.T) {
	t.Parallel()
	mp := NewMockStreamProducer()
	ctx := context.Background()

	for i := 0; i < 10; i++ {
		topic := fmt.Sprintf("topic-%d", i%3)
		msg := []byte(fmt.Sprintf("msg-%d", i))
		err := mp.Publish(ctx, topic, msg)
		if err != nil {
			t.Errorf("Publish() error = %v", err)
		}
	}

	if len(mp.messages) != 10 {
		t.Errorf("Publish() stored %d messages, want 10", len(mp.messages))
	}

	// Verify topics
	topics := make(map[string]int)
	for _, m := range mp.messages {
		topics[m.Topic]++
	}
	if len(topics) != 3 {
		t.Errorf("Topics = %d, want 3", len(topics))
	}
}

// Test MockStreamConsumer iteration.
func TestMockStreamConsumerIteration(t *testing.T) {
	t.Parallel()
	mc := NewMockStreamConsumer()
	ctx := context.Background()

	mc.Subscribe([]string{"events"})

	// Add 5 messages
	for i := 0; i < 5; i++ {
		mc.messages = append(mc.messages, dal.StreamMessage{
			Topic: "events",
			Value: []byte(fmt.Sprintf("event-%d", i)),
		})
	}

	// Poll all messages
	for i := 0; i < 5; i++ {
		msgs, _ := mc.Poll(ctx, 100*time.Millisecond)
		if len(msgs) != 1 {
			t.Errorf("Poll %d: expected 1 message, got %d", i, len(msgs))
		}
	}

	// Poll empty
	msgs, _ := mc.Poll(ctx, 100*time.Millisecond)
	if len(msgs) != 0 {
		t.Errorf("Final poll should return empty")
	}
}
