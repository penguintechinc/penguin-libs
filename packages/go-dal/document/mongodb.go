package document

import (
	"context"
	"fmt"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/bson/primitive"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

// mongoCollection is the subset of *mongo.Collection operations used by MongoDB.
type mongoCollection interface {
	InsertOne(ctx context.Context, document interface{}, opts ...*options.InsertOneOptions) (*mongo.InsertOneResult, error)
	FindOne(ctx context.Context, filter interface{}, opts ...*options.FindOneOptions) *mongo.SingleResult
	Find(ctx context.Context, filter interface{}, opts ...*options.FindOptions) (*mongo.Cursor, error)
	UpdateOne(ctx context.Context, filter interface{}, update interface{}, opts ...*options.UpdateOptions) (*mongo.UpdateResult, error)
	DeleteOne(ctx context.Context, filter interface{}, opts ...*options.DeleteOptions) (*mongo.DeleteResult, error)
	CountDocuments(ctx context.Context, filter interface{}, opts ...*options.CountOptions) (int64, error)
	Indexes() mongo.IndexView
}

// mongoDatabase is the subset of *mongo.Database operations used by MongoDB.
type mongoDatabase interface {
	Collection(name string, opts ...*options.CollectionOptions) mongoCollection
}

// mongoClientConn is the subset of *mongo.Client used by MongoDB.
type mongoClientConn interface {
	Disconnect(ctx context.Context) error
}

// realMongoDatabase wraps *mongo.Database to implement mongoDatabase.
type realMongoDatabase struct {
	inner *mongo.Database
}

func (r *realMongoDatabase) Collection(name string, opts ...*options.CollectionOptions) mongoCollection {
	return r.inner.Collection(name, opts...)
}

// MongoConfig configures a MongoDB document store.
type MongoConfig struct {
	URI                    string
	DBName                 string
	ServerSelectionTimeout time.Duration
	ConnectTimeout         time.Duration
	MaxPoolSize            uint64
}

// MongoDB implements dal.DocumentStore for MongoDB.
type MongoDB struct {
	conn mongoClientConn
	db   mongoDatabase
	cfg  MongoConfig
}

// NewMongoDB creates a new MongoDB document store.
func NewMongoDB(ctx context.Context, cfg MongoConfig) (*MongoDB, error) {
	if cfg.URI == "" {
		return nil, fmt.Errorf("go-dal: mongodb: %w: connection URI required", dal.ErrInvalidConfiguration)
	}
	if cfg.DBName == "" {
		return nil, fmt.Errorf("go-dal: mongodb: %w: database name required", dal.ErrInvalidConfiguration)
	}

	if cfg.ServerSelectionTimeout == 0 {
		cfg.ServerSelectionTimeout = 5 * time.Second
	}
	if cfg.ConnectTimeout == 0 {
		cfg.ConnectTimeout = 10 * time.Second
	}
	if cfg.MaxPoolSize == 0 {
		cfg.MaxPoolSize = 100
	}

	clientOpts := options.Client().
		ApplyURI(cfg.URI).
		SetServerSelectionTimeout(cfg.ServerSelectionTimeout).
		SetConnectTimeout(cfg.ConnectTimeout).
		SetMaxPoolSize(cfg.MaxPoolSize)

	client, err := mongo.Connect(ctx, clientOpts)
	if err != nil {
		return nil, fmt.Errorf("go-dal: mongodb: connect: %w", err)
	}

	// Verify connection
	if err := client.Ping(ctx, nil); err != nil {
		client.Disconnect(ctx)
		return nil, fmt.Errorf("go-dal: mongodb: ping: %w", err)
	}

	rawDB := client.Database(cfg.DBName)

	return &MongoDB{
		conn: client,
		db:   &realMongoDatabase{inner: rawDB},
		cfg:  cfg,
	}, nil
}

// NewMongoDBWithDatabase creates a MongoDB using injected database/client interfaces (for testing).
func NewMongoDBWithDatabase(conn mongoClientConn, db mongoDatabase, cfg MongoConfig) *MongoDB {
	return &MongoDB{
		conn: conn,
		db:   db,
		cfg:  cfg,
	}
}

// InsertOne inserts a single document into a collection.
func (m *MongoDB) InsertOne(ctx context.Context, collection string, document interface{}) (string, error) {
	coll := m.db.Collection(collection)

	result, err := coll.InsertOne(ctx, document)
	if err != nil {
		return "", fmt.Errorf("go-dal: mongodb: insert: %w", err)
	}

	// Convert ObjectID to hex string
	if oid, ok := result.InsertedID.(primitive.ObjectID); ok {
		return oid.Hex(), nil
	}

	return fmt.Sprintf("%v", result.InsertedID), nil
}

// FindOne finds a single document matching the filter.
func (m *MongoDB) FindOne(ctx context.Context, collection string, filter interface{}) (map[string]interface{}, error) {
	coll := m.db.Collection(collection)

	result := bson.M{}
	err := coll.FindOne(ctx, filter).Decode(&result)
	if err == mongo.ErrNoDocuments {
		return nil, fmt.Errorf("go-dal: mongodb: find: %w", dal.ErrNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("go-dal: mongodb: find: %w", err)
	}

	// Convert ObjectID to string in result
	if id, ok := result["_id"].(primitive.ObjectID); ok {
		result["_id"] = id.Hex()
	}

	return result, nil
}

// Find finds multiple documents matching the filter.
func (m *MongoDB) Find(ctx context.Context, collection string, filter interface{}, opts ...dal.FindOption) ([]map[string]interface{}, error) {
	coll := m.db.Collection(collection)

	fo := &dal.FindOptions{}
	for _, opt := range opts {
		opt(fo)
	}

	findOpts := options.Find()
	if fo.Limit > 0 {
		findOpts = findOpts.SetLimit(fo.Limit)
	}
	if fo.Skip > 0 {
		findOpts = findOpts.SetSkip(fo.Skip)
	}

	// Apply sort options
	if len(fo.Sort) > 0 {
		sortDoc := bson.D{}
		for _, ik := range fo.Sort {
			sortDoc = append(sortDoc, bson.E{Key: ik.Field, Value: ik.Direction})
		}
		findOpts.SetSort(sortDoc)
	}

	cursor, err := coll.Find(ctx, filter, findOpts)
	if err != nil {
		return nil, fmt.Errorf("go-dal: mongodb: find: %w", err)
	}
	defer cursor.Close(ctx)

	var results []map[string]interface{}
	if err := cursor.All(ctx, &results); err != nil {
		return nil, fmt.Errorf("go-dal: mongodb: find all: %w", err)
	}

	// Convert ObjectIDs to strings
	for i, doc := range results {
		if id, ok := doc["_id"].(primitive.ObjectID); ok {
			doc["_id"] = id.Hex()
		}
		results[i] = doc
	}

	return results, nil
}

// UpdateOne updates a single document matching the filter.
func (m *MongoDB) UpdateOne(ctx context.Context, collection string, filter, update interface{}) (int64, error) {
	coll := m.db.Collection(collection)

	result, err := coll.UpdateOne(ctx, filter, update)
	if err != nil {
		return 0, fmt.Errorf("go-dal: mongodb: update: %w", err)
	}

	return result.ModifiedCount, nil
}

// DeleteOne deletes a single document matching the filter.
func (m *MongoDB) DeleteOne(ctx context.Context, collection string, filter interface{}) (int64, error) {
	coll := m.db.Collection(collection)

	result, err := coll.DeleteOne(ctx, filter)
	if err != nil {
		return 0, fmt.Errorf("go-dal: mongodb: delete: %w", err)
	}

	return result.DeletedCount, nil
}

// Count returns the count of documents matching the filter.
func (m *MongoDB) Count(ctx context.Context, collection string, filter interface{}) (int64, error) {
	coll := m.db.Collection(collection)

	count, err := coll.CountDocuments(ctx, filter)
	if err != nil {
		return 0, fmt.Errorf("go-dal: mongodb: count: %w", err)
	}

	return count, nil
}

// CreateIndex creates an index on the collection.
func (m *MongoDB) CreateIndex(ctx context.Context, collection string, keys []dal.IndexKey, unique bool) error {
	coll := m.db.Collection(collection)

	sortDoc := bson.D{}
	for _, k := range keys {
		sortDoc = append(sortDoc, bson.E{Key: k.Field, Value: k.Direction})
	}

	indexModel := mongo.IndexModel{
		Keys: sortDoc,
	}

	indexOpts := options.Index().SetUnique(unique)
	indexModel.Options = indexOpts

	_, err := coll.Indexes().CreateOne(ctx, indexModel)
	if err != nil {
		return fmt.Errorf("go-dal: mongodb: create index: %w", err)
	}

	return nil
}

// Close closes the MongoDB connection.
func (m *MongoDB) Close(ctx context.Context) error {
	if err := m.conn.Disconnect(ctx); err != nil {
		return fmt.Errorf("go-dal: mongodb: disconnect: %w", err)
	}

	return nil
}
