# Content Security Policy readiness

## Decision

Blocking CSP remains deferred. The server sends the intended strict policy as
`Content-Security-Policy-Report-Only` because served frontend pages still contain
inline scripts, HTML event-handler attributes, `<style>` elements, and `style`
attributes. Enforcing `script-src 'self'` and `style-src 'self'` now would disable
existing login, navigation, form, review, and administration behavior.

The admin page's Bootstrap 5.3.0 and Font Awesome 6.4.0 CDN references were
replaced with the matching assets already stored under `frontend/vendor/`. No
`unsafe-inline`, external CDN allowlist, nonce, or hash exception was added.

## Safety gate

Run `node tests/csp_readiness_selfcheck.js`. It scans every served HTML file and
first-party JavaScript-generated markup, rejects a blocking CSP while detectable
violations remain, requires report-only observation during the deferral, and
rejects new remote asset references. It is also included automatically by
`node tests/run_selfchecks.js`.

Move to `Content-Security-Policy` only after the audit reports no blockers and
browser testing confirms the login, user, reviewer, and admin workflows under
the enforcing policy.

`Strict-Transport-Security` is intentionally absent. Add HSTS only after the
deployment is confirmed to be HTTPS-only, including every hostname and entry
point used by this application.
