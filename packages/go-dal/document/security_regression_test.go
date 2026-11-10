package document

import (
	"context"
	"errors"
	"testing"

	"go.mongodb.org/mongo-driver/bson"
)

// unsafeFilters are filters that must be rejected unless wrapped in Trusted.
var unsafeFilters = map[string]interface{}{
	"top-level $where":           bson.M{"$where": "sleep(1000)"},
	"top-level $function":        bson.M{"$function": bson.M{"body": "x"}},
	"nested $where":              bson.M{"name": bson.M{"$where": "x"}},
	"$where inside $or":          bson.M{"$or": []bson.M{{"$where": "x"}}},
	"$accumulator in array":      bson.M{"$and": []interface{}{bson.M{"a": bson.M{"$accumulator": "x"}}}},
	"bson.D nested $function":    bson.D{{Key: "a", Value: bson.D{{Key: "$function", Value: "x"}}}},
	"unknown top-level operator": bson.M{"$expr": bson.M{"$eq": bson.A{1, 1}}},
}

// TestValidateFilterRejectsUnsafe is a regression test for SEC-GO-07 NoSQL operator injection.
func TestValidateFilterRejectsUnsafe(t *testing.T) {
	t.Parallel()
	for name, f := range unsafeFilters {
		t.Run(name, func(t *testing.T) {
			if _, err := validateFilter(f); !errors.Is(err, ErrUnsafeFilter) {
				t.Errorf("validateFilter() error = %v, want ErrUnsafeFilter", err)
			}
		})
	}
}

// TestValidateFilterAcceptsSafe guards against breaking safe callers.
func TestValidateFilterAcceptsSafe(t *testing.T) {
	t.Parallel()
	safe := map[string]interface{}{
		"equality":        bson.M{"name": "alice", "tenant": "t1"},
		"value operator":  bson.M{"age": bson.M{"$gt": 3}, "tags": bson.M{"$in": []string{"a"}}},
		"top-level $and":  bson.M{"$and": []bson.M{{"a": 1}, {"b": bson.M{"$lt": 2}}}},
		"top-level $or":   bson.M{"$or": []bson.M{{"a": 1}, {"a": 2}}},
		"bson.D equality": bson.D{{Key: "name", Value: "bob"}},
		"nil filter":      nil,
		"empty filter":    bson.M{},
		"struct equality": struct {
			Name string `bson:"name"`
		}{Name: "x"},
	}
	for name, f := range safe {
		t.Run(name, func(t *testing.T) {
			if _, err := validateFilter(f); err != nil {
				t.Errorf("validateFilter() error = %v, want nil", err)
			}
		})
	}
}

// TestValidateFilterTrustedBypass verifies the explicit trusted option.
func TestValidateFilterTrustedBypass(t *testing.T) {
	t.Parallel()
	inner := bson.M{"$where": "trusted()"}
	got, err := validateFilter(Trusted(inner))
	if err != nil {
		t.Fatalf("validateFilter(Trusted) error = %v", err)
	}
	if m, ok := got.(bson.M); !ok || m["$where"] != "trusted()" {
		t.Errorf("validateFilter(Trusted) returned %#v, want unwrapped filter", got)
	}
}

// TestValidateFilterMarshalError ensures unencodable filters fail loudly.
func TestValidateFilterMarshalError(t *testing.T) {
	t.Parallel()
	if _, err := validateFilter(bson.M{"ch": make(chan int)}); err == nil {
		t.Error("validateFilter() with unencodable value returned nil error")
	}
}

// TestStoreOpsRejectUnsafeFilter confirms every filter-taking operation enforces the check.
func TestStoreOpsRejectUnsafeFilter(t *testing.T) {
	t.Parallel()
	ctx := context.Background()
	bad := bson.M{"$where": "x"}

	m := newTestMongoDB(&mockMongoCollection{})
	if _, err := m.FindOne(ctx, "c", bad); !errors.Is(err, ErrUnsafeFilter) {
		t.Errorf("FindOne error = %v, want ErrUnsafeFilter", err)
	}
	if _, err := m.Find(ctx, "c", bad); !errors.Is(err, ErrUnsafeFilter) {
		t.Errorf("Find error = %v, want ErrUnsafeFilter", err)
	}
	if _, err := m.UpdateOne(ctx, "c", bad, bson.M{"$set": bson.M{"a": 1}}); !errors.Is(err, ErrUnsafeFilter) {
		t.Errorf("UpdateOne error = %v, want ErrUnsafeFilter", err)
	}
	if _, err := m.DeleteOne(ctx, "c", bad); !errors.Is(err, ErrUnsafeFilter) {
		t.Errorf("DeleteOne error = %v, want ErrUnsafeFilter", err)
	}
	if _, err := m.Count(ctx, "c", bad); !errors.Is(err, ErrUnsafeFilter) {
		t.Errorf("Count error = %v, want ErrUnsafeFilter", err)
	}
}

// unsafeUpdates are update documents/pipelines that must be rejected unless wrapped in Trusted.
var unsafeUpdates = map[string]interface{}{
	"$function in $set":         bson.M{"$set": bson.M{"a": bson.M{"$function": bson.M{"body": "x"}}}},
	"$accumulator in $set":      bson.M{"$set": bson.M{"a": bson.M{"$accumulator": bson.M{}}}},
	"$where in update":          bson.M{"$where": "x"},
	"pipeline $function":        []bson.M{{"$set": bson.M{"a": bson.M{"$function": bson.M{"body": "x"}}}}},
	"pipeline bson.A deep":      bson.A{bson.M{"$replaceWith": bson.M{"x": bson.A{bson.M{"$accumulator": 1}}}}},
	"pipeline bson.D $function": bson.A{bson.D{{Key: "$set", Value: bson.D{{Key: "a", Value: bson.D{{Key: "$function", Value: "x"}}}}}}},
	"deeply nested $set $where": bson.M{"$set": bson.M{"a": bson.M{"b": bson.M{"c": bson.M{"$where": "x"}}}}},
}

// TestValidateUpdateRejectsUnsafe is a regression test: UpdateOne passed update documents (incl. pipeline form) unscreened.
func TestValidateUpdateRejectsUnsafe(t *testing.T) {
	t.Parallel()
	for name, u := range unsafeUpdates {
		t.Run(name, func(t *testing.T) {
			if _, err := validateUpdate(u); !errors.Is(err, ErrUnsafeFilter) {
				t.Errorf("validateUpdate() error = %v, want ErrUnsafeFilter", err)
			}
		})
	}
}

// TestValidateUpdateAcceptsSafe guards ordinary update operators and pipelines.
func TestValidateUpdateAcceptsSafe(t *testing.T) {
	t.Parallel()
	safe := map[string]interface{}{
		"$set":      bson.M{"$set": bson.M{"a": 1}, "$inc": bson.M{"n": 1}},
		"pipeline":  []bson.M{{"$set": bson.M{"a": bson.M{"$add": bson.A{"$a", 1}}}}},
		"$push doc": bson.M{"$push": bson.M{"tags": bson.M{"$each": []string{"x"}}}},
	}
	for name, u := range safe {
		t.Run(name, func(t *testing.T) {
			if _, err := validateUpdate(u); err != nil {
				t.Errorf("validateUpdate() error = %v, want nil", err)
			}
		})
	}
}

// TestValidateUpdateTrustedBypassAndErrors covers the Trusted pass-through and unencodable updates.
func TestValidateUpdateTrustedBypassAndErrors(t *testing.T) {
	t.Parallel()
	inner := bson.M{"$set": bson.M{"a": bson.M{"$function": "x"}}}
	got, err := validateUpdate(Trusted(inner))
	if err != nil {
		t.Fatalf("validateUpdate(Trusted) error = %v", err)
	}
	if _, ok := got.(bson.M); !ok {
		t.Errorf("validateUpdate(Trusted) returned %#v, want unwrapped update", got)
	}
	if _, err := validateUpdate(bson.M{"$set": bson.M{"ch": make(chan int)}}); err == nil {
		t.Error("validateUpdate() with unencodable value returned nil error")
	}
	if got, err := validateUpdate(nil); err != nil || got != nil {
		t.Errorf("validateUpdate(nil) = %v, %v; want nil, nil", got, err)
	}
}

// TestUpdateOneRejectsUnsafeUpdate confirms UpdateOne enforces the update screening end to end.
func TestUpdateOneRejectsUnsafeUpdate(t *testing.T) {
	t.Parallel()
	m := newTestMongoDB(&mockMongoCollection{})
	_, err := m.UpdateOne(context.Background(), "c", bson.M{"a": 1},
		[]bson.M{{"$set": bson.M{"x": bson.M{"$function": bson.M{"body": "x"}}}}})
	if !errors.Is(err, ErrUnsafeFilter) {
		t.Errorf("UpdateOne error = %v, want ErrUnsafeFilter", err)
	}
}
