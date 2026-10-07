"""Offline engine command surface and sanitized errors."""
from __future__ import annotations

from pathlib import Path

from .canonical import EngineError
from .storage import Store,read_bytes,read_json,safe_path,scenario_output
from .engine import fresh,gate_command,merge_command

COMMANDS={"merge","gate","plan","report-check","export-audience","persona-starter","export-personas","persona-intake","minimize"}

HELP={"merge":"Merge typed reader returns with authoritative captures","gate":"Regrade every claim and check the research process","plan":"Initialize and preflight the axes plan, acknowledgements and empty search ledger together","report-check":"Check report order, citations and statement mapping","export-audience":"Export an honest incomplete audience draft","persona-starter":"Write an authored-input starter of gated claim cards and diagnostics for synthetic persona hypotheses","export-personas":"Export authored synthetic persona/scenario hypotheses as a QA packet and ergo scenario skeletons","minimize":"Create an allowlisted loop projection"}
HELP["persona-intake"]="기존 QA가 바로 읽을 수 있는 현재 페르소나 패킷과 시나리오 경로를 검증해 반환합니다."


def add_parser(commands):
    for name in sorted(COMMANDS):
        parser=commands.add_parser(name,help=HELP[name])
        parser.add_argument("--run",required=True)
        parser.add_argument("--lock-timeout",type=float,default=5)
        if name=="merge":
            parser.add_argument("--manifest",type=Path,required=True);parser.add_argument("--acknowledgements",type=Path);parser.add_argument("--search-ledger",type=Path,required=True);parser.add_argument("--imports",type=Path);parser.add_argument("--returns",type=Path,nargs="+",required=True)
        elif name=="plan":
            parser.add_argument("--manifest",type=Path,required=True,help="a ux-research-axes.v1 draft; written to RUN/axes.json only when the whole plan validates");parser.add_argument("--acknowledgements",type=Path,help="a ux-axis-acknowledgements.v1 file; an empty one is created when omitted")
        else:
            parser.add_argument("--bundle",type=Path,required=True)
            if name=="gate":parser.add_argument("--write-bundle",action="store_true")
            else:parser.add_argument("--gate",type=Path,required=True)
        if name=="report-check":parser.add_argument("--report",type=Path,required=True);parser.add_argument("--statements",type=Path,required=True)
        if name in {"export-audience","export-personas"}:parser.add_argument("--audience-id",required=True)
        if name=="export-personas":parser.add_argument("--hypotheses",type=Path,required=True,help="an authored ux-research-persona-hypotheses.v1 file; start from the persona-starter output")


def _persona_files(run,store,bundle,gate):
    """Consumers receive verified snapshot paths, never potentially mixed review mirrors."""
    from .engine import now_of
    from scripts.validate_bundle import validate_bundle
    from ergoqa.snapshot import validate_scenario
    marker=run.path/"persona-export.json"
    if marker.exists() and read_json(marker).get("result")!="pass":
        raise EngineError("failed_export","최근 페르소나 내보내기가 실패했습니다. 입력을 수정해 다시 내보내세요.")
    packet=store.committed("qa-personas.json")
    result=store.committed("persona-export.json")
    metadata=packet.get("persona_export",{})
    if result.get("result")!="pass" or result.get("bundle_id")!=packet["bundle_id"] or metadata.get("source_bundle_id")!=bundle["bundle_id"] or metadata.get("gate_bundle_input_sha256")!=gate["bundle_input_sha256"] or metadata.get("gate_process_input_sha256")!=gate["process_input_sha256"] or metadata.get("mode")!=gate["mode"]:
        raise EngineError("stale_personas","페르소나 패킷이 현재 조사 근거와 일치하지 않습니다. 다시 내보내세요.")
    if validate_bundle(packet,now=now_of(run)):
        raise EngineError("packet_contract","현재 페르소나 패킷의 QA 연결을 검증하지 못했습니다.")
    state=store.state()
    names=result.get("scenario_files",[])
    if not isinstance(names,list) or len(set(names))!=len(names) or set(names)!={name for name in state["outputs"] if scenario_output(name)}:
        raise EngineError("snapshot","생성 시나리오 목록이 현재 저장 기록과 일치하지 않습니다.")
    scenarios={s["id"]:s for s in packet["records"]["scenarios"]}
    for name in names:
        scenario=store.committed(name)
        linked=scenarios.get(scenario.get("scenario_id"))
        if validate_scenario(scenario) or linked is None or scenario.get("motivation_claim_ids")!=linked.get("motivation_claim_ids"):
            raise EngineError("scenario_contract","생성 시나리오가 현재 QA 패킷과 연결되지 않습니다.")
    files=["qa-personas.json","qa-personas.md","persona-export.json",*names]
    for name in files:
        store.committed(name)  # verifies the manifest's bytes and permissions
    return [str(safe_path(run.path/state["outputs"][name]["generation_path"],run.path/".engine")) for name in files]


def _mark_failed_export(store,generation,issue):
    """A failed latest export blocks silent intake; the committed snapshot stays for recovery."""
    try:
        current=store.state()
    except EngineError:
        return
    if current is None or current["generation_id"]!=generation:
        return  # a manifest that already advanced keeps its publication semantics
    try:
        store.failure("persona-export.json",dict(schema_version="ux-persona-export.v1",result="fail",
                                                 exit_code=2,issues=[issue],warnings=[]))
    except (OSError,EngineError):
        pass


def execute(args,run):
    with Store(run.path,args.lock_timeout) as store:
        export_generation=None
        def validate_publish(outputs):
            from .engine import expired_sources, now_of
            from .merge import validate_policy
            validate_policy(run)
            bundle=outputs.get("bundle.json")
            if bundle and expired_sources(bundle,now_of(run)):
                raise EngineError("expired", "Retention deadline passed before manifest commit; purge and rerun.")
        store.validator=validate_publish
        try:
            if args.command=="merge":return merge_command(args,run,store)
            if args.command=="gate":return gate_command(args,run,store)
            if args.command=="plan":
                from .planning import plan_command
                return plan_command(args,run,store)
            if args.command=="persona-starter":
                bundle,gate=fresh(run,store,args.bundle,args.gate)
                from .personas import starter
                doc=starter(bundle,gate,read_json(run.path/"brief.json") if (run.path/"brief.json").exists() else {})
                store.publish("persona-starter",{"persona.hypotheses.starter.json":doc})
                return 0,["persona.hypotheses.starter.json"],[],[]
            if args.command=="export-personas":
                from .engine import now_of
                prior=store.state()
                export_generation=prior["generation_id"] if prior else None
                bundle,gate=fresh(run,store,args.bundle,args.gate)
                from . import personas
                doc=read_json(args.hypotheses)
                out,issues,warnings=personas.export(bundle,gate,read_json(run.path/"brief.json") if (run.path/"brief.json").exists() else {},doc,args.audience_id,now=now_of(run))
                if issues or out is None:
                    result=dict(schema_version="ux-persona-export.v1",result="fail",exit_code=1,issues=issues,warnings=warnings)
                    store.failure("persona-export.json",result)
                    return 1,["persona-export.json"],issues,warnings
                packet,stubs=out["packet"],out["stubs"]
                scenario_files={f"qa-scenarios/{stub['scenario_id']}.json":stub for stub in stubs}
                outputs={"qa-personas.json":packet,"qa-personas.md":personas.scenario_markdown(packet),
                         "persona-export.json":dict(schema_version="ux-persona-export.v1",result="pass",exit_code=0,
                                                    audience_id=args.audience_id,bundle_id=packet["bundle_id"],
                                                    personas=len(packet["records"]["personas"])-len(bundle["records"]["personas"]),
                                                    scenarios=len(stubs),scenario_files=list(scenario_files),issues=[],warnings=warnings),
                         **scenario_files}
                store.publish("export-personas",outputs)
                files=_persona_files(run,store,bundle,gate)
                return 0,files,[],warnings
            bundle,gate=fresh(run,store,args.bundle,args.gate)
            if args.command=="persona-intake":
                return 0,_persona_files(run,store,bundle,gate),[],[]
            if args.command=="report-check":
                from .reports import check
                result=check(read_bytes(args.report).decode("utf-8"),read_json(args.statements),bundle,gate,run.routes)
                store.publish("report-check",{"report_check.json":result})
                return result["exit_code"],["report_check.json"],result["violations"],result["warnings"]
            if args.command=="export-audience":
                from .audiences import make_draft,todo_markdown
                brief=read_json(run.path/"brief.json")
                draft=make_draft(bundle,gate,brief,args.audience_id)
                store.publish("export-audience",{"audience.draft.json":draft,"audience.todo.md":todo_markdown(draft)})
                return 0,["audience.draft.json","audience.todo.md"],[],[]
            from .minimize import minimize
            out,result=minimize(bundle,gate)
            if result["exit_code"]:
                store.failure("minimize.json",result)
                return result["exit_code"],["minimize.json"],result["issues"],result["warnings"]
            store.publish("minimize",{"bundle.min.json":out,"minimize.json":result})
            return 0,["bundle.min.json","minimize.json"],[],result["warnings"]
        except (OSError, UnicodeError, TypeError, KeyError, IndexError, AttributeError, RecursionError) as exc:
            error=EngineError("io_or_integrity", "Required input is missing, malformed or unsafe.")
            if args.command in {"merge", "gate"}:
                store.failure("gate_failed.json", dict(result="fail", exit_code=2, issues=[error.issue]))
            if args.command=="export-personas":
                _mark_failed_export(store,export_generation,error.issue)
            raise error from exc
        except EngineError as exc:
            if args.command=="report-check" and exc.exit_code!=3:
                store.failure("report_check.json",dict(schema_version="ux-report-check.v1",result="fail",exit_code=exc.exit_code,violations=[exc.issue],warnings=[],citations=[],mapping_checks=[],supported_coverage=None,bundle_id=None,gate_input_sha256=None,report_sha256=None,mapping_sha256=None))
            if exc.exit_code!=3 and args.command in {"merge","gate"}:
                store.failure("gate_failed.json",dict(result="fail",exit_code=exc.exit_code,issues=[exc.issue]))
            if exc.exit_code!=3 and args.command=="export-personas":
                _mark_failed_export(store,export_generation,exc.issue)
            raise
