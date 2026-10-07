"""Pinned local research schemas, with no network reference resolution."""
from __future__ import annotations

import re
import math
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .canonical import EngineError, byte_digest, canonical, loads, timestamp

ROOT=Path(__file__).resolve().parents[1]/'schemas'
PINS=Path(__file__).resolve().parent/'data'/'research-schema-pins.json'
KEYWORDS={'$schema','$id','$defs','$ref','title','description','$comment','default','examples','type','enum','const','properties','required','additionalProperties','propertyNames','items','uniqueItems','minItems','maxItems','minLength','maxLength','pattern','format','minimum','maximum','exclusiveMinimum','exclusiveMaximum','minProperties','maxProperties','allOf','anyOf','oneOf','not','if','then','else'}
class Resolver:
    def __init__(self):
        self.docs={};self.ids={}
        for name,sha in loads(PINS.read_bytes()).items():
            path=ROOT/name
            if path.name!=name or path.is_symlink() or byte_digest(path.read_bytes())!=sha:raise EngineError('schema_pin','Packaged schema does not match its local pin.')
            doc=loads(path.read_bytes());self.docs[name]=doc;self.ids[doc['$id']]=name;self.check_schema(doc)
    def check_schema(self,schema):
        if type(schema) is bool:return
        if not isinstance(schema,dict) or set(schema)-KEYWORDS:raise EngineError('schema_keyword','Schema has unsupported keywords.')
        for k in ('properties','$defs'):
            for s in schema.get(k,{}).values():self.check_schema(s)
        for k in ('items','additionalProperties','propertyNames','not','if','then','else'):
            if k in schema:self.check_schema(schema[k])
        for k in ('allOf','anyOf','oneOf'):
            for s in schema.get(k,[]):self.check_schema(s)
    def ref(self,ref,current):
        name,_,ptr=ref.partition('#')
        if name:
            current=self.ids.get(name,name)
            if current not in self.docs:raise EngineError('schema_reference','Only pinned local references are allowed.')
        node=self.docs[current]
        if ptr:
            if not ptr.startswith('/'):raise EngineError('schema_reference','Schema fragment must be a JSON Pointer.')
            try:
                for part in ptr[1:].split('/'):node=node[part.replace('~1','/').replace('~0','~')]
            except (KeyError,TypeError):raise EngineError('schema_reference','Schema reference is missing.') from None
        return node,current
    def validate(self,value,name,definition=None):
        canonical(value)  # also reject non-JSON values when called directly
        return self.walk(value,self.docs[name]['$defs'][definition] if definition else self.docs[name],name,'$',0)
    def walk(self,value,schema,current,path,depth):
        if depth>128:return [path+': nesting limit']
        if type(value) is float and not math.isfinite(value):return [path+': nonfinite number']
        if schema is True:return []
        if schema is False:return [path+': forbidden value']
        errors=[]
        def sub(s,v=value,p=path,c=current):return self.walk(v,s,c,p,depth+1)
        if '$ref' in schema:
            s,c=self.ref(schema['$ref'],current);errors+=sub(s,c=c)
        types=schema.get('type')
        if types:
            types=types if isinstance(types,list) else [types]
            kinds={'null':value is None,'boolean':type(value) is bool,'integer':type(value) is int or type(value) is float and value.is_integer(),'number':type(value) in (int,float),'string':isinstance(value,str),'object':isinstance(value,dict),'array':isinstance(value,list)}
            if not any(kinds.get(t,False) for t in types):return errors+[path+': wrong type']
        if 'const' in schema and canonical(value)!=canonical(schema['const']):errors.append(path+': unexpected constant')
        if 'enum' in schema and not any(canonical(value)==canonical(x) for x in schema['enum']):errors.append(path+': invalid enum')
        for s in schema.get('allOf',[]):errors+=sub(s)
        for k in ('anyOf','oneOf'):
            if k in schema:
                n=sum(not sub(s) for s in schema[k])
                if k=='anyOf' and n==0 or k=='oneOf' and n!=1:errors.append(path+': '+k+' does not match')
        if 'not' in schema and not sub(schema['not']):errors.append(path+': prohibited shape')
        if 'if' in schema:
            k='then' if not sub(schema['if']) else 'else'
            if k in schema:errors+=sub(schema[k])
        if isinstance(value,dict):
            for k in schema.get('required',[]):
                if k not in value:errors.append(path+': missing '+k)
            props=schema.get('properties',{})
            for k,v in value.items():
                if k in props:errors+=sub(props[k],v,path+'.'+k)
                elif 'additionalProperties' in schema:errors+=sub(schema['additionalProperties'],v,path+'.<key>')
                if 'propertyNames' in schema:errors+=sub(schema['propertyNames'],k,path+'.<key>')
            if len(value)<schema.get('minProperties',0) or len(value)>schema.get('maxProperties',float('inf')):errors.append(path+': property count')
        if isinstance(value,list):
            if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',float('inf')):errors.append(path+': item count')
            if schema.get('uniqueItems') and len({canonical(x) for x in value})!=len(value):errors.append(path+': duplicate item')
            if 'items' in schema:
                for i,v in enumerate(value):errors+=sub(schema['items'],v,path+'['+str(i)+']')
        if isinstance(value,str):
            if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',float('inf')):errors.append(path+': string length')
            if 'pattern' in schema and re.search(schema['pattern'],value) is None:errors.append(path+': pattern')
            try:
                if schema.get('format')=='date':date.fromisoformat(value)
                elif schema.get('format')=='date-time':timestamp(value)
                elif schema.get('format')=='uri' and (not urlsplit(value).scheme or any(c.isspace() for c in value)):raise ValueError()
            except (ValueError,TypeError):errors.append(path+': invalid format')
        if type(value) in (int,float):
            if value<schema.get('minimum',float('-inf')) or value>schema.get('maximum',float('inf')) or 'exclusiveMinimum' in schema and value<=schema['exclusiveMinimum'] or 'exclusiveMaximum' in schema and value>=schema['exclusiveMaximum']:errors.append(path+': numeric bounds')
        return errors

def require(value,name,definition=None):
    errors=Resolver().validate(value,name,definition)
    if errors:raise EngineError('schema','Input fails its pinned schema.',location=errors[0])
