import csv, io, json, pytest
BASE='lot,batch,mass,unit,moisture,element,assay,basis,revision\n'
def make_csv(*rows): return BASE+'\n'.join(rows)+'\n'
V1=make_csv('00001,F-1,100,kg,2,Cu,9,dry,1','00001,F-1,100,kg,2,Zn,5,dry,1','00002,F-1,100,kg,2,Cu,10,dry,1')
def upload(client,text,**kw): return client.post('/api/retest',json={'csv':text,**kw})
def current(client,batch='F-1'): return client.get('/api/retest/view?batch='+batch+'&view=current')
def assay_row(client,lot,element,batch='F-1'):
    data=current(client,batch).get_json()
    return next(r for r in data['成分'] if r['批号']==lot and r['元素']==element)
def test_first_upload_registers_current(client):
    result=upload(client,V1).get_json()
    assert result['status']=='done' and result['applied']==3 and result['total']==3 and result['version']==1
    assert result['applied']+result['duplicate']+result['stale']+result['conflict']+result['invalid']==result['total']
    data=current(client).get_json()
    assert len(data['成分'])==3 and all(r['修订号']==1 for r in data['成分'])
def test_newer_revision_updates_current(client):
    upload(client,V1)
    result=upload(client,make_csv('00001,F-1,100,kg,2,Cu,10,dry,2')).get_json()
    assert result['applied']==1
    row=assay_row(client,'00001','Cu')
    assert row['修订号']==2 and row['含量上界_pct']=='10'
def test_late_record_does_not_overwrite(client):
    upload(client,V1);upload(client,make_csv('00001,F-1,100,kg,2,Cu,10,dry,2'))
    result=upload(client,make_csv('00001,F-1,100,kg,2,Cu,8,dry,1')).get_json()
    assert result['stale']==1 and result['applied']==0
    row=assay_row(client,'00001','Cu')
    assert row['修订号']==2 and row['含量上界_pct']=='10'
def test_same_revision_conflict_quarantined(client):
    upload(client,V1)
    result=upload(client,make_csv('00001,F-1,100,kg,2,Cu,11,dry,1')).get_json()
    assert result['conflict']==1
    assert assay_row(client,'00001','Cu')['含量上界_pct']=='9'
    from app.modules.m8_retest import service
    issue=next(i for i in service.dashboard()['issues'] if i['原因码']=='SAME_REVISION')
    assert issue['类型']=='隔离' and 'r1' in issue['当前值'] and issue['到达值']!='—'
def test_same_revision_same_value_is_duplicate(client):
    upload(client,V1)
    result=upload(client,make_csv('00001,F-1,100,kg,2,Cu,9,dry,1')).get_json()
    assert result['duplicate']==1 and assay_row(client,'00001','Cu')['含量上界_pct']=='9'
def test_rerun_creates_no_new_version(client):
    first=upload(client,V1).get_json();again=upload(client,V1).get_json()
    assert again['reused'] is True and again['version']==first['version']==1
    assert len(client.get('/api/retest/jobs').get_json())==1
def test_chunked_processing_then_resume(client):
    result=upload(client,V1,limit=2).get_json()
    assert result['status']=='running' and result['processed']==2
    done=client.post('/api/retest/resume',json={'job_id':result['job_id']}).get_json()
    assert done['status']=='done' and done['processed']==3 and done['applied']==3
    assert len(current(client).get_json()['成分'])==3
def test_crash_mid_job_recovers(client,monkeypatch):
    from app.modules.m8_retest import rules, service
    original=rules.normalize;calls={'n':0}
    def boom(row):
        calls['n']+=1
        if calls['n']==2: raise RuntimeError('模拟中断')
        return original(row)
    monkeypatch.setattr(rules,'normalize',boom)
    with pytest.raises(RuntimeError): service.ingest(V1)
    monkeypatch.setattr(rules,'normalize',original)
    job=service.store.jobs()[0]
    assert job['status']=='running' and job['processed']==1
    result=service.process(job['job_id'])
    assert result['status']=='done' and result['applied']==3
def test_signoff_freezes_snapshot(client):
    upload(client,V1)
    signed=client.post('/api/retest/signoff',json={'batch':'F-1'}).get_json()
    upload(client,make_csv('00001,F-1,100,kg,2,Cu,10,dry,2'))
    frozen=client.get('/api/retest/view?batch=F-1&view=signed').get_json()
    row=next(r for r in frozen['成分'] if r['批号']=='00001' and r['元素']=='Cu')
    assert row['修订号']==1 and row['含量上界_pct']=='9' and frozen['签核单']==signed['signoff_id']
    assert assay_row(client,'00001','Cu')['修订号']==2
def test_signoff_idempotent_when_unchanged(client):
    upload(client,V1)
    first=client.post('/api/retest/signoff',json={'batch':'F-1'}).get_json()
    again=client.post('/api/retest/signoff',json={'batch':'F-1'}).get_json()
    assert again['reused'] is True and again['signoff_id']==first['signoff_id']
    upload(client,make_csv('00001,F-1,100,kg,2,Cu,10,dry,2'))
    newer=client.post('/api/retest/signoff',json={'batch':'F-1'}).get_json()
    assert newer['reused'] is False and newer['seq']==2 and newer['signoff_id']!=first['signoff_id']
def export_rows(client,query):
    text=client.get('/api/retest/export.csv?'+query).data.decode('utf-8-sig')
    return text,list(csv.DictReader(io.StringIO(text)))
def test_export_binds_respective_revisions(client):
    upload(client,V1)
    signed=client.post('/api/retest/signoff',json={'batch':'F-1'}).get_json()
    upload(client,make_csv('00001,F-1,100,kg,2,Cu,10,dry,2'))
    current_text,current_rows=export_rows(client,'batch=F-1&view=current')
    signed_text,signed_rows=export_rows(client,'batch=F-1&view=signed')
    assert 'current:' in current_text and 'signoff:'+str(signed['signoff_id']) in signed_text
    pick=lambda rows: next(r for r in rows if r['阶段']=='成分' and r['批号']=='00001' and r['元素']=='Cu')
    assert pick(current_rows)['修订号']=='2' and pick(signed_rows)['修订号']=='1'
    assert all(r['绑定'].startswith('current:') for r in current_rows)
    assert all(r['绑定']=='signoff:'+str(signed['signoff_id']) for r in signed_rows)
def test_new_batch_uses_new_assays(client):
    upload(client,V1)
    upload(client,make_csv('00009,F-2,100,kg,2,Cu,12,dry,1'))
    assert current(client,'F-2').status_code==200
    assert assay_row(client,'00009','Cu','F-2')['含量上界_pct']=='12'
def test_page_renders(client):
    assert client.get('/retest').status_code==200
    upload(client,V1)
    assert client.get('/retest?batch=F-1&view=current').status_code==200
    client.post('/api/retest/signoff',json={'batch':'F-1'})
    assert client.get('/retest?batch=F-1&view=signed').status_code==200
def test_view_param_invalid(client):
    upload(client,V1)
    assert client.get('/api/retest/view?batch=F-1&view=abc').status_code==422
def test_unknown_batch_is_404(client):
    assert client.get('/api/retest/view?batch=NOPE').status_code==404
    assert client.get('/api/retest/export.csv?batch=NOPE').status_code==404
def test_signoff_empty_batch_422(client):
    assert client.post('/api/retest/signoff',json={'batch':'NOPE'}).status_code==422
def test_resume_unknown_job_404(client):
    assert client.post('/api/retest/resume',json={'job_id':'nope'}).status_code==404
def test_invalid_rows_isolated(client):
    result=upload(client,make_csv('00001,F-1,100,kg,2,Cu,N/A,dry,1','00002,F-1,100,kg,2,Cu,9,dry,1.5')).get_json()
    assert result['invalid']==2 and result['applied']==0
    from app.modules.m8_retest import service
    codes={i['原因码'] for i in service.dashboard()['issues']}
    assert {'MISSING','REVISION'}<=codes
def test_non_object_json_400(client):
    assert client.post('/api/retest',json=[1]).status_code==400
    assert client.post('/api/retest/resume',json='x').status_code==400
def test_wrong_upload_field_400(client):
    assert client.post('/api/retest',data={'wrong':(io.BytesIO(b'a,b'),'x.csv')}).status_code==400
def test_upload_file(client):
    response=client.post('/api/retest',data={'file':(io.BytesIO(V1.encode()),'retest.csv')})
    assert response.status_code==200 and response.get_json()['applied']==3
def test_sample_files_flow(client):
    from app.config import RETEST1, RETEST2
    first=upload(client,RETEST1.read_text(encoding='utf-8-sig')).get_json()
    assert first['applied']==6
    second=upload(client,RETEST2.read_text(encoding='utf-8-sig')).get_json()
    assert (second['applied'],second['stale'],second['conflict'],second['duplicate'])==(3,1,1,1)
    assert assay_row(client,'00001','Cu','F-1108')['修订号']==2
    assert current(client,'F-1109').status_code==200
def test_default_sample_when_csv_omitted(client):
    result=client.post('/api/retest',json={}).get_json()
    assert result['applied']==6 and result['status']=='done'
