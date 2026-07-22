from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import CONFIG_DIR, PROJECT_ROOT
from .eod import EodStatus, FixtureTradingCalendar, load_eod_policy
from .mappings import approve_research_version
from .reconciliation import run_controlled_replay
from .provider_validation import run_validation
from .provider_selection import run_provider_selection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leopard-project")
    commands = parser.add_subparsers(dest="command", required=True)
    mappings = commands.add_parser("mappings")
    mapping_commands = mappings.add_subparsers(dest="mapping_command", required=True)
    approve = mapping_commands.add_parser("approve-research-version")
    approve.add_argument("--version", required=True)
    approve.add_argument("--effective-date", type=date.fromisoformat)
    approve.add_argument("--output", type=Path, help="write a new versioned preview; never updates the seed in place")
    providers = commands.add_parser("providers")
    provider_commands = providers.add_subparsers(dest="provider_command", required=True)
    validate = provider_commands.add_parser("validate-live")
    validate.add_argument("--scope", choices=("representative", "all"), default="representative")
    validate.add_argument("--output-dir", type=Path)
    select = provider_commands.add_parser("select-phase1b0")
    select.add_argument("--output-dir", type=Path, default=Path("data/provider-selection"))
    market = commands.add_parser("market")
    market_commands = market.add_subparsers(dest="market_command", required=True)
    eod_status = market_commands.add_parser("eod-status")
    eod_status.add_argument("--provider", choices=("ths_public",), required=True)
    eod_status.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    provider = commands.add_parser("provider")
    provider_commands_singular = provider.add_subparsers(dest="provider_command_singular", required=True)
    compare = provider_commands_singular.add_parser("compare")
    compare.add_argument("--sector-key", required=True)
    compare.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile_commands = reconcile.add_subparsers(dest="reconcile_command", required=True)
    reconcile_run = reconcile_commands.add_parser("run")
    reconcile_run.add_argument("--mode", choices=("validation", "replay"), required=True)
    reconcile_run.add_argument("--trade-date", type=date.fromisoformat, required=True)
    reconcile_run.add_argument("--live", action="store_true")
    reconcile_run.add_argument("--confirm-network", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "mappings" and args.mapping_command == "approve-research-version":
        source = CONFIG_DIR / "sector_mappings_v2_3.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        approved = approve_research_version(document, args.version, effective_date=args.effective_date)
        if args.output:
            if args.output.resolve() == source.resolve():
                raise SystemExit("refusing to overwrite the checked-in research seed")
            if args.output.exists():
                raise SystemExit(f"refusing to overwrite existing output: {args.output}")
            args.output.write_text(json.dumps(approved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        eligible = sum(1 for row in approved["mappings"] if row["included_in_daily_job"])
        print(json.dumps({"new_version": approved["mapping_version"], "approved": 66, "daily_job_eligible": eligible}, ensure_ascii=False))
        return 0
    if args.command == "providers" and args.provider_command == "validate-live":
        coverage = run_validation(scope=args.scope, output_dir=args.output_dir)
        print(json.dumps(coverage["summary"], ensure_ascii=False, default=str))
        return 0
    if args.command == "providers" and args.provider_command == "select-phase1b0":
        coverage, comparison = run_provider_selection(output_dir=args.output_dir)
        print(json.dumps({"coverage": coverage["summary"], "selection_conclusion": comparison["selection_conclusion"]}, ensure_ascii=False, default=str))
        return 0
    if args.command == "market" and args.market_command == "eod-status":
        if args.as_of.tzinfo is None or args.as_of.utcoffset() is None:
            raise SystemExit("--as-of must include an explicit timezone offset")
        policy = load_eod_policy()
        calendar = FixtureTradingCalendar.from_file()
        expected = calendar.expected_trade_date(args.as_of, policy.safe_time("ths_public_validation"))
        coverage = json.loads((PROJECT_ROOT / "data/provider-selection/coverage_65.json").read_text(encoding="utf-8"))
        local = args.as_of.astimezone(ZoneInfo(policy.timezone))
        counts = {status.value: 0 for status in EodStatus}
        for row in coverage["results"]:
            latest = date.fromisoformat(row["latest_trade_date"])
            if latest > expected and latest == local.date() and local.time() < policy.safe_time("ths_public_validation"):
                status = EodStatus.INTRADAY_SNAPSHOT
            elif latest > expected:
                status = EodStatus.FUTURE_SNAPSHOT
            elif latest < expected:
                status = EodStatus.STALE_SNAPSHOT
            else:
                status = EodStatus.COMPLETE_EOD
            counts[status.value] += 1
        print(json.dumps({
            "provider": "ths_public_validation",
            "network_access": False,
            "policy_version": policy.policy_version,
            "requested_as_of": args.as_of.isoformat(),
            "expected_trade_date": expected.isoformat(),
            "status_counts": counts,
        }, ensure_ascii=False))
        return 0
    if args.command == "provider" and args.provider_command_singular == "compare":
        details = json.loads(
            (PROJECT_ROOT / "data/reconciliation-validation/reconciliation_details.json").read_text(encoding="utf-8")
        )
        record = next((row for row in details["records"] if row["sector_key"] == args.sector_key), None)
        if record is None:
            raise SystemExit(f"sector key is not present in controlled replay: {args.sector_key}")
        print(json.dumps({"network_access": False, "requested_as_of": args.as_of.isoformat(), "record": record}, ensure_ascii=False))
        return 0
    if args.command == "reconcile" and args.reconcile_command == "run":
        if args.live and not args.confirm_network:
            raise SystemExit("live validation requires both --live and --confirm-network")
        if args.mode == "validation":
            raise SystemExit("live dual-source validation is not available; use --mode replay")
        if args.live:
            raise SystemExit("replay mode cannot enable network access")
        summary, _ = run_controlled_replay(trade_date=args.trade_date)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
