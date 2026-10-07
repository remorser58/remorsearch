"""Markdown citation/mapping checks; semantic review remains a human decision."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .canonical import EngineError, byte_digest, canonical, digest
from .grading import SUPPORTED
from .merge import problem
from .schema import require

ANNEX=re.compile(r"\b(?:unresolved|unverified|annex|appendix|next evidence needed)\b|미확정|확인 필요|부록",re.I)
TOKEN=re.compile(r"(?i)CLM-[\w-]*")


def markdown(text):
    lines=text.replace("\r\n","\n").splitlines(); headings={};fenced=set();fence=None
    for i,line in enumerate(lines,1):
        match=re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$",line)
        if fence:
            fenced.add(i)
            if match and match[1][0]==fence[0] and len(match[1])>=fence[1] and not match[2].strip():fence=None
            continue
        if match:
            fence=(match[1][0],len(match[1]));fenced.add(i);continue
        atx=re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$",line)
        if atx:
            headings[i]=(len(atx[1]),clean_heading(atx[2]))
        elif i>1 and lines[i-2].strip() and i-1 not in fenced and re.fullmatch(r" {0,3}(?:=+|-+)\s*",line):
            headings[i-1]=(1 if line.strip()[0]=="=" else 2,clean_heading(lines[i-2]))
    if fence:raise EngineError("unclosed_fence","Report has an unclosed fenced block.",1,"report")
    paths={};annex={};stack=[]
    for i in range(1,len(lines)+1):
        if i in headings:
            level,title=headings[i]
            while stack and stack[-1][0]>=level:stack.pop()
            inherited=any(x[2] for x in stack)
            stack.append((level,title,bool(ANNEX.search(title)) or inherited))
        paths[i]=[x[1] for x in stack];annex[i]=bool(stack and stack[-1][2])
    return lines,headings,fenced,paths,annex


def clean_heading(text):
    text=re.sub(r"!?\[([^]]*)\]\([^)]*\)",r"\1",text)
    return unicodedata.normalize("NFC",text.strip(" *_`~#")).casefold()


def decision_section(text):
    lines,headings,fenced,paths,annex=markdown(text)
    ordered=sorted(headings)
    if not ordered or headings[ordered[0]][0]!=1:raise EngineError("decision_order","Report requires a title followed by the decision section.",1,"report")
    if len(ordered)<2 or headings[ordered[1]] not in {(2,"decision"),(2,"결론")}:
        raise EngineError("decision_order","First section after the title must be ## Decision or ## 결론.",1,"report")
    start=ordered[1];end=next((i for i in ordered[2:] if headings[i][0]<=2),len(lines)+1)
    return "\n".join(lines[start:end-1]),(start+1,end-1)


def community_hosts(routes):
    hosts=set()
    for item in routes.get("platforms",[]):
        channel=item.get("channel") or item.get("family") or item.get("channel_family") or item.get("platform_family")
        if channel in {"community","blog","commerce_reviews","app_store_reviews","microblog","qna","video","social","reviews","review"}:
            hosts.update(str(x).lower().rstrip(".").removeprefix("*.") for x in item.get("hosts",[]))
    return hosts


def check(text,mapping,bundle,gate,routes):
    require(mapping,"ux-report-claims.v1.schema.json")
    text=text.replace("\r\n","\n");lines,headings,fenced,paths,annex=markdown(text)
    section,(start,end)=decision_section(text)
    report_sha=byte_digest(text.encode())
    if mapping["report_sha256"]!=report_sha:raise EngineError("stale_mapping","Report statement mapping belongs to different bytes.",1,"statements")
    rows={r["claim_id"]:r for r in gate["claims"]};claims={c["id"]:c for c in bundle["records"]["claims"]}
    citations=[];violations=[];warnings=[];seen=set()
    for i,line in enumerate(lines,1):
        if i in fenced:continue
        for candidate in {m.group() for variant in (line,unquote(line)) for m in TOKEN.finditer(variant)}:
            if candidate not in rows:
                code="invalid_claim_id" if not re.fullmatch(r"CLM-[0-9a-f]{8}",candidate) else "phantom_claim_id"
                raise EngineError(code,"Report cites an unknown or malformed research claim ID.",2,"report:"+str(i))
            key=(i,candidate)
            if key in seen:continue
            seen.add(key);row=rows[candidate]
            citations.append(dict(id=candidate,line=i,heading_path=paths[i],annex=annex[i],status=row["status"]))
            if row["status"] not in SUPPORTED and not annex[i]:violations.append(problem("unsupported_body","report:"+str(i),"Unsupported claims must be cited inside an annex."))
        # Check all body URLs, including definitions, HTML and encoded destinations.
        for url in re.findall(r"https?://[^\s<>\"'`]+",unquote(line),re.I):
            host=urlsplit(url.rstrip(").,;")).hostname or ""
            if any(host==h or host.endswith("."+h) for h in community_hosts(routes)):
                violations.append(problem("community_url","report:"+str(i),"Shared community, review and social evidence uses channel, date and source ID."))
    mapped_lines=set();checks=[]
    for statement in mapping["statements"]:
        a,b=statement["line_start"],statement["line_end"]
        span=set(range(a,b+1))
        if a>b or b>len(lines) or span&fenced or span&mapped_lines or not "\n".join(lines[a-1:b]).strip():
            violations.append(problem("statement_span","statements","Statement spans must be nonblank, disjoint, unfenced and within the report."));continue
        mapped_lines|=span;raw="\n".join(lines[a-1:b]);visible={c["id"] for c in citations if a<=c["line"]<=b}
        if byte_digest(raw.encode())!=statement["text_sha256"]:violations.append(problem("statement_hash","statements","Statement span hash does not match report bytes."))
        if set(statement["claim_ids"])-rows.keys():raise EngineError("phantom_claim_id","Mapping references unknown claim IDs.",2,"statements")
        if set(statement["claim_ids"])-visible:violations.append(problem("statement_citation","statements","Mapped claims must be visibly cited in their span."))
        if statement["kind"]=="empirical" and not statement["claim_ids"]:violations.append(problem("empirical_mapping","statements","An empirical span needs nonempty known claim citations."))
        if statement["kind"]!="empirical" and not any(annex[i] for i in span) and not re.match(r"\s*(?:hypothesis|recommendation|가설|권고):",raw,re.I):violations.append(problem("statement_label","statements","Uncited hypotheses and recommendations need an explicit label."))
        if statement["reviewed_by"] is None or statement["review_note"] is None:warnings.append(problem("review_pending","statements","Semantic review is pending."))
        checks.append(dict(id=statement["id"],line_start=a,line_end=b))
    # Research decision: findings before steps, at most three of each, plus coverage.
    decision_ids=sorted({c["id"] for c in citations if start<=c["line"]<=end})
    next_steps=[x for x in lines[start-1:end] if re.match(r"\s*(?:[-*+]\s+)?(?:next step|recommendation|다음 단계|권고)\s*:",x,re.I)]
    finding_lines={c["line"] for c in citations if start<=c["line"]<=end}
    next_heading=None
    for line_number in sorted(headings):
        if start<=line_number<=end and re.search(r"^(?:next steps|다음 단계)$",headings[line_number][1],re.I):
            next_heading=line_number
    if next_heading is not None:
        next_steps=[x for x in lines[next_heading:end] if re.match(r"\s*(?:[-*+]\s+|[0-9]+[.)]\s+)",x)]
    if len(finding_lines)>3 or len(decision_ids)>3 or len(next_steps)>3:violations.append(problem("decision_limit","report","Decision holds at most three findings and three next steps."))
    if next_steps:
        first=next(i for i in range(start,end+1) if re.match(r"\s*(?:[-*+]\s+)?(?:next step|recommendation|다음 단계|권고)\s*:",lines[i-1],re.I))
        if any(start<=c["line"]<=end and c["line"]>first for c in citations):violations.append(problem("decision_order","report","Findings precede next steps in the decision section."))
    if not re.search(r"(?:coverage|범위)\s*:",section,re.I):violations.append(problem("decision_coverage","report","Decision requires one line of pages, main stops and unseen coverage."))
    for identifier in sorted({c["id"] for c in citations if not c["annex"]}):
        row=rows[identifier];claim=claims[identifier]
        if row["counter_search_required"]:
            cs=claim.get("counter_search")
            expected="Counter: "+cs["outcome"]+" - "+cs["summary"] if cs else None
            relevant=[c["line"] for c in citations if c["id"]==identifier and not c["annex"]]
            spans=[]
            for line_number in relevant:
                following=next((c["line"] for c in citations if c["line"]>line_number),len(lines)+1)
                spans.append("\n".join(lines[line_number-1:following-1]))
            if expected is None or any(expected not in span for span in spans):violations.append(problem("counter_line","report","Priority findings require a Counter line matching the gate's outcome and summary."))
        if identifier in decision_ids and row["status"] not in section:violations.append(problem("finding_status","report","Decision findings must state their gate status."))
    supported={k for k,v in rows.items() if v["status"] in SUPPORTED};cited={c["id"] for c in citations if c["status"] in SUPPORTED}
    coverage=len(cited)/len(supported) if supported else None
    if coverage is not None and coverage<0.5:warnings.append(problem("supported_coverage","report","Less than half of supported claims are cited."))
    return dict(schema_version="ux-report-check.v1",result="fail" if violations else "pass",exit_code=1 if violations else 0,report_sha256=report_sha,mapping_sha256=digest(mapping),bundle_id=bundle["bundle_id"],gate_input_sha256=digest(gate),citations=sorted(citations,key=lambda x:(x["line"],x["id"])),violations=violations,warnings=warnings,mapping_checks=checks,supported_coverage=coverage)
