from app.stages import STAGES


def test_station_links_and_stock_page(client):
    home = client.get('/')
    assert '配方余量轨'.encode() in home.data and b'17000 g' in home.data
    for path, name in STAGES:
        reply = client.get('/trial/' + path)
        assert reply.status_code == 200 and name.encode() in reply.data


def test_invalid_form_retains_repair_fields(client):
    response = client.post('/trial/formula', data={'sample':'custom','proposal':'{broken','assays':'draft,row','step_g':'350'})
    assert all(value in response.data for value in (b'BAD_PROPOSAL_JSON', b'{broken', b'draft,row', b'350'))


def test_certificate_page_issues_revokes_and_hides_lot_details(client):
    batch_id = client.post('/api/batches', json={'sample': 'dirty'}).json['batch_id']
    page = client.get('/trial/certificate?batch=' + batch_id)
    assert page.status_code == 200 and b'PJ-01' not in page.data and '签发凭据'.encode() in page.data
    issued = client.post('/trial/certificate?batch=' + batch_id, data={'action': 'issue', 'batch_id': batch_id})
    assert 'ISSUED'.encode() in issued.data and '下载有效凭据'.encode() in issued.data
    revoked = client.post('/trial/certificate?batch=' + batch_id, data={'action': 'revoke', 'batch_id': batch_id})
    assert 'REVOKED'.encode() in revoked.data and '下载已停止'.encode() in revoked.data
    # 列表页展示凭据状态
    listing = client.get('/trial/certificate')
    assert 'REVOKED'.encode() in listing.data


def test_certificate_page_blocks_issue_when_gate_fails(client, dirty):
    dirty['plan'].update(gel_low_sag=195, gel_high_sag=200)
    batch_id = client.post('/api/batches', json=dirty).json['batch_id']
    page = client.get('/trial/certificate?batch=' + batch_id)
    assert b'GATE_GEL_LOW' in page.data and b'disabled' in page.data
