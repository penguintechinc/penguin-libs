package cache

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-dal"
	"github.com/valkey-io/valkey-go"
)

// stubValkeyClient is a no-op implementation of valkey.Client for testing.
// All ValkeyCache methods are stubs, so we only need Close() to not panic.
type stubValkeyClient struct {
	valkey.Client
}

func (s stubValkeyClient) Close() {}

// newTestValkeyCache creates a ValkeyCache with a stub client for unit testing.
// Since all ValkeyCache operations currently return ErrUnsupportedOperation,
// no real network connection is required.
func newTestValkeyCache(prefix string) *ValkeyCache {
	return &ValkeyCache{
		cfg:    ValkeyConfig{Prefix: prefix},
		client: stubValkeyClient{},
	}
}

func TestValkeyGet(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	_, err := vc.Get(ctx, "k")
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("Get() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeySet(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	err := vc.Set(ctx, "k", []byte("v"), 0)
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("Set() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeyDelete(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	err := vc.Delete(ctx, "k")
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("Delete() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeyExists(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	_, err := vc.Exists(ctx, "k")
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("Exists() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeyIncrement(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	_, err := vc.Increment(ctx, "k", 1)
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("Increment() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeyGetMany(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	_, err := vc.GetMany(ctx, []string{"k"})
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("GetMany() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeySetMany(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	err := vc.SetMany(ctx, map[string][]byte{"k": []byte("v")}, 0)
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("SetMany() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeyFlush(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	defer vc.Close()
	ctx := context.Background()
	err := vc.Flush(ctx, "")
	if !errors.Is(err, dal.ErrUnsupportedOperation) {
		t.Errorf("Flush() = %v, want ErrUnsupportedOperation", err)
	}
}

func TestValkeyClose(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("")
	if err := vc.Close(); err != nil {
		t.Errorf("Close() error = %v", err)
	}
}

func TestValkeyKeyPrefix(t *testing.T) {
	t.Parallel()
	vc := &ValkeyCache{cfg: ValkeyConfig{Prefix: "myns"}}
	if got := vc.key("k"); got != "myns:k" {
		t.Errorf("key() = %q, want myns:k", got)
	}
	vc2 := &ValkeyCache{cfg: ValkeyConfig{Prefix: ""}}
	if got := vc2.key("k"); got != "k" {
		t.Errorf("key() no prefix = %q, want k", got)
	}
}

func TestNewValkeyCacheEmptyAddr(t *testing.T) {
	t.Parallel()
	_, err := NewValkeyCache(ValkeyConfig{InitAddress: []string{}})
	if err == nil {
		t.Errorf("NewValkeyCache() with empty addr should error")
	}
	if !errors.Is(err, dal.ErrInvalidConfiguration) {
		t.Errorf("NewValkeyCache() = %v, want ErrInvalidConfiguration", err)
	}
}

// Verify all stub methods return ErrUnsupportedOperation.
func TestValkeyAllStubsReturnUnsupported(t *testing.T) {
	t.Parallel()
	vc := newTestValkeyCache("pfx")
	defer vc.Close()
	ctx := context.Background()

	tests := []struct {
		name string
		fn   func() error
	}{
		{"Get", func() error { _, err := vc.Get(ctx, "k"); return err }},
		{"Set", func() error { return vc.Set(ctx, "k", []byte("v"), time.Minute) }},
		{"Delete", func() error { return vc.Delete(ctx, "k") }},
		{"Exists", func() error { _, err := vc.Exists(ctx, "k"); return err }},
		{"Increment", func() error { _, err := vc.Increment(ctx, "k", 1); return err }},
		{"GetMany", func() error { _, err := vc.GetMany(ctx, []string{"k"}); return err }},
		{"SetMany", func() error {
			return vc.SetMany(ctx, map[string][]byte{"k": []byte("v")}, time.Minute)
		}},
		{"Flush", func() error { return vc.Flush(ctx, "prefix") }},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			err := tt.fn()
			if !errors.Is(err, dal.ErrUnsupportedOperation) {
				t.Errorf("%s() = %v, want ErrUnsupportedOperation", tt.name, err)
			}
		})
	}
}
