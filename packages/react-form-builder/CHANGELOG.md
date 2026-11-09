# Changelog

All notable changes to @penguintechinc/react-form-builder are documented here.

## [Unreleased]

### Security
- Upgrade `zod` 3.25.76 -> 4.6.7 (exact pin); fixes the oversized-collection DoS advisory.

### BREAKING
- The `z` re-export from `FormModalBuilder` is now the zod 4 API, and `FormField.schema` takes a zod 4 `ZodType`. Consumers passing custom schemas must upgrade to `zod@^4` (zod 3 schemas are not accepted at the type level).
  - zod 4 migration: `message`/`invalid_type_error` -> `error`, `z.string().email()` -> `z.email()`, `z.record(v)` -> `z.record(k, v)`, `.flatten()`/`.format()` -> `z.flattenError`/`z.treeifyError`, `ZodError.errors` -> `.issues`.
- Validation message behaviour: the custom `error` on `select`/`radio` and required `checkbox` fields now applies to every failure of that field (previously only wrong-type failures), so e.g. an unlisted select value now shows "<Label> must be one of the available options".

