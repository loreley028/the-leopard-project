from __future__ import annotations

from leopard_project.market_paths import load_market_path_registry
from leopard_project.providers.capabilities import load_provider_capabilities, provider_capability_summary


def main() -> None:
    rows = load_provider_capabilities()
    registry = load_market_path_registry()
    summary = provider_capability_summary(rows)
    if summary["matrix_total"] != len(registry.supported_market_paths):
        raise SystemExit(f"capability count mismatch: {summary!r}")
    if summary["operational_coverage"] + summary["unverified"] != summary["matrix_total"]:
        raise SystemExit(f"capability classification mismatch: {summary!r}")
    if "hotel_catering" in rows or "hotel" not in rows or "catering" not in rows:
        raise SystemExit("hotel/catering market-path split is invalid")
    print(f"Provider capability matrix valid: {summary}")


if __name__ == "__main__":
    main()
