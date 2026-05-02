package stream

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// --- mock producer ---

type mockKafkaProducer struct {
	failProduce   bool
	flushRemaining int
	closed        bool

	// produceDeliverErr simulates a delivery-level error in the kafka.Message.
	produceDeliverErr bool
	// produceDeliverAsync: if true, runs delivery in separate goroutine (shouldn't matter here).
}

func (m *mockKafkaProducer) Produce(msg *kafka.Message, deliveryChan chan kafka.Event) error {
	if m.failProduce {
		return errors.New("produce enqueue failed")
	}
	// Simulate async delivery notification.
	var deliveredMsg kafka.Message = *msg
	if m.produceDeliverErr {
		deliveredMsg.TopicPartition.Error = errors.New("broker error")
	}
	go func() {
		deliveryChan <- &deliveredMsg
	}()
	return nil
}

func (m *mockKafkaProducer) Flush(timeoutMs int) int {
	return m.flushRemaining
}

func (m *mockKafkaProducer) Close() {
	m.closed = true
}

// --- mock consumer ---

type mockKafkaConsumer struct {
	failSubscribe bool
	failCommit    bool
	failClose     bool
	events        []kafka.Event
	eventIdx      int
}

func (m *mockKafkaConsumer) SubscribeTopics(topics []string, rebalanceCb kafka.RebalanceCb) error {
	if m.failSubscribe {
		return errors.New("subscribe failed")
	}
	return nil
}

func (m *mockKafkaConsumer) Poll(timeoutMs int) kafka.Event {
	if m.eventIdx >= len(m.events) {
		return nil
	}
	ev := m.events[m.eventIdx]
	m.eventIdx++
	return ev
}

func (m *mockKafkaConsumer) Commit() ([]kafka.TopicPartition, error) {
	if m.failCommit {
		return nil, errors.New("commit failed")
	}
	return nil, nil
}

func (m *mockKafkaConsumer) Close() error {
	if m.failClose {
		return errors.New("close failed")
	}
	return nil
}

// --- helpers ---

func newTopic(t string) *string { return &t }

// --- producer tests ---

func TestKafkaProducerPublish(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{})
	ctx := context.Background()
	err := p.Publish(ctx, "topic", []byte("hello"))
	if err != nil {
		t.Errorf("Publish() = %v, want nil", err)
	}
}

func TestKafkaProducerPublishWithKey(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{})
	ctx := context.Background()
	err := p.Publish(ctx, "topic", []byte("hello"), dal.WithPublishKey([]byte("mykey")))
	if err != nil {
		t.Errorf("Publish() with key = %v, want nil", err)
	}
}

func TestKafkaProducerPublishWithHeaders(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{})
	ctx := context.Background()
	err := p.Publish(ctx, "topic", []byte("hello"), dal.WithPublishHeaders(map[string]string{"h": "v"}))
	if err != nil {
		t.Errorf("Publish() with headers = %v, want nil", err)
	}
}

func TestKafkaProducerPublishProduceError(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{failProduce: true})
	ctx := context.Background()
	err := p.Publish(ctx, "topic", []byte("hello"))
	if err == nil {
		t.Error("Publish() expected error, got nil")
	}
}

func TestKafkaProducerPublishDeliveryError(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{produceDeliverErr: true})
	ctx := context.Background()
	err := p.Publish(ctx, "topic", []byte("hello"))
	if err == nil {
		t.Error("Publish() delivery error: expected error, got nil")
	}
}

func TestKafkaProducerFlushSuccess(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{flushRemaining: 0})
	ctx := context.Background()
	err := p.Flush(ctx, time.Second)
	if err != nil {
		t.Errorf("Flush() = %v, want nil", err)
	}
}

func TestKafkaProducerFlushTimeout(t *testing.T) {
	t.Parallel()
	p := NewKafkaProducerWithClient(&mockKafkaProducer{flushRemaining: 3})
	ctx := context.Background()
	err := p.Flush(ctx, time.Second)
	if err == nil {
		t.Error("Flush() expected timeout error, got nil")
	}
}

func TestKafkaProducerClose(t *testing.T) {
	t.Parallel()
	mp := &mockKafkaProducer{}
	p := NewKafkaProducerWithClient(mp)
	if err := p.Close(); err != nil {
		t.Errorf("Close() = %v, want nil", err)
	}
	if !mp.closed {
		t.Error("Close() did not set closed=true on mock")
	}
}

func TestNewKafkaProducerEmptyBootstrap(t *testing.T) {
	t.Parallel()
	_, err := NewKafkaProducer(KafkaConfig{})
	if err == nil {
		t.Error("NewKafkaProducer() expected error for empty bootstrap, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewKafkaProducer() = %v, want ErrInvalidConfiguration", err)
	}
}

// --- consumer tests ---

func TestKafkaConsumerSubscribe(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{})
	err := c.Subscribe([]string{"t1", "t2"})
	if err != nil {
		t.Errorf("Subscribe() = %v, want nil", err)
	}
}

func TestKafkaConsumerSubscribeError(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{failSubscribe: true})
	err := c.Subscribe([]string{"t1"})
	if err == nil {
		t.Error("Subscribe() expected error, got nil")
	}
}

func TestKafkaConsumerPollEmpty(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{})
	msgs, err := c.Poll(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Poll() = %v, want nil", err)
	}
	if len(msgs) != 0 {
		t.Errorf("Poll() len = %d, want 0", len(msgs))
	}
}

func TestKafkaConsumerPollMessages(t *testing.T) {
	t.Parallel()
	topic := "stream-topic"
	events := []kafka.Event{
		&kafka.Message{
			TopicPartition: kafka.TopicPartition{Topic: newTopic(topic), Partition: 0, Offset: 1},
			Key:            []byte("k"),
			Value:          []byte("v"),
			Headers:        []kafka.Header{{Key: "hk", Value: []byte("hv")}},
			Timestamp:      time.Now(),
		},
		&kafka.Message{
			TopicPartition: kafka.TopicPartition{Topic: newTopic(topic), Partition: 0, Offset: 2},
			Key:            nil,
			Value:          []byte("v2"),
		},
	}
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{events: events})
	msgs, err := c.Poll(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Poll() = %v, want nil", err)
	}
	if len(msgs) != 2 {
		t.Errorf("Poll() len = %d, want 2", len(msgs))
	}
	if string(msgs[0].Key) != "k" {
		t.Errorf("msgs[0].Key = %q, want k", msgs[0].Key)
	}
	if msgs[0].Headers["hk"] != "hv" {
		t.Errorf("msgs[0].Headers[hk] = %q, want hv", msgs[0].Headers["hk"])
	}
	// pendingCommit should be true now
	if !c.pendingCommit {
		t.Error("pendingCommit should be true after poll with messages")
	}
}

func TestKafkaConsumerPollKafkaError(t *testing.T) {
	t.Parallel()
	events := []kafka.Event{kafka.Error(kafka.NewError(kafka.ErrUnknown, "test error", false))}
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{events: events})
	_, err := c.Poll(context.Background(), time.Second)
	if err == nil {
		t.Error("Poll() expected error on kafka.Error event, got nil")
	}
}

func TestKafkaConsumerPollUnknownEvent(t *testing.T) {
	t.Parallel()
	// kafka.PartitionEOF is an event that falls through to default
	events := []kafka.Event{kafka.PartitionEOF{}}
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{events: events})
	msgs, err := c.Poll(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Poll() unknown event = %v, want nil", err)
	}
	if len(msgs) != 0 {
		t.Errorf("Poll() unknown event len = %d, want 0", len(msgs))
	}
}

func TestKafkaConsumerCommitNoPending(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{})
	err := c.Commit(context.Background())
	if err != nil {
		t.Errorf("Commit() no pending = %v, want nil", err)
	}
}

func TestKafkaConsumerCommitWithPending(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{})
	c.pendingCommit = true
	err := c.Commit(context.Background())
	if err != nil {
		t.Errorf("Commit() = %v, want nil", err)
	}
	if c.pendingCommit {
		t.Error("pendingCommit should be false after commit")
	}
}

func TestKafkaConsumerCommitError(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{failCommit: true})
	c.pendingCommit = true
	err := c.Commit(context.Background())
	if err == nil {
		t.Error("Commit() expected error, got nil")
	}
}

func TestKafkaConsumerClose(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{})
	if err := c.Close(); err != nil {
		t.Errorf("Close() = %v, want nil", err)
	}
}

func TestKafkaConsumerCloseError(t *testing.T) {
	t.Parallel()
	c := NewKafkaConsumerWithClient(&mockKafkaConsumer{failClose: true})
	if err := c.Close(); err == nil {
		t.Error("Close() expected error, got nil")
	}
}

func TestNewKafkaConsumerEmptyBootstrap(t *testing.T) {
	t.Parallel()
	_, err := NewKafkaConsumer(KafkaConfig{GroupID: "grp"})
	if err == nil {
		t.Error("NewKafkaConsumer() expected error for empty bootstrap, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewKafkaConsumer() = %v, want ErrInvalidConfiguration", err)
	}
}

func TestNewKafkaConsumerEmptyGroupID(t *testing.T) {
	t.Parallel()
	_, err := NewKafkaConsumer(KafkaConfig{BootstrapServers: "localhost:9092"})
	if err == nil {
		t.Error("NewKafkaConsumer() expected error for empty group id, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewKafkaConsumer() = %v, want ErrInvalidConfiguration", err)
	}
}
