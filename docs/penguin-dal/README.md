# penguin-dal

PyDAL-style database abstraction layer built on SQLAlchemy. Provides a familiar PyDAL-style API for defining tables and running queries, with support for connection pooling, async queries, Flask/Quart integration, and read/write splitting.

## Installation

```bash
pip install penguin-dal

# With database drivers:
pip install penguin-dal[postgresql]   # psycopg2
pip install penguin-dal[asyncpg]      # asyncpg for async
pip install penguin-dal[mysql]        # PyMySQL
pip install penguin-dal[all]          # all drivers
```

## Features

- Table reflection — no `define_table()` calls; reads schema from the database
- PyDAL-identical query syntax (`db(query).select()`, `db.table.insert()`, etc.)
- Async-first — native `async/await` with `AsyncDB` for Quart/ASGI apps
- All backends — PostgreSQL, MySQL, MariaDB Galera, MSSQL, Firebird, SQLite
- Connection pooling — per-backend tuning via SQLAlchemy pool
- Cursor pagination — efficient keyset pagination for large datasets
- Bulk operations — `bulk_insert()` for batch inserts
- Validators — register column validators or use `@validated_columns` decorator
- Flask/Quart integration — `init_dal(app)` and `get_db()` helpers
- Read/write splitting — `DatabaseManager` manages primary and replica connections

## Quick Start

### Sync (Flask)

```python
from penguin_dal import DB

db = DB("postgresql://user:pass@localhost/mydb")

# Select
users = db(db.users.active == True).select()
user = db(db.users.email == "alice@example.com").select().first()

# Insert
pk = db.users.insert(email="new@example.com", name="New User", active=True)

# Update
db(db.users.id == pk).update(name="Updated Name")

# Delete
db(db.users.id == pk).delete()
```

### Async (Quart)

```python
from penguin_dal import AsyncDB

db = AsyncDB("postgresql+asyncpg://user:pass@localhost/mydb")
await db.reflect()

users = await db(db.users.active == True).select()
pk = await db.users.async_insert(email="new@example.com", name="New")
```

### Read/Write Splitting

```python
from penguin_dal import DatabaseManager

manager = DatabaseManager(
    write_url="postgresql://primary/myapp",
    read_url="postgresql://replica/myapp",
)

# Read from replica
rows = manager.read(manager.read.users.active == True).select()

# Write to primary
manager.write.users.insert(name="Alice")
manager.write.commit()

manager.close()
```

## Flask Integration

```python
from penguin_dal.flask_ext import init_dal, get_db

app = Flask(__name__)
init_dal(app, uri="postgresql://...")

@app.route("/users")
def list_users():
    db = get_db()
    return jsonify(db(db.users.active == True).select().as_list())
```

## Migration from PyDAL

| PyDAL | penguin-dal |
|-------|-------------|
| `db.define_table('users', Field(...))` | Tables reflected automatically |
| `db(db.users.id > 0).select()` | `db(db.users.id > 0).select()` (same!) |
| `db.users.insert(email=...)` | `db.users.insert(email=...)` (same!) |
| `db(query).update(...)` | `db(query).update(...)` (same!) |
| `db(query).delete()` | `db(query).delete()` (same!) |
| `row.email` | `row.email` (same!) |

📚 Full documentation: [docs/penguin-dal/](../../docs/penguin-dal/)
