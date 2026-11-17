import hashlib, json
from app.config import RULE_VERSION
from app.domain import blend, TARGETS
from app.numeric import number
from app.errors import DomainError
from app.modules.m8_retest import store, rules
def identify(text):
    digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
    return hashlib.sha256((RULE_VERSION+':'+digest).encode('utf-8')).hexdigest()[:16],digest
def ingest(text,limit=None):
    if not isinstance(text,str): raise DomainError('TYPE','CSV必须是文本')
    job_id,digest=identify(text)
    job=store.get_job(job_id)
    if job and job['status']=='done': return summary(job,True)
    if job is None:
        rows,bad=rules.parse(text)
        store.create_job(job_id,digest,store.next_version(),rows)
        store.record_structural(job_id,bad)
    return process(job_id,limit)
def process(job_id,limit=None):
    job=store.get_job(job_id)
    if job is None: raise DomainError('NOT_FOUND','复测任务不存在',404)
    rows=json.loads(job['rows_json']);step=0
    while job['status']!='done' and (limit is None or step<limit):
        seq=job['processed'];raw=rows[seq]
        try: n=rules.normalize(raw)
        except DomainError as e: store.apply_error(job_id,seq,raw,e.code,e.message)
        else: store.apply_row(job_id,seq,raw,n)
        step+=1;job=store.get_job(job_id)
    return summary(job,False)
def summary(job,reused):
    counts=store.event_counts(job['job_id']);structural=counts.get('structural',0)
    invalid=counts.get('invalid',0)-structural
    return {'job_id':job['job_id'],'version':job['version'],'status':job['status'],'total':job['total'],'processed':job['processed'],
    'applied':counts.get('applied',0),'duplicate':counts.get('duplicate',0),'stale':counts.get('stale',0),
    'conflict':counts.get('conflict',0),'invalid':invalid,'structural':structural,'reused':reused}
def composition(rows):
    return [{'炉次':r['batch'],'批号':r['lot'],'元素':r['element'],'干重_kg':r['dry_mass'],'含量下界_pct':r['low'],'含量上界_pct':r['high'],'修订号':r['revision'],'更新时间':r['updated_at']} for r in rows]
def acceptance(mixture):
    rows=[]
    for r in mixture:
        lo,hi=TARGETS[r['元素']];a=number(r['含量下界_pct']);b=number(r['含量上界_pct'])
        status='通过' if lo<=a<=b<=hi else '不合格' if b<lo or a>hi else '待补测'
        rows.append({'炉次':r['炉次'],'元素':r['元素'],'含量下界_pct':r['含量下界_pct'],'含量上界_pct':r['含量上界_pct'],'下限_pct':str(lo),'上限_pct':str(hi),'验收':status})
    return rows
def reblend(rows):
    answer=[]
    for batch in sorted({r['batch'] for r in rows}):
        group=[r for r in rows if r['batch']==batch];lots=sorted({r['lot'] for r in group})
        for lot in lots:
            trial=blend([r for r in group if r['lot']!=lot])
            passing=sum(TARGETS[r['元素']][0]<=number(r['含量下界_pct'])<=number(r['含量上界_pct'])<=TARGETS[r['元素']][1] for r in trial)
            answer.append({'炉次':batch,'移除批号':lot,'剩余批次':len(lots)-1,'通过元素':passing,'复配结果':'可验收' if passing==len(TARGETS) else '需复测'})
    return answer
def build_payload(batch,rows):
    feed=[{'lot':r['lot'],'batch':r['batch'],'element':r['element'],'dry_mass':r['dry_mass'],'low':r['low'],'high':r['high']} for r in rows]
    mixture=[{'炉次':batch,**row} for row in blend(feed)]
    revision_set={r['lot']+'|'+r['element']:r['revision'] for r in rows}
    return {'炉次':batch,'成分':composition(rows),'混配':mixture,'验收':acceptance(mixture),'复配':reblend(rows),'修订集合':revision_set,'规则版本':RULE_VERSION}
def signoff(batch):
    if not batch: raise DomainError('MISSING','炉次不能为空')
    rows=store.current_rows(batch)
    if not rows: raise DomainError('EMPTY','该炉次没有有效成分，不能签核')
    payload=build_payload(batch,rows)
    content=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    latest=store.latest_signoff(batch)
    if latest and latest['content_hash']==content:
        return {'signoff_id':latest['id'],'seq':latest['seq'],'signed_at':latest['signed_at'],'reused':True}
    return {**store.create_signoff(batch,payload,content),'reused':False}
def view(batch,view_name,signoff_id=None):
    if view_name not in ('current','signed'): raise DomainError('VIEW','视图参数无效')
    if not batch: raise DomainError('MISSING','炉次不能为空')
    if view_name=='current':
        rows=store.current_rows(batch)
        if not rows: raise DomainError('NOT_FOUND','炉次不存在或没有有效成分',404)
        payload=build_payload(batch,rows)
        binding='current:'+hashlib.sha256(json.dumps(payload['修订集合'],sort_keys=True).encode('utf-8')).hexdigest()[:12]
        return {'视图':'current','绑定':binding,'签核单':None,'签核时间':None,**payload}
    so=store.get_signoff(signoff_id) if signoff_id else store.latest_signoff(batch)
    if so is None or so['batch']!=batch: raise DomainError('NOT_FOUND','该炉次没有已签核验收单',404)
    return {'视图':'signed','绑定':'signoff:'+str(so['id']),'签核单':so['id'],'签核时间':so['signed_at'],**json.loads(so['payload'])}
def export(batch,view_name,signoff_id=None):
    import csv, io
    data=view(batch,view_name,signoff_id)
    rows=[]
    for stage in ('成分','混配','验收','复配'): rows.extend({'阶段':stage,**r} for r in data[stage])
    fields=list(dict.fromkeys(['视图','绑定','签核单','签核时间','规则版本','阶段']+[k for r in rows for k in r]))
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
    for row in rows: writer.writerow({'视图':data['视图'],'绑定':data['绑定'],'签核单':data['签核单'] or '','签核时间':data['签核时间'] or '','规则版本':data['规则版本'],**row})
    name='retest-'+view_name+'-'+batch+('-'+str(data['签核单']) if data['签核单'] else '')+'.csv'
    return name,'﻿'+out.getvalue()
def fmt_value(text):
    if not text: return '—'
    try: d=json.loads(text)
    except ValueError: return text
    if 'low' in d: return '含量 '+str(d['low'])+'~'+str(d['high'])+'% · r'+str(d['revision'])
    return d.get('assay',text)
def issues():
    rows=[]
    for q in store.quarantine():
        rows.append({'类型':'隔离','炉次':q['batch'] or '—','批号':q['lot'] or '—','元素':q['element'] or '—','修订':q['revision'] or '—','原因码':q['code'],'原因':q['reason'],'当前值':fmt_value(q['current_value']),'到达值':fmt_value(q['incoming_value'])})
    for e in store.stale_events():
        current='含量 '+str(e['cur_low'])+'~'+str(e['cur_high'])+'% · r'+str(e['cur_revision']) if e['cur_low'] is not None else '—'
        incoming=fmt_value(e['raw'])
        rows.append({'类型':'晚到','炉次':e['batch'],'批号':e['lot'],'元素':e['element'],'修订':e['revision'],'原因码':'STALE','原因':'晚到旧值：修订号低于当前，不覆盖','当前值':current,'到达值':incoming})
    return rows
def dashboard(batch=None,view_name='current',signoff_id=None):
    batches=store.batches()
    batch=batch if batch else (batches[0] if batches else None)
    data=None
    if batch:
        try: data=view(batch,view_name,signoff_id)
        except DomainError as e:
            if e.status==404: data=None
            else: raise
    return {'stats':store.stats(),'jobs':store.jobs(),'batches':batches,'batch':batch,'view':view_name,'signoff':signoff_id,'data':data,'signoffs':store.signoffs_for(batch) if batch else [],'issues':issues()}
