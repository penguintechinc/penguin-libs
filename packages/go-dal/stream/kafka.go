package stream

import (
	"context"
	"fmt"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// kafkaProducerClient is the subset of *kafka.Producer used by KafkaProducer.
type kafkaProducerClient interface {
	Produce(msg *kafka.Message, deliveryChan chan kafka.Event) error
	Flush(timeoutMs int) int
	Close()
}

// kafkaConsumerClient is the subset of *kafka.Consumer used by KafkaConsumer.
type kafkaConsumerClient interface {
	SubscribeTopics(topics []string, rebalanceCb kafka.RebalanceCb) error
	Poll(timeoutMs int) kafka.Event
	Commit() ([]kafka.TopicPartition, error)
	Close() error
}

// KafkaConfig configures a Kafka streaming backend.
type KafkaConfig struct {
	BootstrapServers string
	GroupID          string
	AutoOffsetReset  string
	EnableAutoCommit bool
	SecurityProtocol string
	SASLMechanism    string
	SASLUsername     string
	SASLPassword     string
}

// KafkaProducer implements dal.StreamProducer for Kafka.
type KafkaProducer struct {
	producer kafkaProducerClient
}

// NewKafkaProducer creates a new Kafka producer.
func NewKafkaProducer(cfg KafkaConfig) (*KafkaProducer, error) {
	if cfg.BootstrapServers == "" {
		return nil, fmt.Errorf("go-dal: kafka: %w: bootstrap servers required", dal.ErrInvalidConfiguration)
	}

	configMap := kafka.ConfigMap{
		"bootstrap.servers": cfg.BootstrapServers,
	}

	if cfg.SecurityProtocol != "" {
		configMap["security.protocol"] = cfg.SecurityProtocol
	}
	if cfg.SASLMechanism != "" {
		configMap["sasl.mechanism"] = cfg.SASLMechanism
	}
	if cfg.SASLUsername != "" {
		configMap["sasl.username"] = cfg.SASLUsername
	}
	if cfg.SASLPassword != "" {
		configMap["sasl.password"] = cfg.SASLPassword
	}

	producer, err := kafka.NewProducer(&configMap)
	if err != nil {
		return nil, fmt.Errorf("go-dal: kafka: new producer: %w", err)
	}

	return &KafkaProducer{producer: producer}, nil
}

// NewKafkaProducerWithClient creates a KafkaProducer with an injected client (for testing).
func NewKafkaProducerWithClient(producer kafkaProducerClient) *KafkaProducer {
	return &KafkaProducer{producer: producer}
}

// Publish sends a message to a Kafka topic.
func (k *KafkaProducer) Publish(ctx context.Context, topic string, message []byte, opts ...dal.PublishOption) error {
	po := &dal.PublishOptions{}
	for _, opt := range opts {
		opt(po)
	}

	msg := &kafka.Message{
		TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
		Value:          message,
	}

	if len(po.Key) > 0 {
		msg.Key = po.Key
	}

	deliveryChan := make(chan kafka.Event, 1)
	err := k.producer.Produce(msg, deliveryChan)
	if err != nil {
		return fmt.Errorf("go-dal: kafka: produce queue: %w", err)
	}

	// Wait for delivery
	e := <-deliveryChan
	m := e.(*kafka.Message)

	if m.TopicPartition.Error != nil {
		return fmt.Errorf("go-dal: kafka: publish: %w", m.TopicPartition.Error)
	}

	return nil
}

// Flush waits for pending messages to be delivered.
func (k *KafkaProducer) Flush(ctx context.Context, timeout time.Duration) error {
	timeoutMs := int(timeout.Milliseconds())
	remaining := k.producer.Flush(timeoutMs)
	if remaining > 0 {
		return fmt.Errorf("go-dal: kafka: flush timeout with %d messages remaining", remaining)
	}

	return nil
}

// Close closes the Kafka producer.
func (k *KafkaProducer) Close() error {
	k.producer.Close()
	return nil
}

// KafkaConsumer implements dal.StreamConsumer for Kafka.
type KafkaConsumer struct {
	consumer      kafkaConsumerClient
	pendingCommit bool
}

// NewKafkaConsumer creates a new Kafka consumer.
func NewKafkaConsumer(cfg KafkaConfig) (*KafkaConsumer, error) {
	if cfg.BootstrapServers == "" {
		return nil, fmt.Errorf("go-dal: kafka: %w: bootstrap servers required", dal.ErrInvalidConfiguration)
	}
	if cfg.GroupID == "" {
		return nil, fmt.Errorf("go-dal: kafka: %w: group id required", dal.ErrInvalidConfiguration)
	}

	configMap := kafka.ConfigMap{
		"bootstrap.servers":       cfg.BootstrapServers,
		"group.id":                cfg.GroupID,
		"enable.auto.commit":      cfg.EnableAutoCommit,
		"auto.offset.reset":       "earliest",
	}

	if cfg.AutoOffsetReset != "" {
		configMap["auto.offset.reset"] = cfg.AutoOffsetReset
	}

	if cfg.SecurityProtocol != "" {
		configMap["security.protocol"] = cfg.SecurityProtocol
	}
	if cfg.SASLMechanism != "" {
		configMap["sasl.mechanism"] = cfg.SASLMechanism
	}
	if cfg.SASLUsername != "" {
		configMap["sasl.username"] = cfg.SASLUsername
	}
	if cfg.SASLPassword != "" {
		configMap["sasl.password"] = cfg.SASLPassword
	}

	consumer, err := kafka.NewConsumer(&configMap)
	if err != nil {
		return nil, fmt.Errorf("go-dal: kafka: new consumer: %w", err)
	}

	return &KafkaConsumer{
		consumer:      consumer,
		pendingCommit: false,
	}, nil
}

// NewKafkaConsumerWithClient creates a KafkaConsumer with an injected client (for testing).
func NewKafkaConsumerWithClient(consumer kafkaConsumerClient) *KafkaConsumer {
	return &KafkaConsumer{
		consumer:      consumer,
		pendingCommit: false,
	}
}

// Subscribe subscribes to a list of topics.
func (k *KafkaConsumer) Subscribe(topics []string) error {
	if err := k.consumer.SubscribeTopics(topics, nil); err != nil {
		return fmt.Errorf("go-dal: kafka: subscribe: %w", err)
	}

	return nil
}

// Poll polls for messages from subscribed topics.
func (k *KafkaConsumer) Poll(ctx context.Context, timeout time.Duration) ([]dal.StreamMessage, error) {
	timeoutMs := int(timeout.Milliseconds())
	var messages []dal.StreamMessage

	for {
		ev := k.consumer.Poll(timeoutMs)
		if ev == nil {
			break
		}

		switch e := ev.(type) {
		case *kafka.Message:
			headers := make(map[string]string)
			for _, h := range e.Headers {
				headers[h.Key] = string(h.Value)
			}

			msg := dal.StreamMessage{
				Topic:     *e.TopicPartition.Topic,
				Partition: e.TopicPartition.Partition,
				Offset:    int64(e.TopicPartition.Offset),
				Key:       e.Key,
				Value:     e.Value,
				Headers:   headers,
				Timestamp: e.Timestamp,
			}

			messages = append(messages, msg)
			k.pendingCommit = true

		case kafka.Error:
			return nil, fmt.Errorf("go-dal: kafka: poll error: %w", e)

		default:
		}
	}

	return messages, nil
}

// Commit commits the current offset.
func (k *KafkaConsumer) Commit(ctx context.Context) error {
	if !k.pendingCommit {
		return nil
	}

	_, err := k.consumer.Commit()
	if err != nil {
		return fmt.Errorf("go-dal: kafka: commit: %w", err)
	}

	k.pendingCommit = false
	return nil
}

// Close closes the Kafka consumer.
func (k *KafkaConsumer) Close() error {
	return k.consumer.Close()
}
