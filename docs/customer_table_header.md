# Customer table header

The customer table header is generated, not hand-written. One function,
`report.table_header`, feeds three outputs:

- `demo_strapping.csv` and `demo_commercial.csv` — a `#` comment block above
  the rows.
- `demo_workbook.xlsx` — the first sheet, `Certificate`.
- `demo_report.md` — the "Customer table header" section.

## Config fields

| Field | Default | Use |
|---|---|---|
| `site` | `""` | Site / tag line |
| `table_version` | `"v1"` | Table version |
| `supersedes` | `"none"` | Previous table reference |

## Reading the CSV

The header lines start with `#`. Parse with:

```python
import pandas as pd

df = pd.read_csv("demo_strapping.csv", comment="#")
```

## What the header contains

Identification, adopted shell, datum, basis, uncertainty, validity, quality,
anomalies, limitations, files.

The top rows are flagged `brim-anchored` when the last dip is below the crown.
Rows below the lowest verified dip are flagged `extrapolated`.
