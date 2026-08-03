# Cloud market connectivity probe runbook

Use this only during an A-share session, preferably 09:45–10:15 Asia/Shanghai.
It is a one-pass capability inventory, not a Scheduler or deployment procedure.

1. Establish the user-authorized SSH ControlMaster; never pass or store a password.
2. Create a `git archive` of the approved feature-branch commit and upload it to a new
   `/opt/the-leopard-project/staging/provider-connectivity/<sha>/` directory.
3. Extract it there and run a one-shot container from the formal API image with the
   staging source mounted read-only. Do not mount `shared/`, production SQLite,
   uploads, `production.env`, or the formal current release.
4. Run: `PYTHONPATH=backend python3.12 scripts/validate_cloud_market_connectivity.py --environment-label cloud --include-history --output-dir var/provider-validation`.
5. Copy back only the JSON, CSV and Markdown summaries. They are diagnostic artifacts
   and stay out of Git. Do not retain raw Provider responses.
6. Confirm `leopard-api` and `leopard-web` container IDs/restart counts and the formal
   SQLite/report/PDF/frozen-snapshot counts are unchanged before and after the run.
7. Stop and remove the one-shot container and its staging directory after results have
   been preserved outside the repository.

The probe is core feasible at 60 or more spot-operational paths, partial at 55–59,
and insufficient below 55. History and MA5 are separate metrics. The result determines
the next MVP coverage decision; it does not authorize production promotion or deployment.
