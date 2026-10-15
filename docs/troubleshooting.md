# Troubleshooting

## Sensor reads `unknown`

No poll data yet (first refresh pending), or this instrument's debt request
failed while the rest succeeded. It recovers on the next poll — no action
needed. Persistent `unknown` on all sensors points at auth (see below).

## Server codes and what to do

| Code | Meaning | Action |
|---|---|---|
| `0603` | User not registered | The flow routes you into registration automatically |
| `0630` | Device not paired | The flow sends a pairing code automatically |
| `0907` | Device already registered | Log in instead of pairing; retry the flow |
| `0407`/`0500` | Wrong code | Type the newest code carefully, once |
| `0408` | Code locked (too many attempts) | Restart the flow for a fresh code |
| `0604` | No valid code | Restart the flow for a fresh code |
| `0427`/`0428` | Debt lookup error | Retry later; the account may be mid-update |
| `0509`/`0605` | Session closed (new device / logout) | Complete the reauth flow when prompted |
| `0700`/`0701` | Token expired | Automatic refresh; reauth only if it persists |
| `0801` | Unired external error | Retry later |

## No OTP e-mail arrives

- Check spam, and confirm the address actually delivers: disabled/deleted
  relay masks never receive anything while the server still answers success.
- There is no resend button (Unired's resend endpoints are broken). Submit
  the current screen again to request a fresh code; only the newest works.
- Wait out the 60 s pairing cooldown before requesting another.

## Reauth loops

Persistent `0509` right after pairing means something else logs in as the
same device (duplicate fingerprint). Remove the extra entry or re-pair once
more; tokens rotate on every refresh, so only the newest session survives.

## Backend changes

The unofficial backend may enforce a newer app version. If requests start
failing across the board, bump `APP_VERSION`/`BUILD_NUMBER` in
`custom_components/unired/const.py` (currently `1.18.2`/`410`) and reload.

## Diagnostics & privacy

Entry diagnostics (⋮ → Download diagnostics) redact tokens, device ids,
e-mail, RUT, contract numbers, and holder names/addresses. Company names,
amounts, and debt types are backend data and stay visible.

## Still stuck?

Open an issue with the diagnostics download attached and note the account
company, the time, and which step failed.
