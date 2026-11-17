import pytest
from fastapi import HTTPException
from src.services import series,runs
from src.schemas.series import SeriesInput,SeriesBudgetInput,SeriesStudyInput
from src.schemas.run import RunInput
from tests.conftest import make_batch

def one(session):
    return series.list_series(session)[0]

def start(session,user,sid,batch,name,alpha=None):
    data=SeriesStudyInput(study_id=batch.id,name=name,alpha=alpha)
    return series.start_study(session,sid,data,user)

def test_reserve_up_to_remaining_then_reject(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    assert one(session)['remaining']==pytest.approx(0.05)
    st1=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    assert st1['alpha']==pytest.approx(0.02) and st1['budget_state']=='reserved'
    assert queued==[st1['id']]
    assert series.complete_study(session,st1['id'],result={'metrics':{}}) is True
    assert one(session)['used']==pytest.approx(0.02)
    st2=start(session,user,s['id'],batch,'研究2')
    assert st2['alpha']==pytest.approx(0.03)
    assert one(session)['remaining']==pytest.approx(0)
    with pytest.raises(HTTPException) as e:
        start(session,user,s['id'],batch,'研究3',alpha=0.001)
    assert e.value.status_code==409
    assert one(session)['used']+one(session)['reserved']<=one(session)['total_budget']

def test_default_alpha_capped_at_max(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=1.0),user)
    st=start(session,user,s['id'],batch,'研究1')
    assert st['alpha']==pytest.approx(0.2)

def test_budget_locked_after_first_study(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    updated=series.update_series(session,s['id'],SeriesBudgetInput(total_budget=0.08),user)
    assert updated['total_budget']==pytest.approx(0.08)
    start(session,user,s['id'],batch,'研究1',alpha=0.01)
    assert one(session)['locked'] is True
    with pytest.raises(HTTPException) as e:
        series.update_series(session,s['id'],SeriesBudgetInput(total_budget=0.1),user)
    assert e.value.status_code==409
    actions=[x['action'] for x in one(session)['ledger']]
    assert 'lock' in actions and 'reserve' in actions

def test_published_budget_never_refunded(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    assert series.complete_study(session,st['id'],result={'metrics':{}}) is True
    with pytest.raises(HTTPException) as e:
        series.cancel_study(session,st['id'],user)
    assert e.value.status_code==409
    with pytest.raises(HTTPException) as e:
        series.retry_study(session,st['id'],user)
    assert e.value.status_code==409
    assert one(session)['used']==pytest.approx(0.02)

def test_cancel_releases_unpublished(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    cancelled=series.cancel_study(session,st['id'],user)
    assert cancelled['status']=='cancelled' and cancelled['budget_state']=='released'
    assert one(session)['reserved']==pytest.approx(0)
    assert one(session)['remaining']==pytest.approx(0.05)
    assert any('取消' in x['reason'] for x in one(session)['ledger'])
    st2=start(session,user,s['id'],batch,'研究2',alpha=0.05)
    assert st2['budget_state']=='reserved'

def test_late_result_cannot_revive_cancelled(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    series.cancel_study(session,st['id'],user)
    assert series.complete_study(session,st['id'],result={'metrics':{'p':1}}) is False
    st2=series.get_study(session,st['id'])
    assert st2['status']=='cancelled' and st2['result'] is None and st2['budget_state']=='released'
    assert one(session)['used']==pytest.approx(0)
    assert not any(x['action']=='use' for x in one(session)['ledger'])

def test_failure_releases_and_retry_no_double_charge(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    assert series.complete_study(session,st['id'],error='boom') is True
    assert one(session)['reserved']==pytest.approx(0) and one(session)['used']==pytest.approx(0)
    retried=series.retry_study(session,st['id'],user)
    assert retried['id']==st['id'] and retried['status']=='queued'
    assert retried['budget_state']=='reserved' and retried['alpha']==pytest.approx(0.02)
    assert queued[-1]==st['id']
    assert one(session)['reserved']==pytest.approx(0.02) and one(session)['used']==pytest.approx(0)
    assert series.complete_study(session,st['id'],result={'metrics':{}}) is True
    assert one(session)['used']==pytest.approx(0.02) and one(session)['reserved']==pytest.approx(0)
    actions=[x['action'] for x in one(session)['ledger']]
    assert actions==['use','reserve','release','reserve','lock','create']

def test_retry_rejected_when_budget_consumed(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st1=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    assert series.complete_study(session,st1['id'],error='boom') is True
    start(session,user,s['id'],batch,'研究2',alpha=0.05)
    with pytest.raises(HTTPException) as e:
        series.retry_study(session,st1['id'],user)
    assert e.value.status_code==409

def test_recovery_keeps_reservation(session,user,queued):
    from src.models.series import SeriesStudy
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st1=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    st2=start(session,user,s['id'],batch,'研究2',alpha=0.01)
    row=session.get(SeriesStudy,st2['id']);row.status='running';session.commit()
    assert set(series.recover(session))=={st1['id'],st2['id']}
    assert one(session)['reserved']==pytest.approx(0.03)
    series.cancel_study(session,st1['id'],user)
    assert series.recover(session)==[st2['id']]
    assert series.complete_study(session,st2['id'],result={'metrics':{}}) is True
    assert one(session)['used']==pytest.approx(0.01)

def test_budget_never_exceeds_total(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    start(session,user,s['id'],batch,'研究1',alpha=0.02)
    start(session,user,s['id'],batch,'研究2',alpha=0.02)
    with pytest.raises(HTTPException) as e:
        start(session,user,s['id'],batch,'研究3',alpha=0.02)
    assert e.value.status_code==409
    start(session,user,s['id'],batch,'研究3',alpha=0.01)
    with pytest.raises(HTTPException):
        start(session,user,s['id'],batch,'研究4',alpha=0.001)
    assert one(session)['reserved']==pytest.approx(0.05)

def test_alpha_and_budget_bounds(session,user,queued):
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    with pytest.raises(HTTPException) as e:
        start(session,user,s['id'],batch,'研究1',alpha=0.5)
    assert e.value.status_code==422
    with pytest.raises(HTTPException) as e:
        series.create_series(session,SeriesInput(name='系列二',total_budget=2),user)
    assert e.value.status_code==422

def test_worker_handle_series_completes_with_reserved_alpha(session,user,queued):
    from src.worker import handle_series
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    handle_series(session,st['id'])
    st2=series.get_study(session,st['id'])
    assert st2['status']=='completed' and st2['budget_state']=='used'
    assert st2['result']['metrics']['显著性阈值']==pytest.approx(0.02)
    assert 0<=st2['result']['metrics']['Fisher双侧p']<=1
    assert one(session)['used']==pytest.approx(0.02)

def test_worker_skips_cancelled_and_failure_releases(session,user,queued):
    from src.worker import handle_series
    batch=make_batch(session)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'研究1',alpha=0.02)
    series.cancel_study(session,st['id'],user)
    handle_series(session,st['id'])
    st2=series.get_study(session,st['id'])
    assert st2['status']=='cancelled' and st2['result'] is None
    bad=make_batch(session,name='批次二',rows=[('A-1',{'group':'A','success':87,'failure':13})])
    st3=start(session,user,s['id'],batch,'研究2',alpha=0.01)
    st4=start(session,user,s['id'],bad,'研究3',alpha=0.01)
    handle_series(session,st4['id'])
    st5=series.get_study(session,st4['id'])
    assert st5['status']=='failed' and st5['budget_state']=='released' and st5['error']
    assert one(session)['reserved']==pytest.approx(0.01)

def test_independent_runs_keep_original_behavior(session,user,run_redis):
    from src.worker import handle_run
    batch=make_batch(session)
    run=runs.create(session,RunInput(study_id=batch.id,name='独立研究',parameters={'alpha':0.05}),user)
    assert run['status']=='queued' and len(run['checksum'])==64
    assert run_redis==[('analysis-queue',run['id'])]
    assert series.list_series(session)==[]
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    handle_run(session,run['id'])
    done=runs.get(session,run['id'])
    assert done['status']=='completed' and done['result']['metrics']['显著性阈值']==pytest.approx(0.05)
    assert one(session)['used']==pytest.approx(0) and one(session)['reserved']==pytest.approx(0)

def test_full_queue_cycle_and_recovery(session,user,monkeypatch):
    from src.worker import dispatch
    pushes=[]
    class FakeRedis:
        @classmethod
        def from_url(cls,url): return cls()
        def rpush(self,q,item): pushes.append(item)
    monkeypatch.setattr('src.services.series.Redis',FakeRedis)
    monkeypatch.setattr('src.services.runs.Redis',FakeRedis)
    batch=make_batch(session)
    run=runs.create(session,RunInput(study_id=batch.id,name='独立研究',parameters={'alpha':0.05}),user)
    s=series.create_series(session,SeriesInput(name='系列一',total_budget=0.05),user)
    st=start(session,user,s['id'],batch,'系列研究1',alpha=0.02)
    assert pushes==[run['id'],f"series:{st['id']}"]
    for raw in pushes: dispatch(session,str(raw))
    assert runs.get(session,run['id'])['status']=='completed'
    done=series.get_study(session,st['id'])
    assert done['status']=='completed' and done['budget_state']=='used'
    assert one(session)['used']==pytest.approx(0.02)
    # 模拟中断：新建研究保持 queued，恢复列表重新入队后完成
    st2=start(session,user,s['id'],batch,'系列研究2',alpha=0.01)
    recovered=[f'series:{x}' for x in series.recover(session)]
    assert recovered==[f"series:{st2['id']}"]
    for raw in recovered: dispatch(session,raw)
    assert series.get_study(session,st2['id'])['status']=='completed'
    assert one(session)['used']==pytest.approx(0.03)
