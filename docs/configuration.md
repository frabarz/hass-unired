# Configuration

## Pairing a Unired account

Settings → Devices & Services → Add Integration → Unired. One form asks for:

- **RUT** — as shown in the app (`12.345.678-9`); dots and dashes are
  stripped before sending, exactly like the official app.
- **E-mail** — the address registered with Unired.
- **Full name** — only used if you are not registered yet.
- **Terms checkbox** — required; the accepted terms id is sent to Unired on
  the registration branch, mirroring the app's guest form.

What happens next depends on the server:

- **Known device** (re-pairing the same HA install): entry is created
  immediately, no code needed.
- **New user** (`0603`): a code is e-mailed, you type the 4 digits, the
  account completes, and pairing continues below.
- **New device** (`0630`): a code is e-mailed, you type the 4 digits, done.

There is **no resend button**: Unired's resend endpoints are dead server-side.
Submitting an OTP screen again requests a fresh code — only the newest code
works, and codes expire after a few minutes (the device-pairing cooldown is
60 s). Codes are single-attempt: a wrong code shows an error, never a retry
loop, because the server locks codes after repeated failures.

## Linking more services (water, light, internet, …)

Each config entry holds one Unired user; every utility linked to that user
becomes sensors automatically. Manage links from the entry's **Configure**
button (no YAML, changes apply server-side so the app agrees):

- **Link a service** — pick the company from the live catalog (126
  companies; falls back to manual UUID entry if the catalog is unreachable),
  then enter the **identifier** (usually the holder's RUT — it defaults to
  yours, so linking family accounts just means typing their RUT) and a
  **nickname**. Sensors appear after the automatic reload.
- **Unlink services** — multi-select accounts to remove from Unired, then
  reload. Sensors vanish with them.
- **Polling settings** — scan interval in seconds, 3600–86400, default
  21600 (6 h). Bills change monthly; there is no reason to poll faster.

## Re-authentication

If Unired closes the session from another device (`0509`/`0605`), Home
Assistant opens a reauth flow: submit once to receive a fresh code, type it,
and the stored tokens are replaced. No other action needed.

Next: [Entities](entities.md).
