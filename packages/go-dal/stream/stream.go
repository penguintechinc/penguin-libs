// Package stream provides streaming backend implementations (Kafka, Redis Streams).
package stream

import (
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Ensure interface compliance at compile time.
var (
	_ dal.StreamProducer = (*KafkaProducer)(nil)
	_ dal.StreamConsumer = (*KafkaConsumer)(nil)
	_ dal.StreamProducer = (*RedisStreamProducer)(nil)
	_ dal.StreamConsumer = (*RedisStreamConsumer)(nil)
)
