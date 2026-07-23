# Viewer and Admin boundary

| Capability | Viewer | Admin |
|---|---:|---:|
| Read published reports and PDFs | yes | yes |
| Read sector opinions | yes | yes |
| See drafts, failures and unmapped terms | no | yes |
| Upload and parse PDF | no | yes |
| Confirm date and review fields | no | yes |
| Publish or withdraw | no | yes |

Authentication is enforced in FastAPI with a signed, HttpOnly, SameSite=Strict cookie. Passwords and the session secret come from environment variables. The frontend contains no password or permission decision. There is no registration, password recovery, email, SMS, OAuth or SSO.

This is not a production identity platform. Local accounts are deliberately limited and must not be exposed publicly.
