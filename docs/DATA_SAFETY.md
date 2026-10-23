# Data and credential safety

## Never commit

- `PRIMO_API_KEY` or an API-key file
- real query logs or patron search histories
- raw Primo API responses
- flattened result CSV files
- bibliographic metadata exports
- local configuration histories
- aggregated datasets derived from collected runs

These locations are ignored by default: `runs/`, `aggregates/`, `outputs/`, and
`data/`.

## Credential handling

The collector accepts the API key only through `PRIMO_API_KEY`. It never writes
the key to a request manifest, raw response, error message, or CSV. `PRIMO_VID`
is also supplied locally rather than committed.

## Before publishing

Run both checks:

```powershell
git status --short
git grep -n -I -E "apikey|api[_-]?key|01[A-Z0-9_]+:01[A-Z0-9_]+"
```

Inspect every staged file with `git diff --cached`. If real research data was
ever committed, removing the working-tree file is insufficient; rewrite the Git
history before publishing.

