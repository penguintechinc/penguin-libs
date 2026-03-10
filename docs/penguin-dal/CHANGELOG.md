# penguin-dal Changelog

## 0.2.0 (2026-03-10)

### New Features

- **Read/write splitting**: `DatabaseManager` class manages primary and replica connections with automatic routing
- **Flask read URI**: `init_dal(app, read_uri=...)` and `DATABASE_READ_URL` env var support
- `DatabaseManager.__call__` routes queries to read replica by default
- `DatabaseManager.close()` cleanly closes both primary and replica connections

### Bug Fixes

- None

## 0.1.0

- Initial release
- `DB` and `AsyncDB` with PyDAL-compatible query syntax
- Table reflection — no `define_table()` required
- `TableProxy`, `FieldProxy`, `Query`, `QuerySet`, `AsyncQuerySet`
- `Row` and `Rows` result types with dict and attribute access
- Cursor-based and page-based pagination
- `bulk_insert()` for batch operations
- Validators and `@validated_columns` decorator
- Flask extension (`init_dal`, `get_db`)
- Quart extension (`init_dal`, `get_db`)
- Connection pooling via SQLAlchemy pool
- All backends: PostgreSQL, MySQL, MariaDB Galera, MSSQL, Firebird, SQLite
