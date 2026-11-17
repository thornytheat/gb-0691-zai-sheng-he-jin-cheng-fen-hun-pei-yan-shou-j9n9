from flask import Blueprint, request, jsonify, Response, render_template
from app.config import TITLE, MODULES, RETEST1, RETEST2
from app.errors import DomainError
from app.reader import decode
from app.modules.m8_retest import service
bp=Blueprint('m8',__name__)
def _limit(value):
    if value is None: return None
    try: n=int(value)
    except (ValueError,TypeError): raise DomainError('LIMIT','每批处理条数必须为正整数')
    if n<1: raise DomainError('LIMIT','每批处理条数必须为正整数')
    return n
@bp.route('/api/retest',methods=['POST'])
def upload():
    if request.files: return jsonify(service.ingest(decode(request.files['file'].read())))
    payload=request.get_json(silent=True) or {}
    text=payload.get('csv')
    if text is None: text=RETEST1.read_text(encoding='utf-8-sig')
    return jsonify(service.ingest(text,_limit(payload.get('limit'))))
@bp.route('/api/retest/resume',methods=['POST'])
def resume():
    payload=request.get_json(silent=True) or {}
    if not payload.get('job_id'): raise DomainError('MISSING','缺少复测任务号')
    return jsonify(service.process(payload['job_id'],_limit(payload.get('limit'))))
@bp.route('/api/retest/jobs')
def jobs(): return jsonify(service.store.jobs())
@bp.route('/api/retest/view')
def view():
    return jsonify(service.view(request.args.get('batch'),request.args.get('view','current'),request.args.get('signoff',type=int)))
@bp.route('/api/retest/signoff',methods=['POST'])
def decide():
    payload=request.get_json(silent=True) or {}
    return jsonify(service.signoff(payload.get('batch')))
@bp.route('/api/retest/export.csv')
def export():
    name,text=service.export(request.args.get('batch'),request.args.get('view','current'),request.args.get('signoff',type=int))
    return Response(text,mimetype='text/csv',headers={'Content-Disposition':'attachment; filename='+name})
@bp.route('/retest')
def page():
    data=service.dashboard(request.args.get('batch'),request.args.get('view','current'),request.args.get('signoff',type=int))
    return render_template('retest.html',title=TITLE,modules=MODULES,sample1=RETEST1.read_text(encoding='utf-8-sig'),sample2=RETEST2.read_text(encoding='utf-8-sig'),**data)
