"""One foreground entry point. No live tool installation, auto-deploy, or background loop."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import merge_packet, require_packet, validate_packet
from .engine import report, run
from .evidence import Evidence
from .io import ContractError, GateStop, atomic_bytes, atomic_json, code_snapshot, digest, load_json, within
from .storage import PHASES, load as load_checkpoint

ROOT = Path(__file__).resolve().parents[1]
EXIT = {"complete": 0, "blocked": 3, "unknown": 4, "failed": 5, "interrupted": 6, "iteration_limit": 7}


def emit(value: dict) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def output_path(path: Path) -> None:
    if ".git" in path.parts:
        raise ContractError("Output paths cannot traverse symlinks or .git")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ContractError(
            "Output paths cannot traverse symlinks or .git. Choose the canonical "
            "directory inside the authorized workspace; on macOS use /private/tmp "
            "instead of the /tmp symlink."
        )


def execution_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--grant", action="append", default=[], choices=["code_write", "design_write", "test_data_write"])
    parser.add_argument("--revoke", action="append", default=[], choices=["code_write", "design_write", "test_data_write"])
    parser.add_argument("--intent-decisions", type=Path, help="Operator-authored context-bound intent decisions; never provider input")
    parser.add_argument("--actor", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--pause-after", choices=PHASES[:-1])
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--report", type=Path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validator = commands.add_parser("validate", help="Validate packet graph; optional local artifact hash checks")
    validator.add_argument("packet", type=Path)
    validator.add_argument("--evidence-root", type=Path)
    fresh = commands.add_parser("run", aliases=["improve"], help="Research intake -> plan -> QA -> authorized fixes -> replay -> decision")
    fresh.add_argument("packet", type=Path)
    fresh.add_argument("--checkpoint", type=Path, required=True)
    fresh.add_argument("--workspace", type=Path, required=True)
    fresh.add_argument("--evidence-root", type=Path, required=True)
    execution_options(fresh)
    resume = commands.add_parser("resume", help="Resume exactly the persisted goal and explicit grants")
    resume.add_argument("--checkpoint", type=Path, required=True)
    resume.add_argument("--input", type=Path, help="Append-only extension of the original packet")
    resume.add_argument("--workspace", type=Path)
    resume.add_argument("--evidence-root", type=Path)
    execution_options(resume)
    demo = commands.add_parser("demo", help="Fixture-only pipeline with an actual patch to a disposable local site")
    demo.add_argument("--output", type=Path, required=True)
    execution_options(demo)
    rev = commands.add_parser("revision", help="Compute the content hash of the explicitly declared code scope")
    rev.add_argument("--workspace", type=Path, required=True)
    rev.add_argument("--path", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "revision":
            emit({"code_revision": digest(code_snapshot(args.workspace, args.path)), "code_scope": args.path})
            return 0
        if args.command == "validate":
            packet = load_json(args.packet)
            errors = validate_packet(packet)
            if not errors and args.evidence_root:
                evidence = Evidence(packet, args.evidence_root)
                for item in packet["artifacts"]:
                    try:
                        evidence.artifact(item["id"])
                    except (GateStop, ContractError, OSError) as exc:
                        errors.append(str(exc))
            emit({"valid": not errors, "errors": errors, "completion_assessed": False})
            return 1 if errors else 0
        if args.command == "demo":
            output_path(args.output)
            args.checkpoint = args.output / "checkpoint.json"
            args.workspace = args.output / "site"
            args.evidence_root = ROOT / "examples" / "loop"
            packet = load_json(ROOT / "examples" / "loop" / "packet.json")
            args.workspace.mkdir(parents=True, exist_ok=True)
            for name in packet["goal"]["code_paths"]:
                target = within(args.workspace, name)
                if not target.exists() and not args.checkpoint.exists():
                    atomic_bytes(target, within(ROOT / "examples" / "loop" / "site", name).read_bytes(), 0o644)
        else:
            source = args.packet if args.command in {"run", "improve"} else args.input
            packet = load_json(source) if source else None
            if source and args.checkpoint.resolve() == source.resolve():
                raise ContractError("Checkpoint cannot overwrite the input packet")
        output_path(args.checkpoint)
        if args.checkpoint.suffix == ".lock":
            raise ContractError("Checkpoint cannot use a lock filename")
        existing = load_checkpoint(args.checkpoint) if args.checkpoint.exists() else None
        effective = packet or (existing["packet"] if existing else None)
        if packet is not None:
            require_packet(packet)
            if existing and packet != existing["packet"]:
                effective = merge_packet(existing["packet"], packet)
        effective_workspace = args.workspace or (Path(existing["workspace"]) if existing else None)
        effective_root = args.evidence_root or (Path(existing["evidence_root"]) if existing else None)
        protected = set()
        if effective_workspace and effective:
            protected.update(within(effective_workspace, name).resolve() for name in effective["goal"]["code_paths"])
        if effective_root and effective:
            protected.update(within(effective_root, item["path"]).resolve() for item in effective["artifacts"])
        source = getattr(args, "packet", None) or getattr(args, "input", None)
        if source:
            protected.add(source.resolve())
        if args.intent_decisions:
            protected.add(args.intent_decisions.resolve())
        if args.checkpoint.resolve() in protected:
            raise ContractError("Checkpoint cannot overwrite input, code or evidence")
        if args.report:
            output_path(args.report)
            protected.update({args.checkpoint.resolve(), args.checkpoint.with_suffix(".lock").resolve()})
            if effective_workspace:
                protected.add((effective_workspace / ".ux-loop" / "workspace.lock").resolve())
            if args.report.resolve() in protected:
                raise ContractError("Report cannot overwrite input, code, evidence, checkpoint or its locks")
        state = run(packet, args.checkpoint, args.workspace, args.evidence_root,
                    grants=args.grant, revokes=args.revoke, actor=args.actor, reason=args.reason,
                    intent_decisions=load_json(args.intent_decisions) if args.intent_decisions else None,
                    require_product_context=args.command == "improve",
                    pause_after=args.pause_after, retry=args.retry, max_steps=args.max_steps)
        result = report(state)
        if args.report:
            protected = {within(Path(state["workspace"]), name).resolve() for name in state["packet"]["goal"]["code_paths"]}
            if args.report.resolve() in protected:
                raise ContractError("Report cannot overwrite product code")
            atomic_json(args.report, result)
        emit(result)
        return EXIT[state["status"]]
    except GateStop as exc:
        emit({"status": exc.status, "reason": exc.reason, "product_complete": False})
        return EXIT.get(exc.status, 2)
    except (ContractError, OSError, UnicodeError, RecursionError) as exc:
        emit({"status": "invalid", "reason": str(exc), "product_complete": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
