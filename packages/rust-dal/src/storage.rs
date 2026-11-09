//! S3 and MinIO object storage abstraction matching `dal.StorageStore`.

use std::fmt;

use async_trait::async_trait;
use aws_sdk_s3::error::SdkError;
use bytes::{Bytes, BytesMut};
use figment::providers::Env;
use figment::Figment;
use serde::Deserialize;

use crate::error::DalError;

/// Default cap on a single `get()` object: 64 MiB.
pub const DEFAULT_MAX_OBJECT_BYTES: u64 = 64 * 1024 * 1024;

/// S3 / MinIO connection settings read from `S3_*` environment variables.
///
/// `Debug` is implemented manually and redacts credentials embedded in `endpoint_url`.
#[derive(Clone, Deserialize)]
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
    /// Maximum bytes `get()` will buffer (`S3_MAX_OBJECT_BYTES`), default 64 MiB.
    #[serde(default = "default_max_object_bytes")]
    pub max_object_bytes: u64,
}

impl fmt::Debug for S3Config {
    /// Formats the config with URL userinfo and query string redacted.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("S3Config")
            .field(
                "endpoint_url",
                &self.endpoint_url.as_deref().map(redact_url),
            )
            .field("region", &self.region)
            .field("force_path_style", &self.force_path_style)
            .field("bucket", &self.bucket)
            .field("max_object_bytes", &self.max_object_bytes)
            .finish()
    }
}

/// Placeholder returned by [`redact_url`] when the input cannot be parsed as a URL.
const REDACTED_URL: &str = "[REDACTED-URL]";

/// Redacts userinfo, query and fragment from a URL for safe display.
///
/// Parses with [`url::Url`] so delimiter characters inside credentials cannot
/// split the string early; unparseable input yields a fixed placeholder and is
/// never echoed, since it may itself contain a secret.
pub(crate) fn redact_url(raw: &str) -> String {
    match url::Url::parse(raw) {
        Ok(mut u) => {
            // set_username/set_password only fail for cannot-be-a-base URLs; clear the rest regardless.
            if u.set_username("").is_err() || u.set_password(None).is_err() {
                return REDACTED_URL.to_owned();
            }
            u.set_query(None);
            u.set_fragment(None);
            u.to_string()
        }
        Err(_) => REDACTED_URL.to_owned(),
    }
}

fn default_max_object_bytes() -> u64 {
    DEFAULT_MAX_OBJECT_BYTES
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
        Self::from_figment(Figment::new().merge(Env::prefixed("S3_")))
    }

    /// Extracts a config from any figment source.
    pub(crate) fn from_figment(fig: Figment) -> Result<Self, DalError> {
        fig.extract().map_err(|e| DalError::Config(e.to_string()))
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
    async fn put(&self, key: &str, data: Bytes, content_type: Option<&str>)
        -> Result<(), DalError>;

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
    max_object_bytes: u64,
}

/// Accumulates body chunks while enforcing a hard byte cap.
struct CappedBuffer {
    buf: BytesMut,
    limit: u64,
}

impl CappedBuffer {
    /// Creates an empty buffer that refuses to grow past `limit` bytes.
    fn new(limit: u64) -> Self {
        Self {
            buf: BytesMut::new(),
            limit,
        }
    }

    /// Appends a chunk, failing with [`DalError::TooLarge`] if the cap would be exceeded.
    fn push(&mut self, chunk: &[u8]) -> Result<(), DalError> {
        let next = (self.buf.len() as u64).saturating_add(chunk.len() as u64);
        if next > self.limit {
            return Err(DalError::TooLarge { limit: self.limit });
        }
        self.buf.extend_from_slice(chunk);
        Ok(())
    }

    /// Returns the accumulated bytes.
    fn finish(self) -> Bytes {
        self.buf.freeze()
    }
}

/// Rejects an object whose declared `Content-Length` already exceeds `limit`.
fn check_declared_len(declared: Option<i64>, limit: u64) -> Result<(), DalError> {
    match declared {
        Some(n) if u64::try_from(n).map_or(true, |n| n > limit) => {
            Err(DalError::TooLarge { limit })
        }
        _ => Ok(()),
    }
}

impl S3StorageStore {
    /// Creates a new S3 storage store for the given client and bucket.
    pub fn new(client: aws_sdk_s3::Client, bucket: impl Into<String>) -> Self {
        Self {
            client,
            bucket: bucket.into(),
            max_object_bytes: DEFAULT_MAX_OBJECT_BYTES,
        }
    }

    /// Overrides the maximum number of bytes `get()` will buffer.
    pub fn with_max_object_bytes(mut self, max: u64) -> Self {
        self.max_object_bytes = max;
        self
    }

    /// Creates a store from configuration, honoring `max_object_bytes`.
    pub async fn from_config(cfg: &S3Config) -> Self {
        let client = build_s3_client(cfg).await;
        Self::new(client, &cfg.bucket).with_max_object_bytes(cfg.max_object_bytes)
    }
}

/// True when a `HeadObject` failure is the typed not-found error (or a raw HTTP 404).
fn head_is_not_found(e: &SdkError<aws_sdk_s3::operation::head_object::HeadObjectError>) -> bool {
    match e.as_service_error() {
        Some(se) => se.is_not_found(),
        None => e.raw_response().is_some_and(|r| r.status().as_u16() == 404),
    }
}

#[async_trait]
impl StorageStore for S3StorageStore {
    async fn put(
        &self,
        key: &str,
        data: Bytes,
        content_type: Option<&str>,
    ) -> Result<(), DalError> {
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
            .map_err(|e| match e.as_service_error() {
                Some(se) if se.is_no_such_key() => DalError::NotFound(key.to_owned()),
                _ => DalError::Storage(e.to_string()),
            })?;

        check_declared_len(resp.content_length, self.max_object_bytes)?;
        let mut body = resp.body;
        let mut buf = CappedBuffer::new(self.max_object_bytes);
        while let Some(chunk) = body
            .try_next()
            .await
            .map_err(|e| DalError::Storage(e.to_string()))?
        {
            buf.push(&chunk)?;
        }
        Ok(buf.finish())
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
            Err(e) if head_is_not_found(&e) => Ok(false),
            Err(e) => Err(DalError::Storage(e.to_string())),
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

#[cfg(test)]
mod tests {
    use super::*;
    use aws_sdk_s3::config::{BehaviorVersion, Credentials, Region};
    use figment::providers::Serialized;
    use serde_json::json;
    use std::sync::{Arc, Mutex};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    type Seen = Arc<Mutex<Vec<String>>>;

    /// Starts a one-shot-per-connection fake S3 endpoint answering with `respond(request_line)`.
    async fn fake_s3(respond: fn(&str) -> String) -> (String, Seen) {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let addr = listener.local_addr().expect("addr");
        let seen: Seen = Arc::default();
        let log = seen.clone();
        tokio::spawn(async move {
            loop {
                let Ok((mut sock, _)) = listener.accept().await else {
                    break;
                };
                let log = log.clone();
                tokio::spawn(async move {
                    let mut buf = Vec::new();
                    let mut tmp = [0u8; 4096];
                    loop {
                        let r = tokio::time::timeout(
                            std::time::Duration::from_millis(150),
                            sock.read(&mut tmp),
                        )
                        .await;
                        match r {
                            Ok(Ok(n)) if n > 0 => buf.extend_from_slice(&tmp[..n]),
                            _ => break,
                        }
                    }
                    let head = String::from_utf8_lossy(&buf);
                    let line = head.lines().next().unwrap_or_default().to_owned();
                    log.lock().expect("lock").push(line.clone());
                    let _ = sock.write_all(respond(&line).as_bytes()).await;
                    let _ = sock.shutdown().await;
                });
            }
        });
        (format!("http://{addr}"), seen)
    }

    fn http(status: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nContent-Type: application/xml\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    fn store(endpoint: &str) -> S3StorageStore {
        let conf = aws_sdk_s3::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new("us-east-1"))
            .endpoint_url(endpoint)
            .force_path_style(true)
            .credentials_provider(Credentials::new(
                "AKIDEXAMPLE",
                "wJalrXUtnFEMI",
                None,
                None,
                "test",
            ))
            .build();
        S3StorageStore::new(aws_sdk_s3::Client::from_conf(conf), "bkt")
    }

    fn cfg_from(v: serde_json::Value) -> S3Config {
        S3Config::from_figment(Figment::new().merge(Serialized::defaults(v))).expect("cfg")
    }

    // regression: S-04 sweep — endpoint credentials must not reach Debug output
    #[test]
    fn config_debug_redacts_endpoint_credentials() {
        let cfg = cfg_from(
            json!({"endpoint_url": "https://AKIA:s3cr3t@minio.local:9000/p?X-Amz-Signature=abc"}),
        );
        let shown = format!("{cfg:?}");
        assert!(
            !shown.contains("s3cr3t") && !shown.contains("AKIA") && !shown.contains("abc"),
            "{shown}"
        );
        assert!(shown.contains("minio.local:9000"));
        assert!(format!("{:?}", cfg_from(json!({}))).contains("None"));
    }

    #[test]
    fn redact_url_cases() {
        assert_eq!(redact_url("http://h:9000"), "http://h:9000/");
        assert_eq!(redact_url("http://u:p@h"), "http://h/");
        assert_eq!(redact_url("http://u:p@h/x?k=v"), "http://h/x");
    }

    /// Asserts that none of `secrets` survive redaction of `input`.
    fn assert_redacted(input: &str, secrets: &[&str]) {
        let out = redact_url(input);
        for s in secrets {
            assert!(
                !out.contains(s),
                "{s:?} leaked in {out:?} (input {input:?})"
            );
        }
    }

    // regression: S-08b — '?' in the password must not truncate userinfo before '@'
    #[test]
    fn redact_url_question_mark_in_password() {
        // the url crate reads "user:p" as host:port and rejects it: placeholder, never the input
        assert_eq!(redact_url("https://user:p?ss@host/x"), "[REDACTED-URL]");
        assert_redacted("https://user:p?ss@host/x", &["user", "p?ss", "ss"]);
    }

    // regression: S-08b — '#' in the password
    #[test]
    fn redact_url_hash_in_password() {
        assert_redacted("https://user:pa#ss@host/x", &["user", "pa", "ss"]);
    }

    // regression: S-08b — '/' in the password, raw and percent-encoded
    #[test]
    fn redact_url_slash_in_password() {
        assert_redacted("https://user:pa/ss@host/x", &["user", "pa/ss", "ss"]);
        assert_redacted("https://user:pa%2Fss@host/x", &["user", "pa%2Fss", "ss"]);
    }

    // regression: S-08b — '@' in the password and multiple '@'
    #[test]
    fn redact_url_at_signs_in_password() {
        assert_redacted("https://user:p@ss@host/x", &["user", "p@ss", "ss"]);
        assert_redacted(
            "https://user:a@b@c@host/x",
            &["user", "a@b", "b@c", "c@host"],
        );
        assert_eq!(redact_url("https://user:a@b@c@host/x"), "https://host/x");
    }

    // regression: S-08b — token in the query string and fragment
    #[test]
    fn redact_url_query_and_fragment_tokens() {
        let out = redact_url("https://host/x?X-Amz-Signature=tok123&a=b#frag99");
        assert_eq!(out, "https://host/x");
        assert!(!out.contains("tok123") && !out.contains("frag99"));
    }

    // regression: S-08b — unparseable input never echoed back
    #[test]
    fn redact_url_unparseable_returns_placeholder() {
        assert_eq!(redact_url("not a url"), "[REDACTED-URL]");
        assert_eq!(redact_url("user:secret@"), "[REDACTED-URL]");
        assert_eq!(redact_url(""), "[REDACTED-URL]");
    }

    #[test]
    fn config_defaults_and_env() {
        let cfg = cfg_from(json!({}));
        assert_eq!(cfg.region, "us-east-1");
        assert!(cfg.force_path_style);
        assert_eq!(cfg.bucket, "penguin");
        assert_eq!(cfg.max_object_bytes, DEFAULT_MAX_OBJECT_BYTES);
        assert!(S3Config::from_figment(
            Figment::new().merge(Serialized::defaults(json!({"region": 5})))
        )
        .is_err());

        let _g = crate::ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        std::env::set_var("S3_BUCKET", "from-env");
        std::env::set_var("S3_MAX_OBJECT_BYTES", "10");
        let got = S3Config::from_env();
        std::env::remove_var("S3_BUCKET");
        std::env::remove_var("S3_MAX_OBJECT_BYTES");
        let got = got.expect("env");
        assert_eq!(
            (got.bucket.as_str(), got.max_object_bytes),
            ("from-env", 10)
        );
    }

    #[test]
    fn capped_buffer_enforces_limit() {
        let mut b = CappedBuffer::new(4);
        b.push(b"ab").expect("fits");
        b.push(b"cd").expect("exactly at limit");
        assert!(matches!(b.push(b"e"), Err(DalError::TooLarge { limit: 4 })));
        assert_eq!(b.finish(), Bytes::from_static(b"abcd"));
    }

    #[test]
    fn declared_length_check() {
        assert!(check_declared_len(None, 10).is_ok());
        assert!(check_declared_len(Some(10), 10).is_ok());
        assert!(matches!(
            check_declared_len(Some(11), 10),
            Err(DalError::TooLarge { .. })
        ));
        assert!(matches!(
            check_declared_len(Some(-1), 10),
            Err(DalError::TooLarge { .. })
        ));
    }

    #[tokio::test]
    async fn build_client_applies_region_and_endpoint() {
        let cfg = cfg_from(json!({"endpoint_url": "http://127.0.0.1:9", "region": "eu-west-2"}));
        let client = build_s3_client(&cfg).await;
        assert_eq!(
            client.config().region().map(|r| r.as_ref()),
            Some("eu-west-2")
        );
        let s = S3StorageStore::from_config(&cfg_from(json!({"max_object_bytes": 3}))).await;
        assert_eq!(s.max_object_bytes, 3);
        assert_eq!(
            S3StorageStore::new(client, "b").max_object_bytes,
            DEFAULT_MAX_OBJECT_BYTES
        );
    }

    #[tokio::test]
    async fn put_get_delete_roundtrip() {
        let (ep, seen) = fake_s3(|line| match line.split(' ').next() {
            Some("GET") => http("200 OK", "hello"),
            Some("PUT") => http("200 OK", ""),
            _ => http("204 No Content", ""),
        })
        .await;
        let s = store(&ep);
        s.put("k/1", Bytes::from_static(b"hello"), Some("text/plain"))
            .await
            .expect("put");
        s.put("k/2", Bytes::from_static(b"hello"), None)
            .await
            .expect("put no ct");
        assert_eq!(
            s.get("k/1").await.expect("get"),
            Bytes::from_static(b"hello")
        );
        s.delete("k/1").await.expect("delete");
        let lines = seen.lock().expect("lock").join("\n");
        assert!(
            lines.contains("PUT /bkt/k/1")
                && lines.contains("GET /bkt/k/1")
                && lines.contains("DELETE /bkt/k/1"),
            "{lines}"
        );
    }

    #[tokio::test]
    async fn get_enforces_size_cap_and_maps_not_found() {
        let (ep, _) = fake_s3(|line| {
            if line.contains("missing") {
                http(
                    "404 Not Found",
                    "<Error><Code>NoSuchKey</Code><Message>x</Message></Error>",
                )
            } else {
                http("200 OK", "0123456789")
            }
        })
        .await;
        let s = store(&ep).with_max_object_bytes(5);
        assert!(matches!(
            s.get("big").await,
            Err(DalError::TooLarge { limit: 5 })
        ));
        assert!(matches!(s.get("missing").await, Err(DalError::NotFound(k)) if k == "missing"));
        assert_eq!(
            store(&ep)
                .get("big")
                .await
                .expect("under default cap")
                .len(),
            10
        );
    }

    #[tokio::test]
    async fn get_other_errors_are_storage() {
        let (ep, _) =
            fake_s3(|_| http("403 Forbidden", "<Error><Code>AccessDenied</Code></Error>")).await;
        assert!(matches!(
            store(&ep).get("k").await,
            Err(DalError::Storage(_))
        ));
        assert!(matches!(
            store(&ep).put("k", Bytes::new(), None).await,
            Err(DalError::Storage(_))
        ));
        assert!(matches!(
            store(&ep).delete("k").await,
            Err(DalError::Storage(_))
        ));
        assert!(matches!(
            store(&ep).list("p").await,
            Err(DalError::Storage(_))
        ));
    }

    // regression: S-15 — exists() must use the typed not-found error, not match error text
    #[tokio::test]
    async fn exists_uses_typed_not_found() {
        let (ep, _) = fake_s3(|line| {
            if line.contains("present") {
                http("200 OK", "")
            } else if line.contains("denied") {
                http("403 Forbidden", "")
            } else if line.contains("k404") {
                // key name contains "404" but the server says it exists
                http("200 OK", "")
            } else {
                http("404 Not Found", "")
            }
        })
        .await;
        let s = store(&ep);
        assert!(s.exists("present").await.expect("exists"));
        assert!(!s.exists("absent").await.expect("absent"));
        assert!(s
            .exists("k404")
            .await
            .expect("404 in key name is not a not-found"));
        assert!(matches!(
            s.exists("denied").await,
            Err(DalError::Storage(_))
        ));
    }

    #[tokio::test]
    async fn list_returns_keys() {
        let (ep, seen) = fake_s3(|_| {
            http(
                "200 OK",
                "<?xml version=\"1.0\"?><ListBucketResult><Name>bkt</Name><Prefix>p/</Prefix><KeyCount>2</KeyCount><MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated><Contents><Key>p/a</Key></Contents><Contents><Key>p/b</Key></Contents></ListBucketResult>",
            )
        })
        .await;
        assert_eq!(
            store(&ep).list("p/").await.expect("list"),
            vec!["p/a", "p/b"]
        );
        assert!(seen.lock().expect("lock")[0].contains("prefix=p%2F"));
        let (ep2, _) = fake_s3(|_| {
            http(
                "200 OK",
                "<ListBucketResult><Name>b</Name></ListBucketResult>",
            )
        })
        .await;
        assert!(store(&ep2).list("").await.expect("empty").is_empty());
    }
}
