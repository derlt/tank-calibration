# Campaign configuration

One JSON file per tank. The file names the raw CSV and records the decisions
the fit cannot take from the data. Paths are relative to the JSON file.

The raw file is read-only. Corrections live in `corrections`, never in the raw
file.

## Minimal file

```json
{
  "tank": "run1",
  "raw": "run1_raw.csv",
  "nominal": {"r": 948.0, "L": 2517.0},
  "sigma_h": 1.5,
  "pour_unit": 50,
  "h0": {"mode": "fit"},
  "heel_row": false,
  "brim": {"reading": 1896.0},
  "bootstrap_n": 200,
  "seed": 0
}
```

## Full file

```json
{
  "tank": "run1",
  "site": "Tank farm A",
  "table_version": "v1",
  "supersedes": "none",
  "raw": "run1_raw.csv",
  "nominal": {"r": 948.0, "L": 2517.0},
  "sigma_h": 1.5,
  "pour_noise": {"rel": 0.005, "abs": 3.0},
  "pour_unit": 50,
  "h0": {"mode": "fit", "value": 0.0},
  "heel_row": true,
  "brim": {
    "reading": 1896.0,
    "overflow_pour": 50.0,
    "vent_volume": 0.0,
    "neck_equality": false
  },
  "object_bands": [
    {"low": 1397, "high": 1444, "litres": 44.0, "label": "solid", "test": "repeat pour into the band"}
  ],
  "corrections": [
    {"row": 12, "field": "height", "value": 853.0, "rule": "6.1", "magnitude": -4.0, "note": "dip misread"}
  ],
  "exclude": [{"row": 30}],
  "blocking": {"enabled": false, "target_rise_mm": 30.0},
  "tilt_test": false,
  "lag_checks": [
    {"at_mm": 1200, "readings": [[1, 1201.0], [10, 1202.5]]}
  ],
  "strapping": {"step_mm": 10.0, "start_mm": 0.0},
  "bootstrap_n": 200,
  "seed": 0,
  "notes": "First pass."
}
```

## Top-level fields

| Field | Type | Default | Unit | Meaning |
|---|---|---|---|---|
| `tank` | string | JSON file stem | — | Name used in output file names and the certificate. |
| `site` | string | `""` | — | Site or tag line in the certificate header. |
| `table_version` | string | `"v1"` | — | Table version in the certificate header. |
| `supersedes` | string | `"none"` | — | Previous table reference in the certificate header. |
| `raw` | string | required | path | Raw CSV. Relative to the JSON file. Read-only. |
| `nominal` | object | required | mm | Starting values for `r` and `L`. |
| `sigma_h` | number | `1.5` | mm | Dip reading standard deviation. Must be positive. |
| `pour_noise` | object | `{rel: 0.005, abs: 3.0}` | L | Pour error model. |
| `pour_unit` | number | none | L | Pour increment. Enables the quantized pour search. |
| `h0` | object | `{mode: "fit"}` | mm | Datum policy. |
| `heel_row` | boolean | `false` | — | The first row is a heel, not an empty start. |
| `brim` | object | `{}` | mm, L | Brim reading, overflow pour and vent volume. |
| `object_bands` | array | `[]` | mm, L | Known internals and their displacement. |
| `corrections` | array | `[]` | mm, L | Flagged edits to the raw rows. |
| `exclude` | array | `[]` | — | Rows left out of the fit. |
| `blocking` | object | `{}` | mm | Interval blocking for small pours. |
| `tilt_test` | boolean | `false` | — | Test a static tilt. |
| `lag_checks` | array | `[]` | min, mm | Repeated dips at one level. |
| `strapping` | object | `{}` | mm | Table interval and start level. |
| `bootstrap_n` | integer | `200` | — | Number of bootstrap resamples. |
| `seed` | integer | `0` | — | Random seed for the bootstrap. |
| `notes` | string | `""` | — | Free text. Kept in the config, not written to the deliverables. |

Notes:

- `pour_unit` enables the quantized pour search for a suspect single-sided
  event.
- `tilt_test` adds one tilt parameter and keeps it only if the F-test and
  plausibility both pass.
- `bootstrap_n` of 200 is enough for a first pass. Use 1000 or more for the
  final table.
- `seed` fixes the bootstrap draws. Keep it for reproducibility.

## Nested fields

### `nominal`

| Field | Type | Required | Unit | Meaning |
|---|---|---|---|---|
| `r` | number | yes | mm | Internal radius: internal diameter divided by 2. |
| `L` | number | yes | mm | Internal shell length between the flat ends. |

The fit searches around these values: `r` within 0.6 to 1.4 times nominal,
`L` within 0.7 to 1.3 times nominal.

### `pour_noise`

| Field | Type | Default | Unit | Meaning |
|---|---|---|---|---|
| `rel` | number | `0.005` | — | Relative pour error, as a fraction of the pour. |
| `abs` | number | `3.0` | L | Absolute pour error. |

The pour sigma is `rel * |s| + abs`, where `s` is the pour in litres.

### `h0`

| Field | Type | Default | Unit | Meaning |
|---|---|---|---|---|
| `mode` | `"fit"` or `"locked"` | `"fit"` | — | Estimate the datum, or fix it. |
| `value` | number | `0.0` | mm | Datum when `mode` is `"locked"`. |

`h0` is the tape reading at the true tank bottom. True depth is `h = H - h0`.
The fit searches `h0` within ±80 mm. A locked datum reports its cost in litres
per step.

### `brim`

| Field | Type | Default | Unit | Meaning |
|---|---|---|---|---|
| `reading` | number | none | mm | Tape reading at the shell crown. If absent, the fit uses `h0 + 2r`. |
| `overflow_pour` | number | none | L | The pour that overflowed. The fit enforces `G <= P - vent_volume`. |
| `vent_volume` | number | `0.0` | L | Liquid that went into the vent. |
| `neck_equality` | boolean | `false` | — | Add `2r + h0 = B` when the last dip reads the neck or brim. |

### `object_bands[]`

| Field | Type | Required | Unit | Meaning |
|---|---|---|---|---|
| `low` | number | yes | mm | Lower tape reading of the band. |
| `high` | number | yes | mm | Upper tape reading. Must exceed `low`. |
| `litres` | number | no | L | Displacement in the band. If absent, the net residual estimates it. |
| `label` | string | no | — | Free text. |
| `test` | string | no | — | Action that confirms the band. |

### `corrections[]`

| Field | Type | Required | Unit | Meaning |
|---|---|---|---|---|
| `row` | integer | yes | — | 1-based data row. The header is not a row. |
| `field` | `"height"` or `"step"` | no | — | What to correct. Default `"height"`. |
| `value` | number | yes | mm or L | Corrected value. |
| `rule` | string | no | — | Method rule, such as `"6.1"`. |
| `magnitude` | number | no | mm or L | The change. Default `0.0`. |
| `note` | string | no | — | Free text. |

### `exclude[]`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `row` | integer | yes | 1-based data row to leave out. A bare integer is also accepted. |

### `blocking`

| Field | Type | Default | Unit | Meaning |
|---|---|---|---|---|
| `enabled` | boolean | `false` | — | Turn interval blocking on. |
| `target_rise_mm` | number | `20 * sigma_h` | mm | Target rise per block. The floor is `10 * sigma_h`; the ceiling is 100 mm. |

### `lag_checks[]`

| Field | Type | Required | Unit | Meaning |
|---|---|---|---|---|
| `at_mm` | number | no | mm | Level of the check. |
| `readings` | array | yes | min, mm | At least two `[minutes, height]` pairs. A creep of 1 mm or more flags a lag. |

### `strapping`

| Field | Type | Default | Unit | Meaning |
|---|---|---|---|---|
| `step_mm` | number | `10.0` | mm | Table interval. |
| `start_mm` | number | `0.0` | mm | First table level. |

## Validation

The loader stops with a message when a rule fails:

- `raw`, `nominal.r` and `nominal.L` are required.
- `r`, `L` and `sigma_h` must be positive.
- `pour_noise.rel` and `pour_noise.abs` must be non-negative.
- `h0.mode` must be `"fit"` or `"locked"`.
- An object band needs `low` and `high`, and `high` must exceed `low`.
- `exclude` rows are 1-based and must be at least 1.
- A correction row must exist in the data.
- The raw file must exist and hold at least two rows.
- Heights must increase. A non-positive rise is excluded and flagged.

## Shorthands and aliases

- `h0: 0.0` is read as `{"mode": "locked", "value": 0.0}`.
- `brim: 1896.0` is read as `{"reading": 1896.0}`.
- `data` is accepted for `raw`.
- `radius` and `length` are accepted inside `nominal`.
- `pour` is accepted for `pour_noise`.
- `excluded_rows` is accepted for `exclude`.
- `id` is accepted for `tank`.

## Reserved

`joint` is accepted by the loader but not used by the pipeline. Use the
`calib joint` command with several config files instead.
