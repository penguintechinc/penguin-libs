# penguin-sal (superseded)

> **This package is superseded.** `penguin-sal` is folded into `penguin-aaa`
> as `penguin_aaa.secrets`, installed via the `penguin-aaa[secrets]` (or
> per-backend `penguin-aaa[secrets-<backend>]`) extra. No further versions of
> `penguin-sal` are published from this branch.
>
> **Migration:** replace `penguin_sal.X` imports with `penguin_aaa.secrets.X`
> (e.g. `penguin_sal.adapters.vault` → `penguin_aaa.secrets.adapters.vault`).
> The public API is unchanged — only the import path and install extras moved.
>
> Full docs: see `docs/penguin-aaa/` on the `release/python-aaa/v0.2.x` line.

See [docs/penguin-sal/](../../docs/penguin-sal/) for the last-published
documentation of this package.
