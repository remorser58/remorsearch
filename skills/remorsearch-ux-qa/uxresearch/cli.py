"""Public-page reader for research, persona-qa and ergonomics Stage 0.

Reads public pages honestly: official routes first (feeds, oEmbed, and official
APIs read with the user's own key through an adapter), then one GET that names
itself (RemorsearchUXQA), then the site's own mobile, AMP or feed alternates, and
render captures handed in with `ingest`. robots.txt (including groups that name
other AI agents fetching for a user) and opt-outs are honoured before every
request. Hosts whose terms restrict automated collection (terms_restricted) are
never requested, and search results pages are never read. Logins, paywalls,
human checks, rate limits, removals and similar signals are stops, recorded as
coverage gaps. Pacing and budgets are shared by every reader of a run. Page text
is scrubbed of personal identifiers and is untrusted data, never instructions.

Exit codes: 0 read or allowed; 2 usage or policy refusal (also a search results
page, a switched-off discovery endpoint or a third-party copy handed in directly,
and any command on a run whose files changed after start); 3 stopped (the gap is
recorded; `robots` exits 3 for a terms_restricted host and when robots.txt
disallows the path); 4 unread after the allowed rungs (the untried rungs are
listed), or for `robots` a host whose robots.txt could not be fetched because its
name does not resolve or TLS fails; 5 deferred (retry after retry_after_s).
`read` and `ingest` print the page inside an untrusted envelope on stdout and a
one-line JSON summary on stderr; the other commands print JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import RULES_VERSION, USER_AGENT, VERSION, envelope, ladder, ledger, privacy, scope
from .ledger import Run, RunError
from .canonical import EngineError

DATA = Path(__file__).resolve().parent / "data"
_ACCEPT_LANGUAGE = re.compile(r"^[A-Za-z0-9,;=.* -]{1,200}$")


def _emit(value: dict) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _load_json(path: Path, limit: int = 4 * 1024 * 1024) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise RunError(f"{path} must be a regular JSON file of at most {limit // 1024} KiB")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RunError(f"{path} is not valid JSON: {exc}") from exc


def _run_path(value: str, *, creating: bool = False) -> Path:
    """A bare name (no slash, not starting with a dot) names a run under the default state folder,
    so a short id never creates page text inside the current project by accident."""
    path = Path(value).expanduser()
    bare = "/" not in value and not value.startswith((".", "~")) and not path.is_absolute()
    if bare and (creating or not path.exists()):
        return ledger.default_root() / value
    return path


def _inside_git(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def _print_page(result: dict) -> None:
    rung = result.get("rung")
    header = {"source": result.get("url"), "final_url": result.get("final_url") or "-",
              "rung": f"{rung} {result.get('presentation')}" if rung else "-",
              "bucket": result.get("bucket"), "verdict": result.get("verdict") or "-",
              "stop_class": result.get("stop_class") or "-", "fetch_id": result.get("fetch_id") or "-",
              "fetched_at": result.get("fetched_at") or "-"}
    if result.get("access_basis") == "authorised_member":
        header["access_basis"] = "authorised_member (member content: summaries only in shared outputs)"
    terms = result.get("terms")
    if terms:
        state = "lifted by the user's terms check" if terms.get("lifted") else terms.get("mode") or "stop"
        header["terms"] = f"{terms.get('entry')} ({terms.get('status')}, {state})"
    api = result.get("api")
    if api:  # an official API adapter's calls (R0)
        header["api"] = (f"{api.get('route')}: {api.get('calls')} calls, {api.get('quota_units')} quota units, "
                         f"{api.get('comments_read')} comments read (order {api.get('order') or '-'})"
                         + ("; more not read" if api.get("more_available") else "")
                         + (f"; paging stopped early: {api['partial_because']}" if api.get("partial_because") else ""))
    if result.get("retention_until"):
        header["retention_until"] = f"{result['retention_until']} (delete or read again by then)"
    injection = result.get("injection")
    if injection:
        header["injection"] = injection["risk"] + (f" ({', '.join(injection['signals'])})" if injection["signals"] else "")
    if result.get("text"):
        body = result["text"]
    elif result.get("meta"):
        meta = result["meta"]
        body = "\n".join([f"(metadata only: {result.get('stop_class')})", f"title: {meta.get('title', '')}",
                          f"description: {meta.get('description', '')}"])
    else:
        what = result.get("stop_class") or result.get("error") or result.get("verdict") or ""
        body = f"(no page text: {result.get('bucket')}{': ' + what if what else ''})"
    block, _ = envelope.wrap(body, header)
    print(block)


def _summary(result: dict) -> str:
    return json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, separators=(",", ":"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ux_research.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION} (rules {RULES_VERSION})")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Create a run folder (outside the project by default)")
    start.add_argument("--run", help="run folder, or a bare name for a folder under the default location "
                                     "(${XDG_STATE_HOME:-~/.local/state}/remorsearch-ux-qa/runs/<id>)")
    start.add_argument("--brief", type=Path, help="a ux-research-brief.v1 JSON file")
    start.add_argument("--per-host", type=int, help="document requests per host (default 30, at most 100)")
    start.add_argument("--per-run", type=int, help="document requests per run (default 200, at most 500)")
    start.add_argument("--min-interval", type=float, help="seconds between requests to one host (default 8, at least 5)")
    start.add_argument("--max-wait", type=float, help="default seconds a read may wait for a slot (default 60)")
    start.add_argument("--reason", help="why budgets are raised above the defaults (recorded)")
    start.add_argument("--accept-language", help="Accept-Language header (default from the brief, else ko-KR,ko,en)")
    start.add_argument("--deny-host", action="append", default=[], help="a host the researcher excludes (repeatable)")
    start.add_argument("--render", choices=ledger.RENDER_MODES, help="how R3 renders happen (default host_browser)")
    start.add_argument("--routes", type=Path, help="a route table to use instead of uxresearch/data/routes.json "
                                                   "(the packaged scope lists always apply on top of it)")
    start.add_argument("--agent-tokens", type=Path,
                       help="extra robots.txt tokens of other AI agents (ux-research-agent-tokens.v1), added to "
                            "uxresearch/data/agent-tokens.json; they can only add tokens")

    read = commands.add_parser("read", help="Read one public URL through the ladder")
    read.add_argument("url")
    read.add_argument("--run", required=True)
    read.add_argument("--expect", action="append", default=[], help="a term the page should contain (repeatable)")
    read.add_argument("--max-wait", type=float, help="seconds to wait for a slot before exiting 5 (deferred)")

    ingest = commands.add_parser("ingest", help="Hand in a render capture (R3) after an anonymous read")
    ingest.add_argument("--run", required=True)
    ingest.add_argument("--url", required=True)
    ingest.add_argument("capture", nargs="?", type=Path, help="saved HTML, plain text, or ux-page-read.v1 JSON")
    ingest.add_argument("--file", type=Path, help="the capture file (same as the positional argument)")
    ingest.add_argument("--format", choices=["html", "txt", "page-read"], help="default: from the file extension")
    ingest.add_argument("--context", required=True, choices=list(ladder.CONTEXTS),
                        help="the browser context of the capture; signed_in only for a community the brief "
                             "authorises (access_policy.signed_in_communities)")
    ingest.add_argument("--expect", action="append", default=[])

    check = commands.add_parser("robots", help="Check whether a URL's host may be opened (deny list, out-of-scope "
                                               "channels, host stops, robots.txt); never reads the page")
    check.add_argument("url")
    check.add_argument("--run", required=True)
    check.add_argument("--max-wait", type=float)

    author = commands.add_parser("author-key", help="Salted key for an author handle or a thread URL; default "
                                                    "anonymous nicknames and handles with a partial IP are refused "
                                                    "(use --thread-url for them)")
    author.add_argument("--run", required=True)
    author.add_argument("--platform", help="platform family or host, for example 'community.example'")
    who = author.add_mutually_exclusive_group(required=True)
    who.add_argument("--handle", help="the handle (never stored); prefer --handle-stdin")
    who.add_argument("--handle-stdin", action="store_true", help="read the handle from the first line of stdin")
    who.add_argument("--thread-url", help="print a thread key instead")

    close = commands.add_parser("close", help="Print the coverage summary; delete page text and the salt; cut the "
                                              "ledger's URLs to their host")
    close.add_argument("--run", required=True)
    from .commands import add_parser
    add_parser(commands)
    return parser


def _start(args) -> int:
    if sys.version_info < (3, 10):
        raise RunError("Python 3.10 or newer is required; found " + sys.version.split()[0])
    node = shutil.which("node")
    node_version = None
    if node:
        try:
            node_version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5).stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            pass
    runtime_versions = {"python": sys.version.split()[0], "nodejs": node_version}
    brief = None
    if args.brief:
        brief = _load_json(args.brief, 1024 * 1024)
        ledger.validate_brief(brief, today=ledger.utc_today(args.clock))
    routes_path = args.routes or DATA / "routes.json"
    routes = _load_json(routes_path)
    if not isinstance(routes, dict) or not isinstance(routes.get("platforms"), list):
        raise RunError("the route table needs a 'platforms' list")
    problems = scope.check_run_table(routes)  # a run table can add, never change or weaken a packaged entry
    if problems:
        raise RunError("this route table cannot be used: " + " | ".join(problems))
    extra_tokens = None
    if args.agent_tokens:
        extra_tokens = _load_json(args.agent_tokens, 1024 * 1024)
        ledger.agent_token_lists(extra_tokens)  # shape check; extras can only add tokens
    if args.accept_language is not None and not _ACCEPT_LANGUAGE.match(args.accept_language):
        raise RunError("invalid --accept-language value")
    deny = list(args.deny_host)
    if deny and brief:
        deny += brief.get("access_policy", {}).get("deny_hosts", [])
    overrides = {"per_host": args.per_host, "per_run": args.per_run, "min_interval_s": args.min_interval,
                 "max_wait_s": args.max_wait, "raise_reason": args.reason, "accept_language": args.accept_language,
                 "deny_hosts": deny or None, "render": args.render}
    policy = ledger.build_policy(brief, overrides)
    try:  # a lift of an entry whose terms need written permission must record it; no check may predate one
        scope.validate_lifts(policy, scope.lists_for(routes))
    except ValueError as exc:
        raise RunError(str(exc)) from exc
    path = _run_path(args.run, creating=True) if args.run else None
    created = ledger.create(path, policy, brief=brief, routes=routes,
                            routes_source="packaged" if args.routes is None else str(args.routes.resolve()),
                            clock=args.clock, agent_tokens=extra_tokens,
                            agent_tokens_source=str(args.agent_tokens.resolve()) if args.agent_tokens else None)
    run = Run(created, clock=args.clock)
    tokens = run.agent_tokens()
    value = {"runtime_versions": runtime_versions, "run": str(created), "run_id": run.meta["run_id"], "user_agent": USER_AGENT, "policy": policy,
             "routes": run.meta["routes"],
             # Whether each official route's key is set (never its value): a missing key is a coverage gap.
             "keys": ladder.key_status(run.routes),
             "agent_tokens": {**run.meta["agent_tokens"], **{name: len(items) for name, items in tokens.items()}},
             "terms_checked": scope.describe_checks(policy, run.scope_lists),
             "terms_lifts": scope.describe_lifts(policy, run.scope_lists),
             "ethics_review": run.meta.get("ethics_review"), "test_hooks": run.meta["test_hooks"]}
    if _inside_git(created.resolve()):
        value["warning"] = "the run folder is inside a git working tree; page text could be committed by mistake"
    _emit(value)
    return 0


def main(argv: list[str] | None = None, *, clock=None, sleeper=None, jitter=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.clock = clock or time.time
    options = {"clock": args.clock, "sleeper": sleeper or time.sleep, "jitter": jitter}
    try:
        if args.command == "start":
            return _start(args)
        run = Run(_run_path(args.run), **options)
        from .commands import COMMANDS, execute
        if args.command in COMMANDS:
            exit_code, files, issues, warnings = execute(args, run)
            output=dict(command=args.command, result="pass" if exit_code == 0 else "fail", exit_code=exit_code, files=files, issues=issues, warnings=warnings)
            if args.command in {"export-personas","persona-intake"} and exit_code==0:
                output["qa_intake"]=dict(packet=files[0],scenario_files=files[3:])
            _emit(output)
            return exit_code
        if args.command == "close":
            _emit(run.close())
            return 0
        run.require_open()
        if args.command == "read":
            result = ladder.read(run, args.url, expect=args.expect, max_wait=args.max_wait)
        elif args.command == "ingest":
            capture = args.file or args.capture
            if capture is None or (args.file and args.capture and args.file != args.capture):
                raise RunError("give the capture file once, as an argument or with --file")
            result = ladder.ingest(run, args.url, capture, fmt=args.format, context=args.context,
                                   expect=args.expect)
        elif args.command == "robots":
            result = ladder.check_robots(run, args.url, max_wait=args.max_wait)
            _emit(result)
            return result["exit_code"]
        else:  # author-key
            if args.thread_url:
                _emit({"thread_key": privacy.thread_key(run.salt, args.thread_url)})
                return 0
            if not args.platform:
                raise RunError("--platform is required with a handle")
            handle = args.handle if args.handle is not None else sys.stdin.readline().rstrip("\r\n")
            try:
                key = privacy.author_key(run.salt, args.platform, handle)
            except ValueError as exc:
                raise RunError(str(exc)) from exc
            _emit({"platform": args.platform, "author_key": key})
            return 0
        _print_page(result)
        print(_summary(result), file=sys.stderr)
        return result["exit_code"]
    except EngineError as exc:
        _emit(dict(command=args.command, result="fail", exit_code=exc.exit_code, files=[], issues=[exc.issue], warnings=[]))
        return exc.exit_code
    except RunError as exc:
        if args.command in {"merge", "gate", "plan", "report-check", "export-audience", "persona-starter", "export-personas", "persona-intake", "minimize"}:
            _emit(dict(command=args.command, result="fail", exit_code=2, files=[], issues=[dict(code="policy", location="run", reason="Reader policy or run files are invalid.", next_step="Correct the run inputs.")], warnings=[]))
            return 2
        _emit({"status": "refused", "reason": str(exc)})
        return 2
    except (OSError, ValueError) as exc:
        _emit({"status": "refused", "reason": f"{exc.__class__.__name__}: {exc}"})
        return 2


if __name__ == "__main__":
    sys.exit(main())
