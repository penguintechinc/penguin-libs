package storage

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"path"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/penguintechinc/penguin-libs/packages/go-dal"
)

// s3ObjectClient is the subset of *s3.Client operations used by S3Store.
type s3ObjectClient interface {
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	DeleteObject(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
	HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	NewListObjectsV2Paginator(params *s3.ListObjectsV2Input) s3PageIterator
}

// s3PageIterator abstracts the ListObjectsV2Paginator for testability.
type s3PageIterator interface {
	HasMorePages() bool
	NextPage(ctx context.Context, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

// s3PresignClient is the subset of *s3.PresignClient operations used by S3Store.
type s3PresignClient interface {
	PresignGetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.PresignOptions)) (*s3PresignResult, error)
}

// s3PresignResult holds the URL returned by presigning.
type s3PresignResult struct {
	URL string
}

// realS3Client wraps *s3.Client to implement s3ObjectClient.
type realS3Client struct {
	inner *s3.Client
}

func (r *realS3Client) PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	return r.inner.PutObject(ctx, params, optFns...)
}

func (r *realS3Client) GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	return r.inner.GetObject(ctx, params, optFns...)
}

func (r *realS3Client) DeleteObject(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error) {
	return r.inner.DeleteObject(ctx, params, optFns...)
}

func (r *realS3Client) HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	return r.inner.HeadObject(ctx, params, optFns...)
}

func (r *realS3Client) NewListObjectsV2Paginator(params *s3.ListObjectsV2Input) s3PageIterator {
	return s3.NewListObjectsV2Paginator(r.inner, params)
}

// realS3PresignClient wraps *s3.PresignClient to implement s3PresignClient.
type realS3PresignClient struct {
	inner *s3.PresignClient
}

func (r *realS3PresignClient) PresignGetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.PresignOptions)) (*s3PresignResult, error) {
	result, err := r.inner.PresignGetObject(ctx, params, optFns...)
	if err != nil {
		return nil, err
	}
	return &s3PresignResult{URL: result.URL}, nil
}

// S3Config configures an S3 storage backend.
type S3Config struct {
	Bucket      string
	Region      string
	AccessKey   string
	SecretKey   string
	EndpointURL string
	Prefix      string
}

// S3Store implements dal.StorageStore for AWS S3.
type S3Store struct {
	cfg     S3Config
	client  s3ObjectClient
	presign s3PresignClient
}

// NewS3Store creates a new S3 storage backend.
func NewS3Store(ctx context.Context, cfg S3Config) (*S3Store, error) {
	if cfg.Bucket == "" {
		return nil, fmt.Errorf("go-dal: s3: %w: bucket required", dal.ErrInvalidConfiguration)
	}
	if cfg.Region == "" {
		return nil, fmt.Errorf("go-dal: s3: %w: region required", dal.ErrInvalidConfiguration)
	}

	awsOpts := []func(*config.LoadOptions) error{
		config.WithRegion(cfg.Region),
	}

	if cfg.AccessKey != "" && cfg.SecretKey != "" {
		awsOpts = append(awsOpts, config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(
			cfg.AccessKey, cfg.SecretKey, "",
		)))
	}

	awsCfg, err := config.LoadDefaultConfig(ctx, awsOpts...)
	if err != nil {
		return nil, fmt.Errorf("go-dal: s3: load config: %w", err)
	}

	rawClient := s3.NewFromConfig(awsCfg)
	rawPresign := s3.NewPresignClient(rawClient)

	store := &S3Store{
		cfg:     cfg,
		client:  &realS3Client{inner: rawClient},
		presign: &realS3PresignClient{inner: rawPresign},
	}

	return store, nil
}

// NewS3StoreWithClient creates an S3Store using injected clients (for testing).
func NewS3StoreWithClient(client s3ObjectClient, presign s3PresignClient, cfg S3Config) *S3Store {
	return &S3Store{
		cfg:     cfg,
		client:  client,
		presign: presign,
	}
}

// Put writes data to S3.
func (s *S3Store) Put(ctx context.Context, key string, data []byte, opts ...dal.PutOption) error {
	po := &dal.PutOptions{}
	for _, opt := range opts {
		opt(po)
	}

	fullKey := path.Join(s.cfg.Prefix, key)
	input := &s3.PutObjectInput{
		Bucket: aws.String(s.cfg.Bucket),
		Key:    aws.String(fullKey),
		Body:   bytes.NewReader(data),
	}

	if po.ContentType != "" {
		input.ContentType = aws.String(po.ContentType)
	}
	if po.CacheControl != "" {
		input.CacheControl = aws.String(po.CacheControl)
	}
	if len(po.Metadata) > 0 {
		input.Metadata = po.Metadata
	}

	_, err := s.client.PutObject(ctx, input)
	if err != nil {
		return fmt.Errorf("go-dal: s3: put: %w", err)
	}

	return nil
}

// Get retrieves data from S3.
func (s *S3Store) Get(ctx context.Context, key string) ([]byte, error) {
	fullKey := path.Join(s.cfg.Prefix, key)
	input := &s3.GetObjectInput{
		Bucket: aws.String(s.cfg.Bucket),
		Key:    aws.String(fullKey),
	}

	output, err := s.client.GetObject(ctx, input)
	if err != nil {
		var nsk *types.NoSuchKey
		if _, ok := err.(*types.NoSuchKey); ok || nsk != nil {
			return nil, fmt.Errorf("go-dal: s3: get: %w", dal.ErrNotFound)
		}
		return nil, fmt.Errorf("go-dal: s3: get: %w", err)
	}
	defer output.Body.Close()

	data, err := io.ReadAll(output.Body)
	if err != nil {
		return nil, fmt.Errorf("go-dal: s3: get read: %w", err)
	}

	return data, nil
}

// Delete removes an object from S3.
func (s *S3Store) Delete(ctx context.Context, key string) error {
	fullKey := path.Join(s.cfg.Prefix, key)
	input := &s3.DeleteObjectInput{
		Bucket: aws.String(s.cfg.Bucket),
		Key:    aws.String(fullKey),
	}

	_, err := s.client.DeleteObject(ctx, input)
	if err != nil {
		return fmt.Errorf("go-dal: s3: delete: %w", err)
	}

	return nil
}

// Exists checks if an object exists in S3.
func (s *S3Store) Exists(ctx context.Context, key string) (bool, error) {
	fullKey := path.Join(s.cfg.Prefix, key)
	input := &s3.HeadObjectInput{
		Bucket: aws.String(s.cfg.Bucket),
		Key:    aws.String(fullKey),
	}

	_, err := s.client.HeadObject(ctx, input)
	if err != nil {
		var nsk *types.NoSuchKey
		if _, ok := err.(*types.NoSuchKey); ok || nsk != nil {
			return false, nil
		}
		return false, fmt.Errorf("go-dal: s3: exists: %w", err)
	}

	return true, nil
}

// List returns all objects with a given prefix.
func (s *S3Store) List(ctx context.Context, prefix string) ([]string, error) {
	fullPrefix := path.Join(s.cfg.Prefix, prefix)
	var keys []string
	paginator := s.client.NewListObjectsV2Paginator(&s3.ListObjectsV2Input{
		Bucket: aws.String(s.cfg.Bucket),
		Prefix: aws.String(fullPrefix),
	})

	for paginator.HasMorePages() {
		output, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("go-dal: s3: list: %w", err)
		}

		for _, obj := range output.Contents {
			keys = append(keys, *obj.Key)
		}
	}

	return keys, nil
}

// GetURL generates a presigned URL for temporary access.
func (s *S3Store) GetURL(ctx context.Context, key string, expiresIn time.Duration) (string, error) {
	fullKey := path.Join(s.cfg.Prefix, key)
	input := &s3.GetObjectInput{
		Bucket: aws.String(s.cfg.Bucket),
		Key:    aws.String(fullKey),
	}

	presignOptFn := func(opts *s3.PresignOptions) {
		opts.Expires = expiresIn
	}

	result, err := s.presign.PresignGetObject(ctx, input, presignOptFn)
	if err != nil {
		return "", fmt.Errorf("go-dal: s3: presign: %w", err)
	}

	return result.URL, nil
}

// Close closes the S3 client (no-op, client is stateless).
func (s *S3Store) Close() error {
	return nil
}
