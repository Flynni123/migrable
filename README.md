# migrable

`migrable` transfers tabular data from CSV and Excel files into SQLite while
keeping every migration as a versionable YAML file. It also has a Textual TUI
for building and running migrations interactively.

## Install

```bash
python -m pip install -e '.[dev,excel]'
```

For contributors, run the quality checks before submitting a change:

```bash
ruff check .
mypy src
pytest
python -m build --wheel
```

## Use

Create and edit a migration in the TUI:

```bash
migrable tui
```

Or run an already saved migration deterministically:

```bash
migrable validate examples/customers.yml
migrable run examples/customers.yml
```

## Migration configuration

```yaml
version: 1
name: import-customers
source:
  kind: csv
  path: ./customers.csv
target:
  kind: sqlite
  path: ./application.db
  dataset: customers
  mode: upsert
mapping:
  - target: customer_id
    source: Customer Number
    type: integer
    primary_key: true
  - target: name
    source: Full Name
    transforms: [trim]
  - target: email
    source: Email
    transforms: [trim, lowercase]
  - target: active
    value: true
    type: boolean
options:
  batch_size: 1000
  on_error: report_and_skip
```

`primary_key: true` values are always required. Every migration writes to
SQLite in one transaction: a failed run leaves the target unchanged, including
when `mode: replace` is selected.

`kind` currently supports `csv`, `excel`, and `sqlite`. Excel support is
optional and requires the `excel` dependency group. The database source layer
is deliberately isolated so additional database backends can be added without
changing mappings or the TUI.
