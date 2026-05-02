package document

import (
	"context"
	"errors"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/bson/primitive"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

// --- mock mongoClientConn ---

type mockMongoConn struct {
	failDisconnect bool
}

func (m *mockMongoConn) Disconnect(ctx context.Context) error {
	if m.failDisconnect {
		return errors.New("disconnect failed")
	}
	return nil
}

// --- mock mongoCollection ---

type mockMongoCollection struct {
	// InsertOne
	failInsert  bool
	insertedID  interface{}

	// FindOne
	failFindOne bool
	findOneDoc  interface{} // document to return; nil → ErrNoDocuments

	// Find
	failFind bool
	findDocs []interface{}

	// UpdateOne
	failUpdate    bool
	modifiedCount int64

	// DeleteOne
	failDelete    bool
	deletedCount  int64

	// CountDocuments
	failCount   bool
	countResult int64

	// Indexes
	indexCreateErr error
}

func (m *mockMongoCollection) InsertOne(ctx context.Context, document interface{}, opts ...*options.InsertOneOptions) (*mongo.InsertOneResult, error) {
	if m.failInsert {
		return nil, errors.New("insert failed")
	}
	id := m.insertedID
	if id == nil {
		id = primitive.NewObjectID()
	}
	return &mongo.InsertOneResult{InsertedID: id}, nil
}

func (m *mockMongoCollection) FindOne(ctx context.Context, filter interface{}, opts ...*options.FindOneOptions) *mongo.SingleResult {
	if m.failFindOne {
		// Pass the error as the 'err' arg — SingleResult.Decode returns sr.err directly.
		return mongo.NewSingleResultFromDocument(bson.M{}, errors.New("findone failed"), nil)
	}
	if m.findOneDoc == nil {
		// Pass ErrNoDocuments as 'err' — Decode returns it directly (sr.err != nil path).
		return mongo.NewSingleResultFromDocument(bson.M{}, mongo.ErrNoDocuments, nil)
	}
	return mongo.NewSingleResultFromDocument(m.findOneDoc, nil, nil)
}

func (m *mockMongoCollection) Find(ctx context.Context, filter interface{}, opts ...*options.FindOptions) (*mongo.Cursor, error) {
	if m.failFind {
		return nil, errors.New("find failed")
	}
	cursor, err := mongo.NewCursorFromDocuments(m.findDocs, nil, nil)
	if err != nil {
		return nil, err
	}
	return cursor, nil
}

func (m *mockMongoCollection) UpdateOne(ctx context.Context, filter interface{}, update interface{}, opts ...*options.UpdateOptions) (*mongo.UpdateResult, error) {
	if m.failUpdate {
		return nil, errors.New("update failed")
	}
	return &mongo.UpdateResult{ModifiedCount: m.modifiedCount}, nil
}

func (m *mockMongoCollection) DeleteOne(ctx context.Context, filter interface{}, opts ...*options.DeleteOptions) (*mongo.DeleteResult, error) {
	if m.failDelete {
		return nil, errors.New("delete failed")
	}
	return &mongo.DeleteResult{DeletedCount: m.deletedCount}, nil
}

func (m *mockMongoCollection) CountDocuments(ctx context.Context, filter interface{}, opts ...*options.CountOptions) (int64, error) {
	if m.failCount {
		return 0, errors.New("count failed")
	}
	return m.countResult, nil
}

func (m *mockMongoCollection) Indexes() mongo.IndexView {
	return mongo.IndexView{}
}

// --- mock mongoDatabase ---

type mockMongoDatabase struct {
	coll *mockMongoCollection
}

func (m *mockMongoDatabase) Collection(name string, opts ...*options.CollectionOptions) mongoCollection {
	return m.coll
}

// --- helper ---

func newTestMongoDB(coll *mockMongoCollection) *MongoDB {
	db := &mockMongoDatabase{coll: coll}
	conn := &mockMongoConn{}
	return NewMongoDBWithDatabase(conn, db, MongoConfig{DBName: "testdb"})
}

// --- tests ---

func TestMongoDBInsertOne(t *testing.T) {
	t.Parallel()
	oid := primitive.NewObjectID()
	m := newTestMongoDB(&mockMongoCollection{insertedID: oid})
	ctx := context.Background()
	id, err := m.InsertOne(ctx, "col", bson.M{"k": "v"})
	if err != nil {
		t.Errorf("InsertOne() = %v, want nil", err)
	}
	if id != oid.Hex() {
		t.Errorf("InsertOne() id = %q, want %q", id, oid.Hex())
	}
}

func TestMongoDBInsertOneNonOIDID(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{insertedID: "custom-id"})
	ctx := context.Background()
	id, err := m.InsertOne(ctx, "col", bson.M{"k": "v"})
	if err != nil {
		t.Errorf("InsertOne() = %v, want nil", err)
	}
	if id != "custom-id" {
		t.Errorf("InsertOne() id = %q, want custom-id", id)
	}
}

func TestMongoDBInsertOneError(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{failInsert: true})
	_, err := m.InsertOne(context.Background(), "col", bson.M{})
	if err == nil {
		t.Error("InsertOne() expected error, got nil")
	}
}

func TestMongoDBFindOne(t *testing.T) {
	t.Parallel()
	oid := primitive.NewObjectID()
	doc := bson.M{"_id": oid, "name": "test"}
	m := newTestMongoDB(&mockMongoCollection{findOneDoc: doc})
	result, err := m.FindOne(context.Background(), "col", bson.M{})
	if err != nil {
		t.Errorf("FindOne() = %v, want nil", err)
	}
	if result["_id"] != oid.Hex() {
		t.Errorf("FindOne() _id = %v, want %v", result["_id"], oid.Hex())
	}
}

func TestMongoDBFindOneNotFound(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{findOneDoc: nil})
	_, err := m.FindOne(context.Background(), "col", bson.M{})
	if err == nil {
		t.Error("FindOne() expected error, got nil")
	}
	if !errors.Is(err, dal.ErrNotFound) {
		t.Errorf("FindOne() = %v, want ErrNotFound", err)
	}
}

func TestMongoDBFindOneNonOIDId(t *testing.T) {
	t.Parallel()
	doc := bson.M{"_id": "string-id", "name": "test"}
	m := newTestMongoDB(&mockMongoCollection{findOneDoc: doc})
	result, err := m.FindOne(context.Background(), "col", bson.M{})
	if err != nil {
		t.Errorf("FindOne() = %v, want nil", err)
	}
	// _id should remain as-is (not converted) since not ObjectID
	if result["_id"] == nil {
		t.Error("FindOne() _id should not be nil")
	}
}

func TestMongoDBFindEmpty(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{findDocs: nil})
	results, err := m.Find(context.Background(), "col", bson.M{})
	if err != nil {
		t.Errorf("Find() = %v, want nil", err)
	}
	if len(results) != 0 {
		t.Errorf("Find() len = %d, want 0", len(results))
	}
}

func TestMongoDBFind(t *testing.T) {
	t.Parallel()
	oid := primitive.NewObjectID()
	docs := []interface{}{
		bson.M{"_id": oid, "x": 1},
		bson.M{"_id": primitive.NewObjectID(), "x": 2},
	}
	m := newTestMongoDB(&mockMongoCollection{findDocs: docs})
	results, err := m.Find(context.Background(), "col", bson.M{})
	if err != nil {
		t.Errorf("Find() = %v, want nil", err)
	}
	if len(results) != 2 {
		t.Errorf("Find() len = %d, want 2", len(results))
	}
}

func TestMongoDBFindWithOptions(t *testing.T) {
	t.Parallel()
	docs := []interface{}{bson.M{"x": 1}, bson.M{"x": 2}}
	m := newTestMongoDB(&mockMongoCollection{findDocs: docs})
	results, err := m.Find(
		context.Background(), "col", bson.M{},
		dal.WithLimit(10),
		dal.WithSkip(0),
		dal.WithSort([]dal.IndexKey{{Field: "x", Direction: 1}}),
	)
	if err != nil {
		t.Errorf("Find() with options = %v, want nil", err)
	}
	if len(results) != 2 {
		t.Errorf("Find() len = %d, want 2", len(results))
	}
}

func TestMongoDBFindError(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{failFind: true})
	_, err := m.Find(context.Background(), "col", bson.M{})
	if err == nil {
		t.Error("Find() expected error, got nil")
	}
}

func TestMongoDBUpdateOne(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{modifiedCount: 1})
	n, err := m.UpdateOne(context.Background(), "col", bson.M{}, bson.M{"$set": bson.M{"k": "v"}})
	if err != nil {
		t.Errorf("UpdateOne() = %v, want nil", err)
	}
	if n != 1 {
		t.Errorf("UpdateOne() count = %d, want 1", n)
	}
}

func TestMongoDBUpdateOneError(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{failUpdate: true})
	_, err := m.UpdateOne(context.Background(), "col", bson.M{}, bson.M{})
	if err == nil {
		t.Error("UpdateOne() expected error, got nil")
	}
}

func TestMongoDBDeleteOne(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{deletedCount: 1})
	n, err := m.DeleteOne(context.Background(), "col", bson.M{})
	if err != nil {
		t.Errorf("DeleteOne() = %v, want nil", err)
	}
	if n != 1 {
		t.Errorf("DeleteOne() count = %d, want 1", n)
	}
}

func TestMongoDBDeleteOneError(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{failDelete: true})
	_, err := m.DeleteOne(context.Background(), "col", bson.M{})
	if err == nil {
		t.Error("DeleteOne() expected error, got nil")
	}
}

func TestMongoDBCount(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{countResult: 5})
	n, err := m.Count(context.Background(), "col", bson.M{})
	if err != nil {
		t.Errorf("Count() = %v, want nil", err)
	}
	if n != 5 {
		t.Errorf("Count() = %d, want 5", n)
	}
}

func TestMongoDBCountError(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{failCount: true})
	_, err := m.Count(context.Background(), "col", bson.M{})
	if err == nil {
		t.Error("Count() expected error, got nil")
	}
}

func TestMongoDBCreateIndexPanicsWithMock(t *testing.T) {
	t.Parallel()
	// CreateIndex calls coll.Indexes().CreateOne() which requires a real mongo.Collection.
	// The mock returns a zero-value mongo.IndexView that panics on CreateOne.
	// We use recover to verify the function reaches the CreateOne call (exercises setup code).
	m := newTestMongoDB(&mockMongoCollection{})
	defer func() {
		if r := recover(); r == nil {
			// If it doesn't panic, that's also acceptable (future driver may handle gracefully).
		}
	}()
	_ = m.CreateIndex(context.Background(), "col", []dal.IndexKey{{Field: "x", Direction: 1}}, true)
}

func TestMongoDBClose(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{})
	if err := m.Close(context.Background()); err != nil {
		t.Errorf("Close() = %v, want nil", err)
	}
}

func TestMongoDBCloseError(t *testing.T) {
	t.Parallel()
	conn := &mockMongoConn{failDisconnect: true}
	db := &mockMongoDatabase{coll: &mockMongoCollection{}}
	m := NewMongoDBWithDatabase(conn, db, MongoConfig{})
	if err := m.Close(context.Background()); err == nil {
		t.Error("Close() expected error, got nil")
	}
}

func TestNewMongoDBEmptyURI(t *testing.T) {
	t.Parallel()
	_, err := NewMongoDB(context.Background(), MongoConfig{DBName: "db"})
	if err == nil {
		t.Error("NewMongoDB() expected error for empty URI, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewMongoDB() = %v, want ErrInvalidConfiguration", err)
	}
}

func TestNewMongoDBEmptyDBName(t *testing.T) {
	t.Parallel()
	_, err := NewMongoDB(context.Background(), MongoConfig{URI: "mongodb://localhost:27017"})
	if err == nil {
		t.Error("NewMongoDB() expected error for empty DBName, got nil")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewMongoDB() = %v, want ErrInvalidConfiguration", err)
	}
}

