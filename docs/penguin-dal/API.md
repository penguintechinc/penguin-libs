# penguin-dal API Reference

## DB

```python
DB(uri: str, *, pool_size: int = 5, **kwargs)
```

Main synchronous database class. Reflects table schema from the database automatically.

### Query Methods

| Method | Description |
|--------|-------------|
| `db(query).select(*fields, orderby=None, limitby=None)` | SELECT rows matching query |
| `db(query).count()` | COUNT rows matching query |
| `db(query).exists()` | Return `True` if any rows match |
| `db(query).update(**values)` | UPDATE rows matching query |
| `db(query).delete()` | DELETE rows matching query |
| `db.table.insert(**values)` | INSERT a row, returns PK |
| `db.table[pk]` | SELECT row by primary key |
| `db.table.bulk_insert(rows)` | Batch insert a list of dicts |

### Transaction Methods

| Method | Description |
|--------|-------------|
| `db.commit()` | Commit current transaction |
| `db.rollback()` | Rollback current transaction |
| `db.close()` | Close the connection |

### Query Building

```python
# Comparison operators
db.users.active == True
db.users.id > 0
db.users.name.contains("alice")
db.users.email.startswith("admin")

# Boolean composition
q = (db.users.active == True) & (db.users.name.contains("alice"))
q = (db.users.role == "admin") | (db.users.role == "superadmin")

# Ordering and limits
db(q).select(orderby=~db.users.name, limitby=(0, 10))
db(q).select(orderby=db.users.created_at)
```

## AsyncDB

Async variant of `DB`. All query methods return coroutines.

```python
AsyncDB(uri: str, *, pool_size: int = 5, **kwargs)
```

| Method | Description |
|--------|-------------|
| `await db.reflect()` | Load schema from database |
| `await db(query).select()` | Async SELECT |
| `await db.table.async_insert(**values)` | Async INSERT |
| `await db(query).async_update(**values)` | Async UPDATE |
| `await db(query).async_delete()` | Async DELETE |

## DatabaseManager

```python
DatabaseManager(write_url: str, read_url: str | None = None, **kwargs)
```

Manages primary (write) and optional replica (read) connections.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `.write` | `DB` | Primary (write) connection |
| `.read` | `DB` | Replica connection (or primary if no `read_url`) |

### Methods

| Method | Description |
|--------|-------------|
| `manager(query)` | Routes to `.read` by default |
| `manager.close()` | Closes both connections |

## Rows / Row

Result types returned by `.select()`.

```python
rows = db(db.users.active == True).select()

rows[0].email           # attribute access
rows[0]["email"]        # dict-style access
rows.first()            # first Row or None
rows.as_list()          # list of dicts
rows.as_dict("id")      # dict keyed by field value
len(rows)               # row count
```

## Cursor Pagination

```python
from penguin_dal.pagination import Cursor, paginate_query

qs = db(db.users.active == True)
page = paginate_query(qs, db.users.id, Cursor(size=25))
# page.rows      — Rows result
# page.next_cursor — opaque cursor string or None
# page.has_more  — bool

# Next page
page2 = paginate_query(qs, db.users.id, Cursor(after=page.next_cursor, size=25))
```

## Validators

```python
from penguin_dal.validators import validated_columns, is_email, is_not_empty

@validated_columns({
    "email": [is_not_empty, is_email],
    "name": [is_not_empty],
})
class User(Base):
    __tablename__ = "users"
    ...

db.register_model(User)
# db.users.insert() now validates before inserting
```

## Flask Extension

```python
from penguin_dal.flask_ext import init_dal, get_db
```

| Function | Description |
|----------|-------------|
| `init_dal(app, uri=None, read_uri=None, **kwargs)` | Initialize dal for Flask app |
| `get_db()` | Get DB instance for current app context |

When both `DATABASE_URL` and `DATABASE_READ_URL` are set (via config or env), `init_dal` automatically creates a `DatabaseManager`. `get_db()` returns the write connection; use `get_db().read` for the replica.

## Quart Extension

```python
from penguin_dal.quart_ext import init_dal, get_db
```

Same API as the Flask extension. `get_db()` returns `AsyncDB`.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Primary (write) database URI |
| `DATABASE_READ_URL` | Read replica URI (optional) |
