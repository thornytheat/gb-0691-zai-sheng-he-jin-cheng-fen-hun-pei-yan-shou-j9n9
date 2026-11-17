from app.domain import mass_kg, assay_bounds
from app.numeric import number
from app.errors import DomainError
from app.reader import read_rows
def parse(text):
    ctx={'text':text,'quarantine':[]}
    rows=read_rows(ctx)
    return rows,ctx['quarantine']
def normalize(r):
    if not r['batch'] or not r['lot']: raise DomainError('MISSING','炉次或批号为空')
    mass=mass_kg(r['mass'],r['unit']);water=number(r['moisture'])
    if not 0<=water<100: raise DomainError('RANGE','水分须小于100%')
    if r['element'] not in ('Cu','Zn'): raise DomainError('ELEMENT','未知元素')
    if r['basis'] not in ('wet','dry'): raise DomainError('BASIS','干湿基无效')
    low,high=assay_bounds(r['assay']);dry=mass*(1-water/100)
    if r['basis']=='wet': low,high=low/(1-water/100),high/(1-water/100)
    if high>100: raise DomainError('RANGE','转换后含量大于100%')
    revision=number(r['revision'])
    if revision!=revision.to_integral_value() or revision<1: raise DomainError('REVISION','修订号须为正整数')
    return {'batch':r['batch'],'lot':r['lot'],'element':r['element'],'dry_mass':str(dry),'moisture':str(water),'low':str(low),'high':str(high),'revision':int(revision)}
def fingerprint(n): return (n['dry_mass'],n['moisture'],n['low'],n['high'])
def held_fingerprint(current): return (current['dry_mass'],current['moisture'],current['low'],current['high'])
def arbitrate(current,n):
    if current is None: return 'applied'
    if n['revision']>current['revision']: return 'applied'
    if n['revision']<current['revision']: return 'stale'
    if fingerprint(n)==held_fingerprint(current): return 'duplicate'
    return 'conflict'
