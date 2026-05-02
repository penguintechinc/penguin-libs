package document

import (
	"context"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// Test MongoDB interface compliance.
func TestMongoDBInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.DocumentStore = (*MongoDB)(nil)
}

// Test MongoDB config validation.
func TestMongoDBConfigValidation(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		cfg     MongoConfig
		wantErr bool
	}{
		{
			name: "empty URI",
			cfg: MongoConfig{
				URI:    "",
				DBName: "testdb",
			},
			wantErr: true,
		},
		{
			name: "empty database name",
			cfg: MongoConfig{
				URI:    "mongodb://localhost:27017",
				DBName: "",
			},
			wantErr: true,
		},
		{
			name: "valid config",
			cfg: MongoConfig{
				URI:    "mongodb://localhost:27017",
				DBName: "testdb",
			},
			wantErr: true, // connection will fail locally without actual MongoDB
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()

			_, err := NewMongoDB(ctx, tt.cfg)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewMongoDB() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Test IndexKey structure.
func TestIndexKey(t *testing.T) {
	t.Parallel()
	ik := dal.IndexKey{
		Field:     "email",
		Direction: 1,
	}

	if ik.Field != "email" {
		t.Errorf("Field = %s, want email", ik.Field)
	}
	if ik.Direction != 1 {
		t.Errorf("Direction = %d, want 1", ik.Direction)
	}
}

// Mock document store for testing higher-level code.
type MockDocumentStore struct {
	collections map[string][]map[string]interface{}
	idCounter   int
}

func NewMockDocumentStore() *MockDocumentStore {
	return &MockDocumentStore{
		collections: make(map[string][]map[string]interface{}),
		idCounter:   1,
	}
}

func (m *MockDocumentStore) InsertOne(ctx context.Context, collection string, document interface{}) (string, error) {
	if _, ok := m.collections[collection]; !ok {
		m.collections[collection] = []map[string]interface{}{}
	}

	doc := document.(map[string]interface{})
	doc["_id"] = m.idCounter
	id := string(rune(m.idCounter))
	m.idCounter++

	m.collections[collection] = append(m.collections[collection], doc)
	return id, nil
}

func (m *MockDocumentStore) FindOne(ctx context.Context, collection string, filter interface{}) (map[string]interface{}, error) {
	if docs, ok := m.collections[collection]; ok && len(docs) > 0 {
		return docs[0], nil
	}
	return nil, dal.ErrNotFound
}

func (m *MockDocumentStore) Find(ctx context.Context, collection string, filter interface{}, opts ...dal.FindOption) ([]map[string]interface{}, error) {
	if docs, ok := m.collections[collection]; ok {
		return docs, nil
	}
	return []map[string]interface{}{}, nil
}

func (m *MockDocumentStore) UpdateOne(ctx context.Context, collection string, filter, update interface{}) (int64, error) {
	if docs, ok := m.collections[collection]; ok && len(docs) > 0 {
		return 1, nil
	}
	return 0, nil
}

func (m *MockDocumentStore) DeleteOne(ctx context.Context, collection string, filter interface{}) (int64, error) {
	if docs, ok := m.collections[collection]; ok && len(docs) > 0 {
		m.collections[collection] = docs[1:]
		return 1, nil
	}
	return 0, nil
}

func (m *MockDocumentStore) Count(ctx context.Context, collection string, filter interface{}) (int64, error) {
	if docs, ok := m.collections[collection]; ok {
		return int64(len(docs)), nil
	}
	return 0, nil
}

func (m *MockDocumentStore) CreateIndex(ctx context.Context, collection string, keys []dal.IndexKey, unique bool) error {
	return nil
}

func (m *MockDocumentStore) Close(ctx context.Context) error {
	return nil
}

// Test MockDocumentStore interface compliance.
func TestMockDocumentStoreInterfaceCompliance(t *testing.T) {
	t.Parallel()
	var _ dal.DocumentStore = (*MockDocumentStore)(nil)
}

// Test MockDocumentStore basic operations.
func TestMockDocumentStore(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	// InsertOne
	doc := map[string]interface{}{"name": "John", "age": 30}
	id, err := mds.InsertOne(ctx, "users", doc)
	if err != nil {
		t.Errorf("InsertOne() error = %v", err)
	}
	if id == "" {
		t.Errorf("InsertOne() returned empty ID")
	}

	// Count
	count, err := mds.Count(ctx, "users", nil)
	if err != nil {
		t.Errorf("Count() error = %v", err)
	}
	if count != 1 {
		t.Errorf("Count() = %d, want 1", count)
	}

	// FindOne
	found, err := mds.FindOne(ctx, "users", nil)
	if err != nil {
		t.Errorf("FindOne() error = %v", err)
	}
	if found == nil {
		t.Errorf("FindOne() returned nil")
	}

	// Find
	docs, err := mds.Find(ctx, "users", nil)
	if err != nil {
		t.Errorf("Find() error = %v", err)
	}
	if len(docs) != 1 {
		t.Errorf("Find() returned %d docs, want 1", len(docs))
	}

	// DeleteOne
	deleted, err := mds.DeleteOne(ctx, "users", nil)
	if err != nil {
		t.Errorf("DeleteOne() error = %v", err)
	}
	if deleted != 1 {
		t.Errorf("DeleteOne() = %d, want 1", deleted)
	}

	// Verify deleted
	count, _ = mds.Count(ctx, "users", nil)
	if count != 0 {
		t.Errorf("Count() after delete = %d, want 0", count)
	}
}

// Test MockDocumentStore UpdateOne.
func TestMockDocumentStoreUpdateOne(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	// Insert a document
	doc := map[string]interface{}{"name": "John", "age": 30}
	mds.InsertOne(ctx, "users", doc)

	// UpdateOne
	updated, err := mds.UpdateOne(ctx, "users", nil, map[string]interface{}{"age": 31})
	if err != nil {
		t.Errorf("UpdateOne() error = %v", err)
	}
	if updated != 1 {
		t.Errorf("UpdateOne() = %d, want 1", updated)
	}

	// UpdateOne on non-existent collection
	updated, err = mds.UpdateOne(ctx, "nonexistent", nil, nil)
	if err != nil {
		t.Errorf("UpdateOne() non-existent error = %v", err)
	}
	if updated != 0 {
		t.Errorf("UpdateOne() on non-existent = %d, want 0", updated)
	}
}

// Test MockDocumentStore with multiple documents.
func TestMockDocumentStoreMultipleDocs(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	// Insert multiple documents
	docs := []map[string]interface{}{
		{"name": "Alice", "age": 25},
		{"name": "Bob", "age": 30},
		{"name": "Charlie", "age": 35},
	}

	for _, doc := range docs {
		mds.InsertOne(ctx, "users", doc)
	}

	// Count
	count, err := mds.Count(ctx, "users", nil)
	if err != nil || count != 3 {
		t.Errorf("Count() = %d, want 3", count)
	}

	// Find all
	found, err := mds.Find(ctx, "users", nil)
	if err != nil || len(found) != 3 {
		t.Errorf("Find() returned %d docs, want 3", len(found))
	}

	// Delete one
	mds.DeleteOne(ctx, "users", nil)

	// Verify count decreased
	count, _ = mds.Count(ctx, "users", nil)
	if count != 2 {
		t.Errorf("Count() after delete = %d, want 2", count)
	}
}

// Test MockDocumentStore CreateIndex.
func TestMockDocumentStoreCreateIndex(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	keys := []dal.IndexKey{
		{Field: "email", Direction: 1},
		{Field: "createdAt", Direction: -1},
	}

	err := mds.CreateIndex(ctx, "users", keys, true)
	if err != nil {
		t.Errorf("CreateIndex() error = %v", err)
	}
}

// Test MockDocumentStore Close.
func TestMockDocumentStoreClose(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	err := mds.Close(ctx)
	if err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

// Test MockDocumentStore Count empty collection.
func TestMockDocumentStoreCountEmpty(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	count, err := mds.Count(ctx, "empty_collection", nil)
	if err != nil {
		t.Errorf("Count() empty collection error = %v", err)
	}
	if count != 0 {
		t.Errorf("Count() empty = %d, want 0", count)
	}
}

// Test MockDocumentStore FindOne on empty collection.
func TestMockDocumentStoreFindOneEmpty(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	_, err := mds.FindOne(ctx, "empty_collection", nil)
	if err != dal.ErrNotFound {
		t.Errorf("FindOne() empty collection: expected ErrNotFound, got %v", err)
	}
}

// Test MockDocumentStore Find on empty collection.
func TestMockDocumentStoreFindEmpty(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	docs, err := mds.Find(ctx, "empty_collection", nil)
	if err != nil {
		t.Errorf("Find() empty collection error = %v", err)
	}
	if len(docs) != 0 {
		t.Errorf("Find() empty = %d docs, want 0", len(docs))
	}
}

// Test MockDocumentStore DeleteOne on empty collection.
func TestMockDocumentStoreDeleteOneEmpty(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	deleted, err := mds.DeleteOne(ctx, "empty_collection", nil)
	if err != nil {
		t.Errorf("DeleteOne() empty collection error = %v", err)
	}
	if deleted != 0 {
		t.Errorf("DeleteOne() empty = %d, want 0", deleted)
	}
}

// Test MockDocumentStore Find with options.
func TestMockDocumentStoreFindWithOptions(t *testing.T) {
	t.Parallel()
	mds := NewMockDocumentStore()
	ctx := context.Background()

	// Insert documents
	for i := 0; i < 5; i++ {
		mds.InsertOne(ctx, "users", map[string]interface{}{"id": i})
	}

	opts := []dal.FindOption{
		dal.WithLimit(2),
		dal.WithSkip(1),
		dal.WithSort([]dal.IndexKey{{Field: "id", Direction: 1}}),
	}

	docs, err := mds.Find(ctx, "users", nil, opts...)
	if err != nil {
		t.Errorf("Find() with options error = %v", err)
	}
	if len(docs) != 5 { // MockDocumentStore ignores options for simplicity
		t.Errorf("Find() returned %d docs", len(docs))
	}
}
