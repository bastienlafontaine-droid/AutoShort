from fastapi.testclient import TestClient
from autoshort import api,core

def test_api_requires_same_origin_token(workspace,monkeypatch):
    monkeypatch.setattr(api,'DATA',core.DATA);monkeypatch.setattr(api,'ROOT',core.ROOT)
    client=TestClient(api.app)
    assert client.post('/api/runs',json={'theme':'Histoire insolite'}).status_code==403
    token=client.get('/api/session').json()['token']
    h={'Origin':'http://127.0.0.1:8765','X-AutoShort-Token':token}
    r=client.post('/api/runs',headers=h,json={'theme':'Histoire insolite'})
    assert r.status_code==200
    rid=r.json()['id']
    assert client.get('/api/runs/'+rid).json()['status']=='QUEUED'
    assert client.get('/api/runs/'+rid+'/files/.env').status_code==404
    assert client.post('/api/runs/'+rid+'/cancel',headers=h,json={}).status_code==200
    assert client.get('/api/runs/'+rid).json()['status']=='CANCELLED'
    assert client.post('/api/runs/'+rid+'/resume',headers=h,json={}).status_code==200
    assert client.get('/api/runs/'+rid).json()['status']=='QUEUED'

def test_key_is_not_returned(workspace,monkeypatch):
    monkeypatch.setattr(api,'ROOT',core.ROOT)
    client=TestClient(api.app);token=client.get('/api/session').json()['token']
    h={'Origin':'http://127.0.0.1:8765','X-AutoShort-Token':token}
    r=client.post('/api/settings',headers=h,json={'brave_key':'test-secret-never-in-response'})
    assert r.json()=={'ok':True}
    assert core.secret('BRAVE_API_KEY')=='test-secret-never-in-response'
