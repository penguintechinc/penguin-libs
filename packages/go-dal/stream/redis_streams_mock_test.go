package stream

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"github.com/redis/go-redis/v9"
)

// --- mock Redis stream client ---

type mockRedisStreamClient struct {
	// XAdd
	failXAdd bool
	xAddID   string

	// XReadGroup
	failXReadGroup bool
	xReadResults   []redis.XStream

	// XGroupCreateMkStream
	failXGroupCreate     bool
	xGroupCreateErrOnce  bool   // error on first call, pass on second (to exercise XInfoStream path)
	xGroupCreateCallCount int

	// XInfoStream
	failXInfoStream bool

	// XAck
	failXAck bool

	// Close
	failClose bool
}

func (m *mockRedisStreamClient) XAdd(ctx context.Context, a *redis.XAddArgs) *redis.StringCmd {
	cmd := redis.NewStringCmd(ctx)
	if m.failXAdd {
		cmd.SetErr(errors.New("xadd failed"))
	} else {
		id := m.xAddID
		if id == "" {
			id = "1-0"
		}
		cmd.SetVal(id)
	}
	return cmd
}

func (m *mockRedisStreamClient) XReadGroup(ctx context.Context, a *redis.XReadGroupArgs) *redis.XStreamSliceCmd {
	cmd := redis.NewXStreamSliceCmd(ctx)
	if m.failXReadGroup {
		cmd.SetErr(errors.New("xreadgroup failed"))
	} else {
		cmd.SetVal(m.xReadResults)
	}
	return cmd
}

func (m *mockRedisStreamClient) XGroupCreateMkStream(ctx context.Context, stream, group, start string) *redis.StatusCmd {
	cmd := redis.NewStatusCmd(ctx)
	m.xGroupCreateCallCount++
	if m.failXGroupCreate {
		cmd.SetErr(errors.New("group create failed"))
		return cmd
	}
	if m.xGroupCreateErrOnce && m.xGroupCreateCallCount == 1 {
		cmd.SetErr(errors.New("group already exists"))
		return cmd
	}
	cmd.SetVal("OK")
	return cmd
}

func (m *mockRedisStreamClient) XInfoStream(ctx context.Context, key string) *redis.XInfoStreamCmd {
	cmd := redis.NewXInfoStreamCmd(ctx, key)
	if m.failXInfoStream {
		cmd.SetErr(errors.New("xinfo failed"))
	}
	return cmd
}

func (m *mockRedisStreamClient) XAck(ctx context.Context, stream, group string, ids ...string) *redis.IntCmd {
	cmd := redis.NewIntCmd(ctx)
	if m.failXAck {
		cmd.SetErr(errors.New("xack failed"))
	} else {
		cmd.SetVal(int64(len(ids)))
	}
	return cmd
}

func (m *mockRedisStreamClient) Close() error {
	if m.failClose {
		return errors.New("close failed")
	}
	return nil
}

// --- producer tests ---

func TestRedisStreamProducerPublish(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{})
	err := p.Publish(context.Background(), "stream", []byte("msg"))
	if err != nil {
		t.Errorf("Publish() = %v, want nil", err)
	}
}

func TestRedisStreamProducerPublishWithKey(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{})
	err := p.Publish(context.Background(), "stream", []byte("msg"), dal.WithPublishKey([]byte("k")))
	if err != nil {
		t.Errorf("Publish() with key = %v, want nil", err)
	}
}

func TestRedisStreamProducerPublishWithHeaders(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{})
	err := p.Publish(context.Background(), "stream", []byte("msg"), dal.WithPublishHeaders(map[string]string{"h": "v"}))
	if err != nil {
		t.Errorf("Publish() with headers = %v, want nil", err)
	}
}

func TestRedisStreamProducerPublishError(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{failXAdd: true})
	err := p.Publish(context.Background(), "stream", []byte("msg"))
	if err == nil {
		t.Error("Publish() expected error, got nil")
	}
}

func TestRedisStreamProducerFlush(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{})
	err := p.Flush(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Flush() = %v, want nil", err)
	}
}

func TestRedisStreamProducerClose(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{})
	if err := p.Close(); err != nil {
		t.Errorf("Close() = %v, want nil", err)
	}
}

func TestRedisStreamProducerCloseError(t *testing.T) {
	t.Parallel()
	p := NewRedisStreamProducerWithClient(&mockRedisStreamClient{failClose: true})
	if err := p.Close(); err == nil {
		t.Error("Close() expected error, got nil")
	}
}

func TestNewRedisStreamProducerEmptyAddr(t *testing.T) {
	t.Parallel()
	_, err := NewRedisStreamProducer(RedisStreamConfig{})
	if err == nil {
		t.Error("NewRedisStreamProducer() expected error for empty addr, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewRedisStreamProducer() = %v, want ErrInvalidConfiguration", err)
	}
}

// --- consumer tests ---

func makeConsumer(mock *mockRedisStreamClient) *RedisStreamConsumer {
	return NewRedisStreamConsumerWithClient(mock, RedisStreamConfig{
		GroupID:      "grp",
		ConsumerName: "c1",
		BatchSize:    10,
	})
}

func TestRedisStreamConsumerSubscribe(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{})
	err := c.Subscribe([]string{"s1", "s2"})
	if err != nil {
		t.Errorf("Subscribe() = %v, want nil", err)
	}
	if len(c.topics) != 2 {
		t.Errorf("Subscribe() topics len = %d, want 2", len(c.topics))
	}
}

func TestRedisStreamConsumerSubscribeGroupError(t *testing.T) {
	t.Parallel()
	// failXGroupCreate + failXInfoStream → Subscribe should return error
	c := makeConsumer(&mockRedisStreamClient{failXGroupCreate: true, failXInfoStream: true})
	err := c.Subscribe([]string{"s1"})
	if err == nil {
		t.Error("Subscribe() expected error, got nil")
	}
}

func TestRedisStreamConsumerSubscribeGroupExistsXInfoOK(t *testing.T) {
	t.Parallel()
	// xGroupCreateErrOnce: first call returns error, so we fall through to XInfoStream which succeeds
	c := makeConsumer(&mockRedisStreamClient{xGroupCreateErrOnce: true})
	err := c.Subscribe([]string{"s1"})
	if err != nil {
		t.Errorf("Subscribe() group-exists path = %v, want nil", err)
	}
}

func TestRedisStreamConsumerPollNoTopics(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{})
	_, err := c.Poll(context.Background(), time.Second)
	if err == nil {
		t.Error("Poll() with no topics: expected error, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("Poll() = %v, want ErrInvalidConfiguration", err)
	}
}

func TestRedisStreamConsumerPollEmpty(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{xReadResults: []redis.XStream{}})
	c.topics = []string{"s1"}
	msgs, err := c.Poll(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Poll() empty = %v, want nil", err)
	}
	if len(msgs) != 0 {
		t.Errorf("Poll() empty len = %d, want 0", len(msgs))
	}
}

func TestRedisStreamConsumerPollMessages(t *testing.T) {
	t.Parallel()
	results := []redis.XStream{
		{
			Stream: "s1",
			Messages: []redis.XMessage{
				{
					ID: "1-0",
					Values: map[string]interface{}{
						"value":   "hello",
						"key":     "mykey",
						"headers": `{"x":"y"}`,
					},
				},
				{
					ID: "2-0",
					Values: map[string]interface{}{
						"value": "world",
					},
				},
			},
		},
	}
	c := makeConsumer(&mockRedisStreamClient{xReadResults: results})
	c.topics = []string{"s1"}
	msgs, err := c.Poll(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Poll() = %v, want nil", err)
	}
	if len(msgs) != 2 {
		t.Errorf("Poll() len = %d, want 2", len(msgs))
	}
	if string(msgs[0].Value) != "hello" {
		t.Errorf("msgs[0].Value = %q, want hello", msgs[0].Value)
	}
	if string(msgs[0].Key) != "mykey" {
		t.Errorf("msgs[0].Key = %q, want mykey", msgs[0].Key)
	}
	if msgs[0].Headers["x"] != "y" {
		t.Errorf("msgs[0].Headers[x] = %q, want y", msgs[0].Headers["x"])
	}
	// pendingIDs should be populated
	if c.pendingIDs["s1"] != "2-0" {
		t.Errorf("pendingIDs[s1] = %q, want 2-0", c.pendingIDs["s1"])
	}
}

func TestRedisStreamConsumerPollNilResults(t *testing.T) {
	t.Parallel()
	// redis.Nil is treated as "no messages" — not an error
	c := makeConsumer(&mockRedisStreamClient{failXReadGroup: false, xReadResults: nil})
	c.topics = []string{"s1"}
	msgs, err := c.Poll(context.Background(), time.Second)
	if err != nil {
		t.Errorf("Poll() nil results = %v, want nil", err)
	}
	if len(msgs) != 0 {
		t.Errorf("Poll() nil results len = %d, want 0", len(msgs))
	}
}

func TestRedisStreamConsumerPollError(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{failXReadGroup: true})
	c.topics = []string{"s1"}
	_, err := c.Poll(context.Background(), time.Second)
	if err == nil {
		t.Error("Poll() expected error, got nil")
	}
}

func TestRedisStreamConsumerCommitEmpty(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{})
	err := c.Commit(context.Background())
	if err != nil {
		t.Errorf("Commit() no pending = %v, want nil", err)
	}
}

func TestRedisStreamConsumerCommitWithPending(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{})
	c.pendingIDs["s1"] = "1-0"
	err := c.Commit(context.Background())
	if err != nil {
		t.Errorf("Commit() = %v, want nil", err)
	}
	if len(c.pendingIDs) != 0 {
		t.Error("pendingIDs should be cleared after commit")
	}
}

func TestRedisStreamConsumerCommitError(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{failXAck: true})
	c.pendingIDs["s1"] = "1-0"
	err := c.Commit(context.Background())
	if err == nil {
		t.Error("Commit() expected error, got nil")
	}
}

func TestRedisStreamConsumerClose(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{})
	if err := c.Close(); err != nil {
		t.Errorf("Close() = %v, want nil", err)
	}
}

func TestRedisStreamConsumerCloseError(t *testing.T) {
	t.Parallel()
	c := makeConsumer(&mockRedisStreamClient{failClose: true})
	if err := c.Close(); err == nil {
		t.Error("Close() expected error, got nil")
	}
}

func TestNewRedisStreamConsumerEmptyAddr(t *testing.T) {
	t.Parallel()
	_, err := NewRedisStreamConsumer(RedisStreamConfig{GroupID: "grp"})
	if err == nil {
		t.Error("NewRedisStreamConsumer() expected error for empty addr, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewRedisStreamConsumer() = %v, want ErrInvalidConfiguration", err)
	}
}

func TestNewRedisStreamConsumerEmptyGroupID(t *testing.T) {
	t.Parallel()
	_, err := NewRedisStreamConsumer(RedisStreamConfig{Addr: "localhost:6379"})
	if err == nil {
		t.Error("NewRedisStreamConsumer() expected error for empty group id, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewRedisStreamConsumer() = %v, want ErrInvalidConfiguration", err)
	}
}

func TestNewRedisStreamConsumerWithClientDefaults(t *testing.T) {
	t.Parallel()
	c := NewRedisStreamConsumerWithClient(&mockRedisStreamClient{}, RedisStreamConfig{GroupID: "grp"})
	if c.cfg.ConsumerName != "consumer-1" {
		t.Errorf("ConsumerName default = %q, want consumer-1", c.cfg.ConsumerName)
	}
	if c.cfg.BatchSize != 10 {
		t.Errorf("BatchSize default = %d, want 10", c.cfg.BatchSize)
	}
}
