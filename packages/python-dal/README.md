# Penguin-DAL

SQLAlchemy runtime wrapper with PyDAL ergonomics. One schema definition (SQLAlchemy), one query interface (penguin-dal) — no more defining tables twice.

## Install

```bash
pip install penguin-dal

# With database drivers
pip install penguin-dal[postgresql]   # psycopg2
pip install penguin-dal[asyncpg]      # asyncpg for async
pip install penguin-dal[mysql]        # PyMySQL
pip install penguin-dal[all]          # all drivers
```

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

# Count & exists
count = db(db.users.active == True).count()
exists = db(db.users.email == "alice@example.com").exists()

# PK lookup
user = db.users[42]

# Compound queries
q = (db.users.active == True) & (db.users.name.contains("alice"))
rows = db(q).select(orderby=~db.users.name, limitby=(0, 10))
```

### Async (Quart)

```python
from penguin_dal import AsyncDB

db = AsyncDB("postgresql+asyncpg://user:pass@localhost/mydb")
await db.reflect()

users = await db(db.users.active == True).select()
pk = await db.users.async_insert(email="new@example.com", name="New")
```

## Features

- **Table reflection** — no `define_table()` calls; reads schema from the database
- **PyDAL-identical query syntax** — `db(query).select()`, `db.table.insert()`, etc.
- **Async-first** — native `async/await` with `AsyncDB` for Quart/ASGI apps
- **All backends** — PostgreSQL, MySQL, MariaDB Galera, MSSQL, Firebird, SQLite
- **Connection pooling** — per-backend tuning via SQLAlchemy pool
- **Cursor pagination** — efficient keyset pagination for large datasets
- **Bulk operations** — `bulk_insert()` for batch inserts
- **Validators** — register column validators or use `@validated_columns` decorator
- **Flask/Quart integration** — `init_dal(app)` and `get_db()` helpers

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

## Quart Integration

```python
from penguin_dal.quart_ext import init_dal, get_db

app = Quart(__name__)
init_dal(app, uri="postgresql+asyncpg://...")

@app.route("/users")
async def list_users():
    db = get_db()
    rows = await db(db.users.active == True).select()
    return jsonify(rows.as_list())
```

## Cursor Pagination

```python
from penguin_dal.pagination import Cursor, paginate_query

qs = db(db.users.active == True)
page = paginate_query(qs, db.users.id, Cursor(size=25))
# page.rows, page.next_cursor, page.has_more

# Next page
page2 = paginate_query(qs, db.users.id, Cursor(after=page.next_cursor, size=25))
```

## Validators

```python
from penguin_dal.validators import validated_columns

@validated_columns({
    "email": [is_not_empty, is_email],
    "name": [is_not_empty],
})
class User(Base):
    __tablename__ = "users"
    ...

db.register_model(User)
# Now db.users.insert() will validate before inserting
```

## Migration from PyDAL

| PyDAL | Penguin-DAL |
|-------|-------------|
| `db.define_table('users', Field(...))` | Tables reflected automatically |
| `db(db.users.id > 0).select()` | `db(db.users.id > 0).select()` (same!) |
| `db.users.insert(email=...)` | `db.users.insert(email=...)` (same!) |
| `db(query).update(...)` | `db(query).update(...)` (same!) |
| `db(query).delete()` | `db(query).delete()` (same!) |
| `db.commit()` | Auto-commits (db.commit() is no-op) |
| `row.email` | `row.email` (same!) |

## License

AGPL-3.0 - Penguin Tech Inc
