# penguin-dal Migration Guide

## Migrating to 0.2.0

### Read/Write Splitting

If you were previously using two separate `DB` instances for read/write splitting, migrate to `DatabaseManager`:

**Before (0.1.x):**
```python
db_write = DB("postgresql://primary/app")
db_read = DB("postgresql://replica/app")

# Manual routing
rows = db_read(db_read.users).select()
db_write.users.insert(name="Alice")
db_write.commit()
db_read.close()
db_write.close()
```

**After (0.2.x):**
```python
from penguin_dal import DatabaseManager

manager = DatabaseManager(
    write_url="postgresql://primary/app",
    read_url="postgresql://replica/app",
)

rows = manager.read(manager.read.users).select()
manager.write.users.insert(name="Alice")
manager.write.commit()
manager.close()
```

### Flask Applications

Add `DATABASE_READ_URL` to your config or `.env`:

```bash
DATABASE_URL=postgresql://primary/app
DATABASE_READ_URL=postgresql://replica/app
```

`init_dal` automatically creates a `DatabaseManager` when both are set. `get_db()` returns the write connection; `get_db().read` (or `manager.read`) returns the replica.

## Migrating from PyDAL

penguin-dal is a drop-in replacement for most PyDAL usage patterns. The main difference is that tables are reflected from the database automatically — you no longer call `db.define_table()`.

**Before (PyDAL):**
```python
from pydal import DAL, Field

db = DAL("postgresql://localhost/app", migrate=False)
db.define_table("users",
    Field("email", "string"),
    Field("active", "boolean"),
)
rows = db(db.users.active == True).select()
```

**After (penguin-dal):**
```python
from penguin_dal import DB

db = DB("postgresql://localhost/app")
# No define_table — schema is reflected automatically
rows = db(db.users.active == True).select()
```

The query syntax (`db(query).select()`, `db.table.insert()`, `row.field`, etc.) is identical.
