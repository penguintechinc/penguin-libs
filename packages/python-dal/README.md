# penguin-dal

PyDAL-style database abstraction layer built on SQLAlchemy. One schema (reflected automatically), one query interface — no more defining tables twice.

## Installation

```bash
pip install penguin-dal

# With database drivers:
pip install penguin-dal[postgresql]   # psycopg2
pip install penguin-dal[asyncpg]      # asyncpg for async
pip install penguin-dal[mysql]        # PyMySQL
pip install penguin-dal[all]          # all drivers
```

## Quick Start

```python
from penguin_dal import DB

db = DB("postgresql://user:pass@localhost/mydb")

users = db(db.users.active == True).select()
pk = db.users.insert(email="new@example.com", name="New User", active=True)
db(db.users.id == pk).update(name="Updated")
db(db.users.id == pk).delete()
```

## Read/Write Splitting

```python
from penguin_dal import DatabaseManager

manager = DatabaseManager(
    write_url="postgresql://primary/myapp",
    read_url="postgresql://replica/myapp",
)
rows = manager.read(manager.read.users).select()
manager.write.users.insert(name="Alice")
manager.close()
```

📚 **Full documentation**: [docs/penguin-dal/](../../docs/penguin-dal/)
- [README](../../docs/penguin-dal/README.md) — complete feature overview
- [API Reference](../../docs/penguin-dal/API.md) — all classes and methods
- [Changelog](../../docs/penguin-dal/CHANGELOG.md)
- [Migration Guide](../../docs/penguin-dal/MIGRATION.md) — migrating from PyDAL or upgrading to 0.2.x

## License

AGPL-3.0 — Penguin Tech Inc
