import json


def test_evidence_matches_preview_inventory_and_formula(client):
    stock = client.post('/api/stock', json={'sample':'dirty'}).json
    key = client.post('/api/batches', json={'sample':'dirty'}).json['batch_id']
    pack = client.get('/api/batches/' + key).json
    assert pack['stages']['stock'] == stock
    assert pack['stages']['blend']['allocation'] == {'PJ-01':5000, 'PJ-02':5000}


def test_issued_credential_aggregates_match_preview_without_lot_detail(client):
    blend = client.post('/api/blend', json={'sample':'dirty'}).json
    key = client.post('/api/batches', json={'sample':'dirty'}).json['batch_id']
    payload = client.post('/api/credentials/' + key).json['payload']
    assert payload['totals']['mass_g'] == 10000
    assert payload['totals']['dry_g'] == blend['dry_g']
    assert payload['totals']['gel_sag'] == blend['gel_sag']
    assert 'PJ-01' not in json.dumps(payload, ensure_ascii=False)
