"""Privacy components and retention repair boundaries independent of grading."""
from __future__ import annotations

import re
from urllib.parse import urlsplit
from .canonical import EngineError
from .merge import privacy_scan,problem

PROTECTED=re.compile(r'\b(?:minor|children|child|older adults?|elderly|religio\w*|racial|political|sexual orientation|medical condition|disabil\w*)\b|미성년|아동|고령|노인|질환|장애|종교|정치|성적 지향',re.I)


def privacy_graph(bundle):
    nodes={record['id']:record for group in bundle['records'].values() for record in group}
    parent={key:key for key in nodes}
    def find(key):
        while parent[key]!=key:
            parent[key]=parent[parent[key]];key=parent[key]
        return key
    def union(a,b):
        if a in parent and b in parent:parent[find(b)]=find(a)
    def references(owner,value):
        if isinstance(value,str):
            if value in nodes:union(owner,value)
        elif isinstance(value,list):
            for x in value:references(owner,x)
        elif isinstance(value,dict):
            for x in value.values():references(owner,x)
    identities={}
    for rid,record in nodes.items():
        references(rid,record)
        for key in ('author_key','thread_key'):
            if record.get(key):
                identity=(key,record[key])
                if identity in identities:union(rid,identities[identity])
                identities[identity]=rid
    groups={}
    for rid,record in nodes.items():groups.setdefault(find(rid),[]).append(record)
    issues=[]
    for records in groups.values():
        protected=any(record.get('privacy_class')=='protected_individual' or record.get('flags',{}).get('protected_attribute_cue') or PROTECTED.search(' '.join(str(record.get(k,'')) for k in ('excerpt','summary','statement'))) or any(v.get('join',{}).get('field')=='age_bands' or v.get('join',{}).get('entity_kind')=='condition' for v in record.get('audience_values',[])) for record in records)
        if protected:
            personal=any(record.get('author_key') or record.get('thread_key') or record.get('item_key') or record.get('source_family')=='voice' or (record.get('source_ref') and record.get('privacy_class') not in {'aggregate',None}) for record in records)
            if personal:issues.append(problem('protected_component','privacy','Protected cues are linked to an individual or personal source; remove the entire component and resubmit.'))
        if any(record.get('privacy_class')=='protected_individual' for record in records):issues.append(problem('protected_individual','privacy','Personal protected-attribute content is refused.'))
        for record in records:
            if record.get('privacy_class')=='aggregate' and (record.get('author_key') or record.get('thread_key') or record.get('item_key') or record.get('source_family')=='voice'):
                issues.append(problem('aggregate_identity','privacy','Deidentified aggregates cannot contain person/thread keys or post locators.'))
    return issues
