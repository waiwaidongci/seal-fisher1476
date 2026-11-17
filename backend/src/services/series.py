import os
from decimal import Decimal
from redis import Redis
from sqlalchemy import select
from fastapi import HTTPException
from src.models.series import Series,SeriesStudy,SeriesLedger
from src.services import studies
from src.services.domain_validation import validate_parameters
from src.services.audits import log
from src.utils.serializers import record,now,checksum

Q=Decimal('0.000000001')
ALPHA_MIN=Decimal('0.001');ALPHA_MAX=Decimal('0.2');BUDGET_MAX=Decimal('1')
def dec(x): return Decimal(str(x)).quantize(Q)

def enqueue(study_id):
    Redis.from_url(os.environ['REDIS_URL']).rpush('analysis-queue',f'series:{study_id}')

def balances(db,series_id):
    used=Decimal(0);reserved=Decimal(0)
    for st in db.scalars(select(SeriesStudy).where(SeriesStudy.series_id==series_id)):
        if st.budget_state=='used': used+=dec(st.alpha)
        elif st.budget_state=='reserved': reserved+=dec(st.alpha)
    return used,reserved

def lock_series(db,series_id):
    s=db.scalar(select(Series).where(Series.id==series_id).with_for_update())
    if not s: raise HTTPException(404,'研究系列不存在')
    return s

def ledger(db,series,study_ref,action,amount,reason):
    used,reserved=balances(db,series.id)
    db.add(SeriesLedger(series_id=series.id,study_ref=study_ref,action=action,amount=dec(amount),used=used,reserved=reserved,reason=reason,created_at=now()))

def study_json(st):
    x=record(st);x['alpha']=float(dec(st.alpha));return x

def series_json(db,s):
    used,reserved=balances(db,s.id);total=dec(s.total_budget)
    return {'id':s.id,'name':s.name,'total_budget':float(total),'locked':bool(s.locked),'created_at':s.created_at,
        'used':float(used),'reserved':float(reserved),'remaining':float(total-used-reserved),
        'studies':[study_json(x) for x in db.scalars(select(SeriesStudy).where(SeriesStudy.series_id==s.id).order_by(SeriesStudy.id.desc()))],
        'ledger':[record(x)|{'amount':float(dec(x.amount)),'used':float(dec(x.used)),'reserved':float(dec(x.reserved))} for x in db.scalars(select(SeriesLedger).where(SeriesLedger.series_id==s.id).order_by(SeriesLedger.id.desc()).limit(50))]}

def list_series(db):
    return [series_json(db,s) for s in db.scalars(select(Series).order_by(Series.id))]

def check_budget(budget):
    if not ALPHA_MIN<=budget<=BUDGET_MAX: raise HTTPException(422,'系列总额度须在0.001到1之间')

def create_series(db,data,user):
    budget=dec(data.total_budget);check_budget(budget)
    if db.scalar(select(Series).where(Series.name==data.name)): raise HTTPException(409,'系列名称已存在')
    s=Series(name=data.name,total_budget=budget,locked=False,created_at=now())
    db.add(s);db.flush()
    ledger(db,s,None,'create',budget,f'建立系列，共享显著性总额 {budget}；首项研究发起后总额锁定')
    log(db,user,'series.create',data.name);db.commit()
    return series_json(db,s)

def update_series(db,series_id,data,user):
    s=lock_series(db,series_id)
    if s.locked: raise HTTPException(409,'首项研究已发起，系列总额已锁定，不可再调整')
    budget=dec(data.total_budget);check_budget(budget)
    old=dec(s.total_budget);s.total_budget=budget
    ledger(db,s,None,'update',budget,f'总额由 {old} 调整为 {budget}（首项研究前可调整）')
    log(db,user,'series.budget.update',f'{series_id}: {old} -> {budget}');db.commit()
    return series_json(db,s)

def start_study(db,series_id,data,user):
    s=lock_series(db,series_id)
    rows=studies.observations(db,data.study_id)
    if not rows: raise HTTPException(422,'先录入至少一条业务观测')
    used,reserved=balances(db,series_id)
    remaining=dec(s.total_budget)-used-reserved
    if data.alpha is None:
        alpha=min(remaining,ALPHA_MAX)
        if alpha<ALPHA_MIN: raise HTTPException(409,f'系列剩余额度不足（剩余 {remaining}），无法发起研究')
    else:
        alpha=dec(data.alpha)
        if not ALPHA_MIN<=alpha<=ALPHA_MAX: raise HTTPException(422,'检验阈值须在0.001到0.2之间')
        if alpha>remaining: raise HTTPException(409,f'预占 {alpha} 超出系列剩余额度（已用 {used} + 预占中 {reserved}，剩余 {remaining}）')
    try: params=validate_parameters({'alpha':float(alpha)})
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    snapshot=[{'source_key':x['source_key'],'values':x['values']} for x in rows]
    if not s.locked:
        s.locked=True
        ledger(db,s,None,'lock',0,f'首项研究发起，系列总额锁定为 {dec(s.total_budget)}')
    st=SeriesStudy(series_id=series_id,study_id=data.study_id,name=data.name,status='queued',alpha=alpha,budget_state='reserved',parameters=params,snapshot=snapshot,checksum=checksum(snapshot),created_at=now())
    db.add(st);db.flush()
    ledger(db,s,st.id,'reserve',alpha,f'研究「{data.name}」预占检验阈值，本次检验按 α={alpha} 判定')
    log(db,user,'series.study.start',f'{series_id}/{st.id} α={alpha}');db.commit()
    enqueue(st.id)
    return study_json(st)

def get_study(db,study_id):
    st=db.get(SeriesStudy,study_id)
    if not st: raise HTTPException(404,'系列研究不存在')
    return study_json(st)

def cancel_study(db,study_id,user):
    st=db.get(SeriesStudy,study_id)
    if not st: raise HTTPException(404,'系列研究不存在')
    s=lock_series(db,st.series_id)
    st=db.scalar(select(SeriesStudy).where(SeriesStudy.id==study_id).with_for_update())
    if st.status=='completed': raise HTTPException(409,'结果已公开，已用额度不可退回')
    if st.status in ('failed','cancelled'): raise HTTPException(409,'研究已结束，无需取消')
    st.status='cancelled'
    if st.budget_state=='reserved':
        st.budget_state='released';db.flush()
        ledger(db,s,st.id,'release',st.alpha,f'研究「{st.name}」在公开前取消，预占额度释放')
    log(db,user,'series.study.cancel',study_id);db.commit()
    return study_json(st)

def retry_study(db,study_id,user):
    st=db.get(SeriesStudy,study_id)
    if not st: raise HTTPException(404,'系列研究不存在')
    s=lock_series(db,st.series_id)
    st=db.scalar(select(SeriesStudy).where(SeriesStudy.id==study_id).with_for_update())
    if st.status not in ('failed','cancelled'): raise HTTPException(409,'仅失败或已取消的研究可重试')
    if st.budget_state=='released':
        used,reserved=balances(db,st.series_id)
        remaining=dec(s.total_budget)-used-reserved
        if dec(st.alpha)>remaining: raise HTTPException(409,f'系列剩余额度不足（剩余 {remaining}），无法沿用原阈值重试')
        st.budget_state='reserved';db.flush()
        ledger(db,s,st.id,'reserve',st.alpha,f'研究「{st.name}」重试，沿用原研究与原阈值重新预占')
    st.status='queued';st.error='';st.result=None
    log(db,user,'series.study.retry',study_id);db.commit()
    enqueue(st.id)
    return study_json(st)

def complete_study(db,study_id,result=None,error=None):
    st=db.get(SeriesStudy,study_id)
    if not st: return False
    s=lock_series(db,st.series_id)
    st=db.scalar(select(SeriesStudy).where(SeriesStudy.id==study_id).with_for_update())
    if st.budget_state!='reserved' or st.status not in ('queued','running'):
        return False
    if error is None:
        st.budget_state='used';db.flush()
        ledger(db,s,st.id,'use',st.alpha,f'研究「{st.name}」结果公开，预占额度转为已用，永不退回')
        st.result=result;st.status='completed'
    else:
        st.budget_state='released';db.flush()
        ledger(db,s,st.id,'release',st.alpha,f'研究「{st.name}」计算失败未公开，预占额度释放')
        st.status='failed';st.error=error
    db.commit()
    return True

def recover(db):
    return list(db.scalars(select(SeriesStudy.id).where(SeriesStudy.status.in_(['queued','running']),SeriesStudy.budget_state=='reserved')))
