import os,sys,tempfile
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
os.environ.setdefault('REDIS_URL','redis://localhost:6379/0')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('ARTIFACTS_DIR',tempfile.mkdtemp(prefix='artifacts-'))
import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

@pytest.fixture()
def session():
    from src.config.database import Base
    from src.models import user,study,observation,run,review,audit,series
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    with Session() as db:
        yield db

@pytest.fixture()
def user():
    return SimpleNamespace(email='analyst@demo.local',role='analyst')

@pytest.fixture()
def queued(monkeypatch):
    items=[]
    monkeypatch.setattr('src.services.series.enqueue',lambda sid:items.append(sid))
    return items

@pytest.fixture()
def run_redis(monkeypatch):
    pushes=[]
    class FakeRedis:
        @classmethod
        def from_url(cls,url): return cls()
        def rpush(self,q,item): pushes.append((q,item))
    monkeypatch.setattr('src.services.runs.Redis',FakeRedis)
    return pushes

def make_batch(session,name='批次一',rows=None):
    from src.models.study import Study
    from src.models.observation import Observation
    s=Study(name=name,source_filename='field.csv',description='')
    session.add(s);session.flush()
    for key,values in (rows or [('A-1',{'group':'A','success':87,'failure':13}),('B-1',{'group':'B','success':96,'failure':4})]):
        session.add(Observation(study_id=s.id,source_key=key,values=values))
    session.commit();return s
