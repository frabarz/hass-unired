# Entities

One device per linked utility account (manufacturer = company, model =
industry, e.g. `CGE S.A.` / `Luz`), named after the account nickname
(`CORE Luz`, …). Each device carries one sensor per billable instrument
(accounts normally have exactly one).

## `sensor.<nickname>_bill_amount` — Bill amount

| Aspect | Value |
|---|---|
| State | Total owed in CLP: sum of bill lines with `amount > 0` |
| `0` | No debt: empty bill list or all-zero lines (nothing prepared) |
| `unknown` | No poll data yet, or this instrument's debt poll failed |
| Device class / unit | `monetary` / `CLP` |
| `amount > 0` | ⟺ a bill is prepared and payable |

No separate "prepared" binary sensor: trigger automations on the numeric
state crossing above `0`.

### Attributes

- `bills[]` — per line: `amount`, `debt_type` (e.g. `Deuda Total`),
  `due_date` (from `FECVEN`, null when the backend sends none),
  `contract` (from `NUMCON`), `selected`.
- `bill_count` — number of lines (owed + paid).
- `company`, `account_identifier`, `account_nickname` — who/which account.
- `allows_credit`, `accept_zero_debt` — backend payment flags.
- `presentation_rule[]` — backend debt-type codes (`AUTODE`, `MTKPU`, …).

`unique_id` is `{account_uuid}_{instrument_uuid}` (stable server ids), so
renaming a nickname never duplicates entities.

Next: [Dashboards](dashboards.md).
