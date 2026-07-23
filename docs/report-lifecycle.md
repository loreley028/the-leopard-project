# Report lifecycle

```text
uploaded → parsing → needs_review → ready_to_publish → published → withdrawn
                ↘ parse_failed → parsing
```

Transitions are explicit and validated by the service. `ready_to_publish` requires an administrator-confirmed report date and no unresolved term. Publishing is idempotent and records actor/time. Withdrawal requires a reason and removes the report from Viewer queries.

Published structured content is never silently overwritten: a pre-change snapshot is written to `ReportRevision`. Stale or duplicate publish requests cannot create a second published report or destroy current state.
