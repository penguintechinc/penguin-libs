use schemars::JsonSchema;
use serde_json::Value;

use crate::DescriptorError;

/// Generates the JSON Schema for `T` as canonical JSON.
pub fn schema_json<T: JsonSchema>() -> Result<String, DescriptorError> {
    let schema = schemars::SchemaGenerator::default().into_root_schema_for::<T>();
    let value =
        serde_json::to_value(&schema).map_err(|e| DescriptorError::Serialization(e.to_string()))?;
    Ok(canonical_json(&value))
}

/// Serializes `value` with object keys sorted at every depth and no
/// insignificant whitespace, so identical schemas hash identically.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.into_iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                push_json_string(key, out);
                out.push(':');
                if let Some(v) = map.get(key) {
                    write_canonical(v, out);
                }
            }
            out.push('}');
        }
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        scalar => out.push_str(&scalar.to_string()),
    }
}

fn push_json_string(s: &str, out: &mut String) {
    out.push_str(&Value::String(s.to_string()).to_string());
}
