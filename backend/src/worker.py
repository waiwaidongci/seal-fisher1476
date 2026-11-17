import os,time,json,logging
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from src.config.database import Session
from src.models.run import Run
from src.models.series import SeriesStudy
from src.models import user,study,observation,review,audit,series
from src.services.algorithm import calculate
from src.services import series as series_service
from src.utils.serializers import checksum
ARTIFACTS=os.environ.get('ARTIFACTS_DIR','/app/artifacts')

def handle_run(db,id):
    run=db.get(Run,id)
    if not run or run.status in ('completed','failed'): return
    run.status='running';db.commit()
    try:
        if checksum(run.snapshot)!=run.checksum: raise ValueError('输入快照校验失败')
        result=calculate(run.snapshot,run.parameters)
        result['input_sha256']=run.checksum
        run.result=result;run.status='completed'
        Path(f'{ARTIFACTS}/run-{id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except Exception as e:
        logging.exception('analysis failed');run.status='failed';run.error=str(e)
    db.commit()

def handle_series(db,id):
    st=db.get(SeriesStudy,id)
    if not st or st.status not in ('queued','running') or st.budget_state!='reserved': return
    st.status='running';db.commit()
    try:
        if checksum(st.snapshot)!=st.checksum: raise ValueError('输入快照校验失败')
        result=calculate(st.snapshot,st.parameters)
        result['input_sha256']=st.checksum
    except Exception as e:
        logging.exception('series study failed');series_service.complete_study(db,id,error=str(e));return
    if series_service.complete_study(db,id,result=result):
        Path(f'{ARTIFACTS}/series-study-{id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))

def dispatch(db,raw):
    if raw.startswith('series:'): handle_series(db,int(raw.split(':',1)[1]))
    else: handle_run(db,int(raw))

def main():
    redis=Redis.from_url(os.environ['REDIS_URL'])
    Path(ARTIFACTS).mkdir(exist_ok=True)
    # Recover jobs interrupted after dequeue. A project runs exactly one worker.
    with Session() as db:
        pending=list(db.scalars(select(Run).where(Run.status.in_(['queued','running']))))
        for run in pending: redis.rpush('analysis-queue',run.id)
        for sid in series_service.recover(db): redis.rpush('analysis-queue',f'series:{sid}')
    while True:
        Path('/tmp/worker-heartbeat').touch()
        job=redis.blpop('analysis-queue',timeout=2)
        if not job: continue
        raw=job[1].decode() if isinstance(job[1],bytes) else str(job[1])
        with Session() as db: dispatch(db,raw)
if __name__=='__main__': main()
