# Secondary-source validation

## AKShare investigation

AKShare 1.18.64 was inspected as a temporary research dependency, not added to project dependencies. Its industry and concept history implementations resolve names/codes and then request the same Tonghuashun v4 chart endpoint used by the current diagnostic adapter.

Result:

- independence status: `shared_upstream`;
- failure-isolation value: not established;
- service SLA: none;
- independent authorization: not established;
- role: `research_provider` only.

The controlled replay records Provider B success as zero because no independent second dataset was available. It does not copy Provider A values into Provider B and does not convert identical upstream data into a dual-source success.

The optional AKShare package source was obtained and inspected, but a complete temporary dependency installation could not finish because the dependency network became unavailable. Live execution is recorded as `blocked_by_dependency_network`; no success was fabricated.

An independent second source remains a prerequisite for meaningful dual-source reconciliation. This may require another documented/authorized vendor, but Phase 1B-1 requests neither a Token nor a purchase.
