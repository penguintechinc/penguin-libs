# Changelog

All notable changes to @penguin/react_libs will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.6] - 2026-11-09

### Security
- Upgrade `zod` 3.25.76 -> 4.6.7 (exact pin); fixes the oversized-collection DoS advisory.

### BREAKING
- The `z` re-export from `FormModalBuilder` is now the zod 4 API, and `FormField.schema` takes a zod 4 `ZodType`. Consumers passing custom schemas must upgrade to `zod@^4` (zod 3 schemas are not accepted at the type level).
  - zod 4 migration: `message`/`invalid_type_error` -> `error`, `z.string().email()` -> `z.email()`, `z.record(v)` -> `z.record(k, v)`, `.flatten()`/`.format()` -> `z.flattenError`/`z.treeifyError`, `ZodError.errors` -> `.issues`.
- Validation message behaviour: the custom `error` on `select`/`radio` and required `checkbox` fields now applies to every failure of that field (previously only wrong-type failures), so e.g. an unlisted select value now shows "<Label> must be one of the available options".

## [1.1.0] - 2026-01-27

### Added
- **Multi-select checkbox support**: New `checkbox_multi` field type for FormModalBuilder
  - Allows users to select multiple options from a list of checkboxes
  - Returns an array of selected values
  - Supports required validation (must have at least one selection)
  - Includes scrollable container for long option lists
  - Example: See `examples/MultiSelectExample.tsx`

### Changed
- Updated field type union to include `checkbox_multi`
- Enhanced default value initialization to handle arrays for multi-select fields
- Improved Zod schema validation for multi-select arrays

## [1.0.0] - 2026-01-22

### Added
- Initial release of @penguin/react_libs
- FormModalBuilder component with comprehensive field types
- SidebarMenu component for navigation
- Dark mode theme with gold accents (default)
- Zod-based validation
- Conditional field visibility (showWhen, triggerField)
- Tab support for complex forms
- File upload with drag & drop
- Password generation
