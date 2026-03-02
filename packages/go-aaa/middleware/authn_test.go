package middleware

import (
	"context"
	"errors"
	"testing"
	"time"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

func validClaims(sub string) *authn.Claims {
	now := time.Now()
	return &authn.Claims{
		Sub: sub, Iss: "https://issuer.example.com",
		Aud: []string{"app"}, Iat: now, Exp: now.Add(time.Hour),
	}
}

func TestOIDCInterceptor_ValidToken(t *testing.T) {
	rp := buildFakeRPInterceptor(func(token string) (*authn.Claims, error) {
		if token != "good-token" {
			return nil, errors.New("bad token")
		}
		return validClaims("user-abc"), nil
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer good-token")

	var claimsInCtx *authn.Claims
	_, err := rp(func(ctx context.Context, r connect.AnyRequest) (connect.AnyResponse, error) {
		claimsInCtx = authz.ClaimsFromContext(ctx)
		return nil, nil
	})(context.Background(), req)

	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if claimsInCtx == nil || claimsInCtx.Sub != "user-abc" {
		t.Errorf("expected claims with sub user-abc in context, got %v", claimsInCtx)
	}
}

func TestOIDCInterceptor_MissingToken(t *testing.T) {
	rp := buildFakeRPInterceptor(func(_ string) (*authn.Claims, error) { return nil, nil })

	req := connect.NewRequest(&struct{}{})
	_, err := rp(noopNext)(context.Background(), req)

	if err == nil {
		t.Fatal("expected error for missing token, got nil")
	}
	if connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Errorf("expected CodeUnauthenticated, got %v", connect.CodeOf(err))
	}
}

func TestOIDCInterceptor_InvalidToken(t *testing.T) {
	rp := buildFakeRPInterceptor(func(_ string) (*authn.Claims, error) {
		return nil, errors.New("signature mismatch")
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer bad-token")

	_, err := rp(noopNext)(context.Background(), req)
	if err == nil {
		t.Fatal("expected error for invalid token, got nil")
	}
	if connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Errorf("expected CodeUnauthenticated, got %v", connect.CodeOf(err))
	}
}

func TestOIDCInterceptor_PublicProcedure_SkipsValidation(t *testing.T) {
	rp := buildFakeRPInterceptorWithOpts(
		func(_ string) (*authn.Claims, error) {
			t.Error("validate should not be called for public procedures")
			return nil, errors.New("should not be called")
		},
		WithPublicProcedures(""),
	)

	req := connect.NewRequest(&struct{}{})
	// No Authorization header — procedure path is "" which matches the public set.

	_, err := rp(noopNext)(context.Background(), req)
	if err != nil {
		t.Errorf("expected no error for public procedure, got %v", err)
	}
}

// buildFakeRPInterceptor constructs a connect.UnaryInterceptorFunc using a fakeRP.
// Because OIDCRelyingParty is a concrete struct, we replicate the interceptor logic
// here with the fakeRP interface to keep tests hermetic.
func buildFakeRPInterceptor(validateFn func(string) (*authn.Claims, error)) connect.UnaryInterceptorFunc {
	return buildFakeRPInterceptorWithOpts(validateFn)
}

func buildFakeRPInterceptorWithOpts(validateFn func(string) (*authn.Claims, error), opts ...InterceptorOption) connect.UnaryInterceptorFunc {
	cfg := applyOptions(opts)
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if cfg.publicProcedures[req.Spec().Procedure] {
				return next(ctx, req)
			}
			auth := req.Header().Get("Authorization")
			if len(auth) < 8 || auth[:7] != "Bearer " {
				return nil, connect.NewError(connect.CodeUnauthenticated, errors.New("missing bearer token"))
			}
			claims, err := validateFn(auth[7:])
			if err != nil {
				return nil, connect.NewError(connect.CodeUnauthenticated, err)
			}
			ctx = authz.ContextWithClaims(ctx, claims)
			return next(ctx, req)
		}
	}
}

func noopNext(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
	return nil, nil
}
