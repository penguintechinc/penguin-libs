package document

import (
	"errors"
	"fmt"
	"strings"

	"go.mongodb.org/mongo-driver/bson"
)

// ErrUnsafeFilter is returned when a filter contains an operator that can run
// server-side code or is not allowed at the top level. Filters built from
// request input must not contain these; wrap a filter in Trusted only when the
// filter is authored by the application itself.
var ErrUnsafeFilter = errors.New("dal: unsafe filter")

// Trusted wraps a filter that the application authored itself, bypassing the
// operator screening applied to every other filter (for example, a $where
// clause). Never wrap a filter built from untrusted input.
func Trusted(filter interface{}) TrustedFilter {
	return TrustedFilter{Filter: filter}
}

// TrustedFilter marks a filter as application-authored; see Trusted.
type TrustedFilter struct {
	Filter interface{}
}

// forbiddenOperators may never appear in a filter at any depth, because they
// execute JavaScript on the server.
var forbiddenOperators = map[string]bool{
	"$where":       true,
	"$function":    true,
	"$accumulator": true,
}

// logicalOperators are the only operators allowed at the top level of a filter.
// Their operands are still screened recursively.
var logicalOperators = map[string]bool{
	"$and": true,
	"$or":  true,
	"$nor": true,
}

// validateFilter screens a filter for operator injection and returns the filter
// to pass to the driver. A nil filter is passed through unchanged. Operators
// in value position (for example {"age": {"$gt": 3}}) remain allowed.
func validateFilter(filter interface{}) (interface{}, error) {
	if tf, ok := filter.(TrustedFilter); ok {
		return tf.Filter, nil
	}
	if filter == nil {
		return nil, nil
	}

	raw, err := bson.Marshal(filter)
	if err != nil {
		return nil, fmt.Errorf("go-dal: mongodb: encode filter: %w", err)
	}
	if err := checkFilterDoc(bson.Raw(raw), true); err != nil {
		return nil, err
	}
	return filter, nil
}

// validateUpdate screens an update document or aggregation-pipeline update
// for server-side JavaScript operators ($function, $accumulator, $where) at any
// depth. Ordinary update operators ($set, $inc, ...) and pipeline stages remain
// allowed. A nil update is passed through unchanged; Trusted bypasses screening.
func validateUpdate(update interface{}) (interface{}, error) {
	if tf, ok := update.(TrustedFilter); ok {
		return tf.Filter, nil
	}
	if update == nil {
		return nil, nil
	}

	bsonType, data, err := bson.MarshalValue(update)
	if err != nil {
		return nil, fmt.Errorf("go-dal: mongodb: encode update: %w", err)
	}
	if err := checkFilterValue(bson.RawValue{Type: bsonType, Value: data}); err != nil {
		return nil, err
	}
	return update, nil
}

// checkFilterDoc walks a BSON document recursively and rejects forbidden
// operators at any depth and non-logical operators at the top level.
func checkFilterDoc(doc bson.Raw, top bool) error {
	elems, err := doc.Elements()
	if err != nil {
		return fmt.Errorf("go-dal: mongodb: decode filter: %w", err)
	}
	for _, el := range elems {
		key := el.Key()
		if strings.HasPrefix(key, "$") {
			if forbiddenOperators[key] {
				return fmt.Errorf("go-dal: mongodb: %w: operator %s not allowed", ErrUnsafeFilter, key)
			}
			if top && !logicalOperators[key] {
				return fmt.Errorf("go-dal: mongodb: %w: top-level operator %s not allowed", ErrUnsafeFilter, key)
			}
		}
		if err := checkFilterValue(el.Value()); err != nil {
			return err
		}
	}
	return nil
}

// checkFilterValue recurses into embedded documents and arrays.
func checkFilterValue(v bson.RawValue) error {
	switch v.Type {
	case bson.TypeEmbeddedDocument:
		return checkFilterDoc(v.Document(), false)
	case bson.TypeArray:
		vals, err := v.Array().Values()
		if err != nil {
			return fmt.Errorf("go-dal: mongodb: decode filter array: %w", err)
		}
		for _, item := range vals {
			if err := checkFilterValue(item); err != nil {
				return err
			}
		}
	}
	return nil
}
