import json, time
from app.config import RULE_VERSION
from app.store import connection as base
from app.modules.m8_retest import rules
DDL=(
"CREATE TABLE IF NOT EXISTS retest_jobs(job_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, rule_version TEXT NOT NULL, version INTEGER NOT NULL, total INTEGER NOT NULL, processed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'running', rows_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS retest_events(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, seq INTEGER NOT NULL, batch TEXT, lot TEXT, element TEXT, revision TEXT, status TEXT NOT NULL, reason TEXT, line INTEGER, raw TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(job_id,seq))",
"CREATE TABLE IF NOT EXISTS assay_current(batch TEXT NOT NULL, lot TEXT NOT NULL, element TEXT NOT NULL, dry_mass TEXT NOT NULL, moisture TEXT NOT NULL, low TEXT NOT NULL, high TEXT NOT NULL, revision INTEGER NOT NULL, event_id INTEGER NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(batch,lot,element))",
"CREATE TABLE IF NOT EXISTS retest_quarantine(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, event_id INTEGER, batch TEXT, lot TEXT, element TEXT, revision TEXT, code TEXT NOT NULL, reason TEXT NOT NULL, current_value TEXT, incoming_value TEXT, created_at TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS signoffs(id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, seq INTEGER NOT NULL, signed_at TEXT NOT NULL, payload TEXT NOT NULL, revision_set TEXT NOT NULL, content_hash TEXT NOT NULL)")
def now(): return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def connection():
    db=base()
    for sql in DDL: db.execute(sql)
    return db
def get_job(job_id):
    with connection() as db: row=db.execute('SELECT * FROM retest_jobs WHERE job_id=?',(job_id,)).fetchone()
    return dict(row) if row else None
def jobs():
    with connection() as db: return [dict(r) for r in db.execute('SELECT job_id,version,status,total,processed,created_at,updated_at FROM retest_jobs ORDER BY version DESC')]
def next_version():
    with connection() as db: return db.execute('SELECT COALESCE(MAX(version),0)+1 AS v FROM retest_jobs').fetchone()['v']
def create_job(job_id,digest,version,rows):
    t=now()
    with connection() as db: db.execute('INSERT INTO retest_jobs(job_id,sha256,rule_version,version,total,processed,status,rows_json,created_at,updated_at) VALUES (?,?,?,?,?,0,?,?,?,?)',(job_id,digest,RULE_VERSION,version,len(rows),'running',json.dumps(rows,ensure_ascii=False),t,t))
def record_structural(job_id,bad):
    t=now()
    with connection() as db:
        for i,r in enumerate(bad):
            cur=db.execute('INSERT INTO retest_events(job_id,seq,batch,lot,element,revision,status,reason,line,raw,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(job_id,-(i+1),r.get('batch'),r.get('lot'),r.get('element'),r.get('revision'),'invalid',r.get('原因码','STRUCTURE')+':'+r.get('原因','结构错误'),r.get('行号'),json.dumps(r,ensure_ascii=False),t))
            db.execute('INSERT INTO retest_quarantine(job_id,event_id,batch,lot,element,revision,code,reason,current_value,incoming_value,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(job_id,cur.lastrowid,r.get('batch'),r.get('lot'),r.get('element'),r.get('revision'),r.get('原因码','STRUCTURE'),r.get('原因','结构错误'),None,json.dumps(r,ensure_ascii=False),t))
def apply_row(job_id,seq,raw,n):
    t=now()
    with connection() as db:
        current=db.execute('SELECT * FROM assay_current WHERE batch=? AND lot=? AND element=?',(n['batch'],n['lot'],n['element'])).fetchone()
        verdict=rules.arbitrate(current,n)
        cur=db.execute('INSERT INTO retest_events(job_id,seq,batch,lot,element,revision,status,reason,line,raw,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(job_id,seq,n['batch'],n['lot'],n['element'],str(n['revision']),verdict,None,raw.get('行号'),json.dumps(raw,ensure_ascii=False),t))
        if verdict=='applied':
            db.execute("INSERT INTO assay_current(batch,lot,element,dry_mass,moisture,low,high,revision,event_id,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(batch,lot,element) DO UPDATE SET dry_mass=excluded.dry_mass,moisture=excluded.moisture,low=excluded.low,high=excluded.high,revision=excluded.revision,event_id=excluded.event_id,updated_at=excluded.updated_at",(n['batch'],n['lot'],n['element'],n['dry_mass'],n['moisture'],n['low'],n['high'],n['revision'],cur.lastrowid,t))
        elif verdict=='conflict':
            held={'dry_mass':current['dry_mass'],'moisture':current['moisture'],'low':current['low'],'high':current['high'],'revision':current['revision']}
            incoming={k:n[k] for k in ('dry_mass','moisture','low','high','revision')}
            db.execute('INSERT INTO retest_quarantine(job_id,event_id,batch,lot,element,revision,code,reason,current_value,incoming_value,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(job_id,cur.lastrowid,n['batch'],n['lot'],n['element'],str(n['revision']),'SAME_REVISION','同版异值：修订号相同但数值不一致',json.dumps(held,ensure_ascii=False),json.dumps(incoming,ensure_ascii=False),t))
        db.execute("UPDATE retest_jobs SET processed=?, status=CASE WHEN ?>=total THEN 'done' ELSE status END, updated_at=? WHERE job_id=?",(seq+1,seq+1,t,job_id))
    return verdict
def apply_error(job_id,seq,raw,code,message):
    t=now()
    with connection() as db:
        cur=db.execute('INSERT INTO retest_events(job_id,seq,batch,lot,element,revision,status,reason,line,raw,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(job_id,seq,raw.get('batch'),raw.get('lot'),raw.get('element'),raw.get('revision'),'invalid',code+':'+message,raw.get('行号'),json.dumps(raw,ensure_ascii=False),t))
        db.execute('INSERT INTO retest_quarantine(job_id,event_id,batch,lot,element,revision,code,reason,current_value,incoming_value,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(job_id,cur.lastrowid,raw.get('batch'),raw.get('lot'),raw.get('element'),raw.get('revision'),code,message,None,json.dumps(raw,ensure_ascii=False),t))
        db.execute("UPDATE retest_jobs SET processed=?, status=CASE WHEN ?>=total THEN 'done' ELSE status END, updated_at=? WHERE job_id=?",(seq+1,seq+1,t,job_id))
def event_counts(job_id):
    with connection() as db: rows=db.execute('SELECT status,COUNT(*) AS c,SUM(CASE WHEN seq<0 THEN 1 ELSE 0 END) AS s FROM retest_events WHERE job_id=? GROUP BY status',(job_id,)).fetchall()
    counts={};structural=0
    for r in rows: counts[r['status']]=r['c'];structural+=r['s'] or 0
    counts['structural']=structural
    return counts
def current_rows(batch):
    with connection() as db: return [dict(r) for r in db.execute('SELECT * FROM assay_current WHERE batch=? ORDER BY lot,element',(batch,))]
def batches():
    with connection() as db: return [r['batch'] for r in db.execute('SELECT DISTINCT batch FROM assay_current ORDER BY batch')]
def quarantine():
    with connection() as db: return [dict(r) for r in db.execute('SELECT * FROM retest_quarantine ORDER BY id DESC')]
def stale_events():
    with connection() as db: return [dict(r) for r in db.execute("SELECT e.*, c.low AS cur_low, c.high AS cur_high, c.revision AS cur_revision FROM retest_events e LEFT JOIN assay_current c ON c.batch=e.batch AND c.lot=e.lot AND c.element=e.element WHERE e.status='stale' ORDER BY e.id DESC")]
def stats():
    with connection() as db:
        return {'jobs':db.execute('SELECT COUNT(*) AS c FROM retest_jobs').fetchone()['c'],
        'running':db.execute("SELECT COUNT(*) AS c FROM retest_jobs WHERE status='running'").fetchone()['c'],
        'keys':db.execute('SELECT COUNT(*) AS c FROM assay_current').fetchone()['c'],
        'quarantine':db.execute('SELECT COUNT(*) AS c FROM retest_quarantine').fetchone()['c'],
        'signoffs':db.execute('SELECT COUNT(*) AS c FROM signoffs').fetchone()['c'],
        'rule_version':RULE_VERSION}
def latest_signoff(batch):
    with connection() as db: row=db.execute('SELECT * FROM signoffs WHERE batch=? ORDER BY id DESC LIMIT 1',(batch,)).fetchone()
    return dict(row) if row else None
def get_signoff(ident):
    with connection() as db: row=db.execute('SELECT * FROM signoffs WHERE id=?',(ident,)).fetchone()
    return dict(row) if row else None
def signoffs_for(batch):
    with connection() as db: return [dict(r) for r in db.execute('SELECT id,batch,seq,signed_at FROM signoffs WHERE batch=? ORDER BY id DESC',(batch,))]
def create_signoff(batch,payload,content):
    t=now()
    with connection() as db:
        seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 AS s FROM signoffs WHERE batch=?',(batch,)).fetchone()['s']
        cur=db.execute('INSERT INTO signoffs(batch,seq,signed_at,payload,revision_set,content_hash) VALUES (?,?,?,?,?,?)',(batch,seq,t,json.dumps(payload,ensure_ascii=False),json.dumps(payload['修订集合'],ensure_ascii=False),content))
    return {'signoff_id':cur.lastrowid,'seq':seq,'signed_at':t}
