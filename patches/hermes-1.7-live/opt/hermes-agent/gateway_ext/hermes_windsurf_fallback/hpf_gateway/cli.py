from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config_loader import default_plan_first_config, load_fallback_config
from .fallback_router import FallbackRouter
from .plan_pipeline import notion_plan_to_md
from .provider_client import ProviderClient
from .smart_router import route_decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Windsurf fallback MVP CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("idea")
    plan.add_argument("--session-id", default="local")
    plan.add_argument("--dry-run", action="store_true")
    route = sub.add_parser("dry-route")
    route.add_argument("message")
    route.add_argument("--config", default="config/fallback-chain.yaml")
    args = parser.parse_args()

    if args.command == "plan":
        client = ProviderClient()
        result = notion_plan_to_md(args.idea, args.session_id, default_plan_first_config(), client, dry_run=args.dry_run)
        print(json.dumps({"path": str(result.path), "state_path": str(result.state_path), "tasks": result.task_count, "used_fallback": result.used_fallback}, indent=2))
        return 0
    if args.command == "dry-route":
        decision = route_decision(args.message)
        config = load_fallback_config(Path(args.config))
        router = FallbackRouter(config, ProviderClient())
        result = router.call_with_fallback({"prompt": args.message}, "local", args.message[:100], dry_run=True)
        print(json.dumps({"decision": decision.__dict__, "fallback": result}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
