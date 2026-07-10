#!/usr/bin/env python3
"""Unified CLI — Create definition → Create/start Run → Poll & download outputs.

Subcommands:
  define    Create a workflow definition
  run       Create a Run draft
  start     Start an existing Run draft
  download  Poll until complete and download outputs

Examples:
  python cli.py define --name 'compliance-review' --parent-folder-id <UUID>
  python cli.py run --definition-id <UUID> --name 'my-run' --input-scope <UUID>
  python cli.py start --run-id <UUID>
  python cli.py download --run-id <UUID>
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from ksapi.api.workflow_runs_api import WorkflowRunsApi
from ksapi.exceptions import ApiException
from ksclient import client
from logic import (
    create_definition,
    create_run,
    download_outputs,
    poll_run,
    start_run,
)

_DOCUMENT_PART_TYPE = "DOCUMENT"


# ── Helpers ──────────────────────────────────────────────────────────────


def _default_name() -> str:
    return datetime.now(UTC).strftime("Workflow-%Y%m%d-%H%M%S")


def _value(enum_or_str):
    return str(getattr(enum_or_str, "value", enum_or_str))


def _normalize_input_scope(raw: str | None) -> str | None:
    """Normalize --input-scope to a JSON array string.

    - None         → None
    - '["a","b"]'  → pass-through
    - "uuid"       → '["uuid"]' (auto-wrap bare string)
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped.startswith("["):
        return stripped
    return f'["{stripped}"]'


# ── Top-level parser ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KS Workflow CLI — Unified entrypoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", title="Subcommands")

    # ── define ───────────────────────────────────────────────────────
    p_def = sub.add_parser(
        "define",
        help="Create a workflow definition",
        description="Create a workflow definition",
        epilog="Example: python cli.py define --name 'compliance-review' --parent-folder-id <UUID>",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_def.add_argument("--name", default=os.environ.get("KS_WF_NAME", _default_name()))
    p_def.add_argument("--description", default="")
    p_def.add_argument(
        "--parent-folder-id", type=UUID, default=os.environ.get("KS_PARENT_FOLDER_ID")
    )
    p_def.add_argument(
        "--approval-required",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("KS_APPROVAL_REQUIRED", "true").lower() == "true",
    )
    p_def.add_argument(
        "--max-run-duration", type=int, default=int(os.environ.get("KS_MAX_RUN_DURATION", "1800"))
    )
    p_def.add_argument("--is-template", action="store_true", default=False)
    p_def.add_argument("--json", action="store_true", dest="json_output")

    # ── run ──────────────────────────────────────────────────────────
    p_run = sub.add_parser(
        "run",
        help="Create a Run draft",
        description="Create a Workflow Run draft",
        epilog="Example: python cli.py run --definition-id <UUID> --name 'my-run' --input-scope <UUID>",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument("--definition-id", type=UUID, required=True)
    p_run.add_argument("--name", required=True)
    p_run.add_argument("--input-scope", default=None)
    p_run.add_argument("--input-files", nargs="*", default=None)
    p_run.add_argument("--auto-start", action="store_true")
    p_run.add_argument("--user-message", default=None)
    p_run.add_argument("--json", action="store_true", dest="json_output")

    # ── start ────────────────────────────────────────────────────────
    p_start = sub.add_parser(
        "start",
        help="Start an existing Run draft",
        description="Start an existing Workflow Run draft",
        epilog="Example: python cli.py start --run-id <UUID>",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_start.add_argument("--run-id", type=UUID, required=True)
    p_start.add_argument("--user-message", default=None)
    p_start.add_argument("--json", action="store_true", dest="json_output")

    # ── download ─────────────────────────────────────────────────────
    p_dl = sub.add_parser(
        "download",
        help="Poll and download outputs",
        description="Poll until Run completes and download outputs",
        epilog="Example: python cli.py download --run-id <UUID>",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_dl.add_argument("--run-id", type=UUID, required=True)
    p_dl.add_argument(
        "--out-dir", type=Path, default=Path(os.environ.get("KS_OUT_DIR", "./workflow_outputs"))
    )
    p_dl.add_argument(
        "--poll-interval", type=int, default=int(os.environ.get("KS_POLL_INTERVAL", "10"))
    )
    p_dl.add_argument(
        "--max-wait", type=int, default=int(os.environ.get("KS_MAX_WAIT_SECONDS", "600"))
    )
    p_dl.add_argument("--no-wait", action="store_true")
    p_dl.add_argument("--dry-run", action="store_true")
    p_dl.add_argument("--json", action="store_true", dest="json_output")

    return parser


# ── Subcommand handlers ──────────────────────────────────────────────────


def cmd_define(args: argparse.Namespace) -> int:
    if not args.parent_folder_id:
        print("Missing --parent-folder-id or KS_PARENT_FOLDER_ID", file=sys.stderr)
        return 2

    try:
        result = create_definition(
            name=args.name,
            description=args.description,
            parent_folder_id=args.parent_folder_id,
            approval_required=args.approval_required,
            max_run_duration_seconds=args.max_run_duration,
            is_template=args.is_template,
        )
    except ApiException as exc:
        detail = str(exc)
        print(f"[Failed] ({exc.status}) Creating definition failed", file=sys.stderr)
        if "Parent path_part not found" in detail:
            print(f"  → Invalid parent folder UUID: {args.parent_folder_id}", file=sys.stderr)
        else:
            print(f"  {detail}", file=sys.stderr)
        return 1

    if args.json_output:
        print(
            json.dumps(
                {
                    "id": str(result.id),
                    "name": result.name,
                    "path_part_id": str(result.path_part_id),
                    "instruction_path_part_id": str(result.instruction_path_part_id),
                    "parent_path_part_id": str(result.parent_path_part_id)
                    if result.parent_path_part_id
                    else None,
                    "approval_required": result.approval_required,
                    "is_template": result.is_template,
                    "created_at": result.created_at.isoformat() if result.created_at else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("Workflow definition created")
        print(f"   ID              : {result.id}")
        print(f"   Name            : {result.name}")
        print(f"   Instruction     : {result.instruction_path_part_id}")
        print(f"   Approval req    : {result.approval_required}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        run = create_run(
            definition_id=args.definition_id,
            name=args.name,
            input_scope=_normalize_input_scope(args.input_scope),
            auto_start=args.auto_start,
            user_message=args.user_message,
            input_file_paths=args.input_files,
        )
    except ApiException as exc:
        print(f"[Create Run failed] ({exc.status})", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    result = {
        "run_id": str(run.id),
        "name": run.name,
        "inputs_path_part_id": str(run.inputs_path_part_id),
        "execution_state": run.execution_state.value if run.execution_state else None,
    }

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Run draft created")
        print(f"   Run ID            : {run.id}")
        print(f"   Name              : {run.name}")
        print(f"   Inputs path       : {run.inputs_path_part_id}")
        print(f"   State             : {run.execution_state}")
        if args.auto_start:
            print("Auto-start armed — ingestion will trigger automatic start")
        else:
            print("Next: python cli.py start --run-id", run.id)

    return 0


def cmd_start(args: argparse.Namespace) -> int:
    try:
        started = start_run(run_id=args.run_id, user_message=args.user_message)
    except ApiException as exc:
        print(f"[Start Run failed] ({exc.status})", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(started, ensure_ascii=False, indent=2))
    else:
        print("Run started")
        print(f"   Run ID            : {started['run_id']}")
        print(f"   State             : {started['execution_state']}")
        print(f"   Approval          : {started['approval_state']}")

    return 0


def cmd_download(args: argparse.Namespace) -> int:
    # ── Poll ──
    if args.no_wait:
        print("Skipping poll (--no-wait)", file=sys.stderr)
        try:
            api = WorkflowRunsApi(client)
            run = api.get_workflow_run(args.run_id)
        except ApiException as exc:
            print(f"[Get Run failed] ({exc.status}): {exc}", file=sys.stderr)
            return 1
    else:
        print("Polling until run completes ...", file=sys.stderr)
        run = poll_run(run_id=args.run_id, poll_interval=args.poll_interval, max_wait=args.max_wait)
        if run is None:
            print("[Failed or timed out]", file=sys.stderr)
            return 1
        print("Run completed", file=sys.stderr)

    # ── Download ──
    if args.dry_run:
        document_ids = [
            asset.id
            for asset in (run.output_assets or [])
            if _value(asset.part_type) == _DOCUMENT_PART_TYPE
        ]
        result = {
            "run_id": str(run.id),
            "run_name": run.name or "",
            "dry_run": True,
            "count": len(document_ids),
            "dest_dir": str(args.out_dir / (run.name or str(run.id))),
        }
    else:
        result = download_outputs(run=run, out_dir=args.out_dir)

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if result.get("error"):
        print(f"{result['error']}")
        return 1

    if result.get("dry_run"):
        print()
        print(f"  Run: {result['run_name']} ({result['run_id']})")
        print(f"  Pending documents: {result['count']}")
        print(f"  Target dir: {result['dest_dir']}")
        print()
        return 0

    print()
    print("Download complete")
    print(f"   Run ID       : {result['run_id']}")
    print(f"   Files        : {result['file_count']}")
    if result.get("skipped"):
        print(f"   Skipped      : {result['skipped']}")
    print(f"   Dest         : {result['dest_dir']}")
    print()
    return 0


# ── Main entrypoint ──────────────────────────────────────────────────────

_HANDLERS = {
    "define": cmd_define,
    "run": cmd_run,
    "start": cmd_start,
    "download": cmd_download,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
