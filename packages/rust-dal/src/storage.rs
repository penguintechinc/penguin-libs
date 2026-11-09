//! S3 and MinIO object storage abstraction matching `dal.StorageStore`.

use async_trait::async_trait;
use bytes::Bytes;
use figment::Figment;
use figment::providers::Env;
use serde::Deserialize;

use crate::error::DalError;

/// S3 / MinIO connection settings read from `S3_*` environment variables.
#[derive(Debug, Clone, Deserialize)]
pub struct S3Config {
    /// Optional custom endpoint URL (e.g. `http://localhost:9000` for MinIO).
    #[serde(default)]
    pub endpoint_url: Option<String>,
    /// AWS region (defaults to `us-east-1`).
    #[serde(default = "default_region")]
    pub region: String,
    /// Force path-style addressing (required for MinIO and local testing).
    #[serde(default = "default_force_path_style")]
    pub force_path_style: bool,
    /// Target bucket name.
    #[serde(default = "default_bucket")]
    pub bucket: String,
}

fn default_region() -> String {
    "us-east-1".to_owned()
}
fn default_force_path_style() -> bool {
    true
}
fn default_bucket() -> String {
    "penguin".to_owned()
}

impl S3Config {
    /// Loads configuration from `S3_*` prefixed environment variables via `figment`.
    pub fn from_env() -> Result<Self, DalError> {
        Figment::new()
            .merge(Env::prefixed("S3_"))
            .extract()
            .map_err(|e| DalError::Config(e.to_string()))
    }
}

/// Builds an AWS SDK S3 client honoring MinIO endpoint overrides and path-style addressing.
pub async fn build_s3_client(cfg: &S3Config) -> aws_sdk_s3::Client {
    let mut loader = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .region(aws_config::Region::new(cfg.region.clone()));
    if let Some(endpoint) = &cfg.endpoint_url {
        loader = loader.endpoint_url(endpoint);
    }
    let shared = loader.load().await;
    let s3_cfg = aws_sdk_s3::config::Builder::from(&shared)
        .force_path_style(cfg.force_path_style)
        .build();
    aws_sdk_s3::Client::from_conf(s3_cfg)
}

/// Abstract object/blob storage contract (S3, MinIO, or in-memory test mocks).
#[async_trait]
pub trait StorageStore: Send + Sync {
    /// Puts an object at `key` with optional MIME content-type.
    async fn put(&self, key: &str, data: Bytes, content_type: Option<&str>) -> Result<(), DalError>;

    /// Gets object data by `key`. Returns [`DalError::NotFound`] if absent.
    async fn get(&self, key: &str) -> Result<Bytes, DalError>;

    /// Deletes the object at `key`.
    async fn delete(&self, key: &str) -> Result<(), DalError>;

    /// Checks if an object exists at `key`.
    async fn exists(&self, key: &str) -> Result<bool, DalError>;

    /// Lists object keys matching the specified prefix.
    async fn list(&self, prefix: &str) -> Result<Vec<String>, DalError>;
}

/// S3 / MinIO implementation of [`StorageStore`].
#[derive(Clone)]
pub struct S3StorageStore {
    client: aws_sdk_s3::Client,
    bucket: String,
}

impl S3StorageStore {
    /// Creates a new S3 storage store for the given client and bucket.
    pub fn new(client: aws_sdk_s3::Client, bucket: impl Into<String>) -> Self {
        Self {
            client,
            bucket: bucket.into(),
        }
    }

    /// Creates a store from configuration.
    pub async fn from_config(cfg: &S3Config) -> Self {
        let client = build_s3_client(cfg).await;
        Self::new(client, &cfg.bucket)
    }
}

#[async_trait]
impl StorageStore for S3StorageStore {
    async fn put(&self, key: &str, data: Bytes, content_type: Option<&str>) -> Result<(), DalError> {
        let mut req = self
            .client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(data.into());

        if let Some(ct) = content_type {
            req = req.content_type(ct);
        }

        req.send()
            .await
            .map(|_| ())
            .map_err(|e| DalError::Storage(e.to_string()))
    }

    async fn get(&self, key: &str) -> Result<Bytes, DalError> {
        let resp = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| DalError::Storage(e.to_string()))?;

        resp.body
            .collect()
            .await
            .map(|d| d.into_bytes())
            .map_err(|e| DalError::Storage(e.to_string()))
    }

    async fn delete(&self, key: &str) -> Result<(), DalError> {
        self.client
            .delete_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map(|_| ())
            .map_err(|e| DalError::Storage(e.to_string()))
    }

    async fn exists(&self, key: &str) -> Result<bool, DalError> {
        match self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
        {
            Ok(_) => Ok(true),
            Err(e) => {
                let err_str = e.to_string();
                if err_str.contains("404") || err_str.contains("NotFound") {
                    Ok(false)
                } else {
                    Err(DalError::Storage(err_str))
                }
            }
        }
    }

    async fn list(&self, prefix: &str) -> Result<Vec<String>, DalError> {
        let resp = self
            .client
            .list_objects_v2()
            .bucket(&self.bucket)
            .prefix(prefix)
            .send()
            .await
            .map_err(|e| DalError::Storage(e.to_string()))?;

        let keys = resp
            .contents
            .unwrap_or_default()
            .into_iter()
            .filter_map(|obj| obj.key)
            .collect();

        Ok(keys)
    }
}
