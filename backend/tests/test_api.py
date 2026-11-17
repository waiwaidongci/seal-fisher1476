import pytest
from fastapi.testclient import TestClient
from tests.conftest import make_batch

@pytest.fixture()
def client(session,queued,monkeypatch):
    from src.main import app
    from src.config.database import get_db
    class FakeRedis:
        def __init__(self): self.counts={}
        def incr(self,key): self.counts[key]=self.counts.get(key,0)+1;return self.counts[key]
        def expire(self,key,seconds): pass
    monkeypatch.setattr('src.middlewares.rate_limit.redis',FakeRedis())
    def override_get_db():
        yield session
    app.dependency_overrides[get_db]=override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture()
def token(session):
    from src.models.user import User
    from src.utils.security import hash_password,token
    u=User(email='admin@demo.local',role='admin',password_hash=hash_password('Research2026!'))
    session.add(u);session.commit()
    return token(u)

def auth(token): return {'Authorization':'Bearer '+token}

def test_series_api_flow(session,client,token):
    batch=make_batch(session)
    r=client.post('/series',json={'name':'系列一','total_budget':0.05},headers=auth(token))
    assert r.status_code==200,r.text
    sid=r.json()['id']
    assert r.json()['remaining']==pytest.approx(0.05)
    r=client.put(f'/series/{sid}',json={'total_budget':0.06},headers=auth(token))
    assert r.status_code==200 and r.json()['total_budget']==pytest.approx(0.06)
    r=client.post(f'/series/{sid}/studies',json={'study_id':batch.id,'name':'研究1','alpha':0.02},headers=auth(token))
    assert r.status_code==200,r.text
    study=r.json()
    assert study['budget_state']=='reserved' and study['alpha']==pytest.approx(0.02)
    r=client.put(f'/series/{sid}',json={'total_budget':0.1},headers=auth(token))
    assert r.status_code==409
    r=client.get('/series',headers=auth(token))
    assert r.json()[0]['locked'] is True and r.json()[0]['reserved']==pytest.approx(0.02)
    assert any(x['action']=='lock' for x in r.json()[0]['ledger'])
    r=client.post(f"/series-studies/{study['id']}/cancel",headers=auth(token))
    assert r.status_code==200 and r.json()['status']=='cancelled'
    r=client.post(f"/series-studies/{study['id']}/retry",headers=auth(token))
    assert r.status_code==200 and r.json()['status']=='queued'
    r=client.get('/series',headers=auth(token))
    assert r.json()[0]['reserved']==pytest.approx(0.02)

def test_series_api_requires_auth_and_writer(session,client):
    assert client.get('/series').status_code==401
    assert client.post('/series',json={'name':'系列一','total_budget':0.05}).status_code==401
    from src.models.user import User
    from src.utils.security import hash_password,token
    v=User(email='viewer@demo.local',role='viewer',password_hash=hash_password('Research2026!'))
    session.add(v);session.commit()
    r=client.post('/series',json={'name':'系列一','total_budget':0.05},headers=auth(token(v)))
    assert r.status_code==403
    assert client.get('/series',headers=auth(token(v))).status_code==200
