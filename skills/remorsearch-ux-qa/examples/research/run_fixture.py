#!/usr/bin/env python3
"""Exercise the entire research command path with invented input and no network."""
from __future__ import annotations
import argparse,contextlib,io,json,sys,tempfile
from pathlib import Path
from fixture import build,write,SKILL
sys.path.insert(0,str(SKILL))
from uxresearch.cli import main
from uxresearch.canonical import digest,byte_digest
from uxresearch.ledger import Run
from ergoqa.cli import main as audience_main


def run_fixture(root):
    root=build(root)
    def command(name,*extra):
        args=[name,'--run',str(root)]
        if name!='merge':args+=['--bundle',str(root/'bundle.json')]
        if name in {'report-check','export-audience','minimize'}:args+=['--gate',str(root/'gate.json')]
        with contextlib.redirect_stdout(io.StringIO()) as output:code=main(args+list(extra))
        result=json.loads(output.getvalue());print(json.dumps(result,sort_keys=True))
        if code:raise RuntimeError('Diagnostic command failed: '+name)
    command('merge','--manifest',str(root/'axes.json'),'--search-ledger',str(root/'search-ledger.jsonl'),'--imports',str(root/'sanitized-imports.json'),'--returns',str(root/'returns/editors.json'))
    bundle=json.loads((root/'bundle.json').read_text());stamp=Run(root).now_iso()
    for src in bundle['records']['sources']:src['summary']='An invented diagnostic aggregate supplied by the example team.'
    for group,records in bundle['records'].items():
        for record in records:
            for field in ('summary','statement','result','actual','expected','task','title'):
                if field in record and (group!='sources' or field=='summary'):bundle['research']['summary_attestations'].append(dict(record_id=record['id'],field=field,content_sha256=digest(record[field]),reviewed_by='self-diagnostic',reviewed_at=stamp))
    write(root/'bundle.json',bundle)
    command('gate','--write-bundle')
    gate=json.loads((root/'gate.json').read_text());cid=bundle['records']['claims'][0]['id'];sid=bundle['records']['sources'][0]['id']
    text=f'# Diagnostic research\n\n## Decision\n\n- {cid} supported_high: Business operators use order lookup. “business operators completed order lookup.” — {sid}, September 2026.\n\nNext step: Test order lookup; completed product observations would strengthen the task model.\nCoverage: zero pages; no reader stops; only invented team data examined.\n\n## Method\n\nThis is an invented offline fixture.\n'
    write(root/'report.md',text);lines=text.splitlines()
    write(root/'report-claims.json',dict(schema_version='ux-report-claims.v1',report_sha256=byte_digest(text.encode()),statements=[dict(id='statement-1',line_start=5,line_end=5,text_sha256=byte_digest(lines[4].encode()),kind='empirical',claim_ids=[cid],reviewed_by='self-diagnostic',review_note='Invented example checked for joins.')]))
    command('report-check','--report',str(root/'report.md'),'--statements',str(root/'report-claims.json'))
    command('export-audience','--audience-id','AU-example')
    code=audience_main(['audience-check',str(root/'audience.draft.json'),'--draft','--run',str(root),'--bundle',str(root/'bundle.json'),'--gate',str(root/'gate.json')])
    if code:raise RuntimeError('Draft check failed')
    command('minimize')
    print(json.dumps(dict(passed=True,network_requests=0,invented_content=True)))
    return root


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path);args=parser.parse_args()
    if args.out:run_fixture(args.out)
    else:
        with tempfile.TemporaryDirectory(prefix='research-diagnostic-') as root:run_fixture(Path(root)/'run')
