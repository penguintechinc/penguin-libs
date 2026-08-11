# penguin-dal `executesql` — Design

**Date:** 2026-08-04
**Package:** `penguin-dal` (`packages/python-dal`)
**Target version:** 0.4.0 (already the repo version; never tagged or published — see Versioning)

## Problem

`penguin-dal` has no raw-SQL escape hatch. The public surface of `DB`, `AsyncDB`, and
`DatabaseManager` is `engine`, `metadata`, `tables`, `commit`, `close`,
`register_validators`, `register_model`, `define_table` — nothing executes caller-supplied
SQL. Callers needing raw SQL must reach for `db.engine` and drop to SQLAlchemy directly,
which breaks the "penguin-dal for ALL runtime operations" rule in `backend-database.md`.

Two concrete drivers:

1. **PyDAL migration.** web2py/PyDAL-era code being ported onto penguin-dal already calls
   `db.executesql(...)`. Every such call site is currently a rewrite.
2. **Bulk operations.** Runtime `UPDATE`/`INSERT ... SELECT`/`TRUNCATE` that the QuerySet
   builder cannot express.

## Non-goals

- Tenant scoping. penguin-dal has **no** tenant awareness today (zero `tenant` references in
  the package). `executesql` does not introduce any, and does not bypass any — tenant
  enforcement lives in the service layer above this package. Callers remain fully responsible
  for including tenant predicates in raw SQL.
- Replacing the QuerySet API. `executesql` is an escape hatch, not a primary query path.
- SQLAlchemy `:name` parameter style. See Parameter style below.

## API

```python
# DB (sync)
def executesql(
    self,
    query: str,
    placeholders: Sequence[Any] | Mapping[str, Any] | None = None,
    as_dict: bool = False,
    fields: Sequence[Any] | None = None,
    colnames: Sequence[str] | None = None,
    as_ordered_dict: bool = False,
    return_rowcount: bool = False,
    check_injection: bool = True,
) -> list[tuple[Any, ...]] | list[dict[str, Any]] | Rows | int | None: ...

# AsyncDB — identical signature, async def
async def executesql(self, ...) -> ...: ...
```

The first six parameters are PyDAL's, in PyDAL's order, with PyDAL's defaults.
`return_rowcount` and `check_injection` are penguin-dal additions; both default to the
PyDAL-equivalent behavior so no migrated call site changes meaning.

### Parameter style — driver-native, not SQLAlchemy

PyDAL passes `placeholders` straight to the DBAPI cursor, so migrated queries contain the
**driver's** paramstyle: `%s` for psycopg2/pymysql, `?` for sqlite3, `%(name)s` for pyformat.
Implementing on `sqlalchemy.text()` (which uses `:name`) would break every migrated call site.

Execution therefore goes through `Connection.exec_driver_sql(query, placeholders)`, which
passes the statement to the DBAPI unmodified with driver-native paramstyle.

**Accepted consequence:** SQLAlchemy `:name` style is *not* supported by `executesql`. That is
what the QuerySet API and `db.engine` are for. This is documented in the docstring.

### Return semantics

PyDAL's, including the parts that are awkward:

| Condition | Returns |
|---|---|
| No result set (`cursor.description is None`) — INSERT/UPDATE/DELETE/DDL | `None` |
| Default (result set present) | `list[tuple]` — raw cursor rows |
| `as_dict=True` | `list[dict]`, keys from cursor description |
| `as_ordered_dict=True` | `list[OrderedDict]` |
| `fields=` and/or `colnames=` | penguin_dal `Rows` (via `Row`, matching `query.py:166-215`) |
| `return_rowcount=True` | `int` — `cursor.rowcount`, overriding the `None` above |

Invalid combinations raise `ValueError`, matching PyDAL's rejection of the same:

- `as_dict=True` together with `fields=` or `colnames=`
- `as_dict=True` together with `as_ordered_dict=True`

### Why `return_rowcount` rather than returning rowcount by default

Returning `cursor.rowcount` unconditionally would silently change migrated code: under PyDAL
`if db.executesql("UPDATE ...")` is always falsy (returns `None`); returning an int makes it
truthy whenever rows matched. It would also surface the DBAPI's `-1` sentinel for DDL, where
rowcount is not applicable.

The rejected alternative was a `db.rowcount` property holding the last statement's count. That
is action-at-a-distance mutable state on the DB object: correct under the house
thread-local/per-coroutine rule, but it returns a *wrong number* rather than an error if an
instance is ever shared across threads or coroutines.

`return_rowcount=True` is opt-in, carries the value in the return, has no shared state, and
cannot alter any PyDAL-era call (which never passes it).

### Transactions

Writes commit inline, matching `QuerySet.update`/`delete` (`query.py:233,248,359,370`).
`DB.commit()`/`AsyncDB.commit()` are no-ops (`db.py:118,320`), so there is no ambient
transaction to join. Each `executesql` call is its own unit of work.

### Injection guard

`executesql` emits `DALSecurityWarning` (new, subclass of `Warning`, exported from
`exceptions.py`) when **both**:

- `placeholders` is `None` or empty, **and**
- the statement contains a quoted string literal inside a `WHERE`, `VALUES`, or `IN` clause.

It **warns, never rejects**. The check is a heuristic and cannot be sound: by the time the
function receives the string, any interpolation has already happened. It will false-positive on
legitimate static SQL such as `WHERE status = 'active'` — hence a dedicated warning class
callers can filter with `warnings.filterwarnings`, plus `check_injection=False` to disable
per-call.

Values must be passed via `placeholders`. The docstring states this explicitly.

### Errors

SQLAlchemy exceptions propagate uncaught, matching current package convention — no new
exception type. `exceptions.py` gains only `DALSecurityWarning`.

## Testing

New tests in `packages/python-dal/tests/`, using existing fixtures (`engine`, `db`, `db_plain`
in `conftest.py:57-130`; `async_db` in `test_async_db.py:10`) against in-memory SQLite:

- Each return mode: default tuples, `as_dict`, `as_ordered_dict`, `fields`/`colnames` → `Rows`
- `None` for INSERT/UPDATE/DELETE/DDL
- `return_rowcount=True` → correct int; `-1` for DDL
- Positional (`?`) and named placeholder binding
- Invalid kwarg combinations → `ValueError`
- `DALSecurityWarning` raised on literal-in-WHERE with no placeholders; **not** raised when
  placeholders supplied; suppressed by `check_injection=False`
- Async mirror of the above against `AsyncDB`
- Coverage must hold ≥90% (`pyproject.toml` gate)

## Versioning and publish

`penguin-dal` sits at `0.4.0` in the repo with **no `penguin-dal-v0.4.0` tag** and PyPI serving
`0.3.0`. Under the house versioning rule — increment only when the current version is already
tagged — `executesql` ships **as part of 0.4.0**, not a new 0.5.0. Bumping would leave a
permanent gap (PyPI 0.3.0 → 0.5.0, no 0.4.0 ever released).

Publish path: merge to `release/python-dal/v0.4.x`, then push tag `penguin-dal-v0.4.0`, which
triggers the existing `publish.yml` (last shipped this package's 0.3.0 on 2026-04-07).

**Known pipeline risk — verify the run, do not assume.** Five tags pushed 2026-03-30 from
commit `2f597ca` produced zero Actions runs, and three npm tags went green while publishing to
GitHub Packages instead of public npm. The tag push must be followed by confirming an actual
successful run and the version appearing on PyPI.
