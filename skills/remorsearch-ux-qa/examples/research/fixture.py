"""Invented native team input for offline engine acceptance; never real research."""
from __future__ import annotations
import copy,json,time
from pathlib import Path
import sys
SKILL=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SKILL))
from uxresearch import ledger
from uxresearch.canonical import byte_digest,canonical
from uxresearch.flags import empty
from uxresearch.merge import import_identity
from uxresearch.storage import atomic,safe_path


def write(path,value):
    atomic(path,value if isinstance(value,bytes) else value.encode() if isinstance(value,str) else canonical(value))


def build(root,*,clock=time.time):
    root=safe_path(root)
    day=time.strftime('%Y-%m-%d',time.gmtime(clock()))
    brief=dict(schema_version='ux-research-brief.v1',product=dict(name='Example checkout',surface='web',url='https://product.example',locale='en',category='commerce',release_date='2026-09-01',current_version='1'),audience_questions=['segments'],budgets=dict(per_run=200,per_host=30,search_queries=12))
    routes=json.loads((SKILL/'uxresearch/data/routes.json').read_text())
    ledger.create(root,ledger.build_policy(brief,{}),brief=brief,routes=routes,routes_source='packaged',clock=clock)
    run=ledger.Run(root,clock=clock);rid=run.meta['run_id'];stamp=run.now_iso()
    text='Illustrative measurement: business operators completed order lookup. A neutral product sample included 20 users. This invented fixture is for offline validation.'
    write(root/'sample.txt',text)
    imp=dict(import_id='',artifact_ref='sample.txt',content_sha256=byte_digest(text.encode()),source_type='product_analytics',producer_org='example-team',producer_stake='independent',acquisition=dict(kind='analytics_export',product=brief['product']['name'],app_id=None,territory=None,exported_at=stamp,period_start='2026-09-01',period_end=day,permission_ref='owner-approved-diagnostic'),sanitization=dict(performed_by='producer',method='producer_redaction',reviewed_at=stamp,removed_categories=['names','identifiers','individual_rows'],review_attestation=True),retention_until=None)
    imp['import_id']=import_identity(imp)
    manifest=dict(schema_version='ux-research-axes.v1',run_id=rid,axes=[dict(axis_id='product',audience_questions=['segments'],excluded=False,reason=None,assignments=[dict(assignment_id='discovery-1',reader_id='reader-1',round=0,purpose='discovery')])],segments=[dict(segment_id='operators',priority='secondary',decision_ref='owner-diagnostic',summary='An illustrative secondary segment.')],question_gaps=[])
    call=dict(call_id='Q-0000000000000001',tool='offline-fixture',called_at=stamp,phase='discovery',queries=[dict(q='diagnostic operator lookup',lang='en')],results_n=1,outcome='completed',assignment_id='discovery-1')
    sc=dict(product_relation='product_users',population='business operators',period_start='2026-09-01',period_end=day,version='1',segment_id='operators',context_id=None)
    source=dict(local_id='source',title='Illustrative team analytics',url=None,item_key=None,source_type='product_analytics',source_family='measured',producer_stake='independent',platform_family='product_analytics',org='example-team',author_key=None,thread_key=None,published_at=day,observed_at=stamp,valid_at=day,version='1',access_method='team_export',access_basis='team_provided',public_scope='deidentified_aggregate',retention_status='retained',retention_until=None,privacy_class='aggregate',promo_check='text_only',flags=empty(),provenance=dict(kind='import',import_id=imp['import_id'],content_sha256=imp['content_sha256']),access=None)
    excerpt=dict(local_id='excerpt',source_local_id='source',capture_ref=imp['import_id'],excerpt='business operators completed order lookup.',summary='The diagnostic sample records successful task execution by this segment.',evidence_type='quantitative',epistemic_status='observed',flags=empty(),scope=sc,cues=dict(segment='operators',context=None,task='lookup',condition=None,device=None),denominator=None)
    claim=dict(local_id='claim',claim_kind='segment_exists',statement='Business operators use order lookup in this diagnostic sample.',excerpt_ids=['excerpt'],counter_excerpt_ids=[],context_excerpt_ids=[],observation_ids=[],subject=dict(segment_id='operators',task_id=None,condition_id=None,context_id=None,pain_point_id=None),scope=sc,about_current_version=False,stakes='normal',scenario_priorities=[],audience_values=[dict(join=dict(segment_id='operators',entity_kind='segment',entity_id='operators',field='name_ko'),value='Business operators',denominator_evidence_ids=[],value_checks=[])],counter_search=None)
    returned=dict(schema_version='ux-reader-return.v1',run_id=rid,return_id='return-1',axis=dict(axis_id='product',assignment_id='discovery-1',reader_id='reader-1',round=0,part_index=1,part_count=1,completion='complete',audience_questions=['segments']),queries_run=[call],search_count=1,sources=[source],excerpts=[excerpt],candidate_claims=[claim],expand_leads=[],dead_ends=[],tail_reason='The single diagnostic input is exhausted.',gaps=[dict(stop_class='limited_fixture',url=None,note='Only invented native team data was examined.')],budget_used=dict(searches=1,document_requests=0,policy_requests=0,request_fetch_ids=[]))
    (root/'returns').mkdir(mode=0o700)
    for name,value in [('axes.json',manifest),('sanitized-imports.json',dict(schema_version='ux-sanitized-imports.v1',run_id=rid,imports=[imp])),('returns/editors.json',returned)]:write(root/name,value)
    write(root/'search-ledger.jsonl',canonical(call)+b'\n')
    return root
