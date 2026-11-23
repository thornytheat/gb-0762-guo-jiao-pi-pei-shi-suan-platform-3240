import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from app.modules.batches.seal import canonical, sha
from app.modules.credentials.service import build_payload


def archive(client, payload):
    return client.post('/api/batches', json=payload).json['batch_id']


def issue(client, batch_id):
    return client.post('/api/credentials/' + batch_id)


def test_issue_requires_all_four_gates_and_returns_minimal_payload(client):
    batch_id = archive(client, {'sample': 'dirty'})
    reply = issue(client, batch_id)
    assert reply.status_code == 201
    envelope = reply.json
    assert envelope['status'] == 'ISSUED' and envelope['revoked_at'] is None
    payload = envelope['payload']
    assert payload['can_issue'] and payload['blocking'] == []
    assert all(payload['checks'].values())
    # 最小凭据：没有批号、逐批化验、逐批库存、配方分配
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in ('PJ-', 'allocation', 'moisture', 'stock_g', 'expires', '"isolated"', 'raw'):
        assert secret not in serialized
    # 聚合判定数据齐全
    assert payload['totals']['mass_g'] == 10000
    assert payload['plan'] == {'target_g': 10000, 'step_g': 2500, 'dry_min_g': 8900,
                               'gel_low_sag': 150.0, 'gel_high_sag': 155.0}
    assert payload['reconcile'] == {'balanced': True, 'shortage_g': 0}


def test_gel_near_lower_bound_is_independently_recomputable_with_integers(client):
    """客户拿到凭据后，仅凭聚合整数即可在凝胶下限附近复算，无需逐批化验。"""
    batch_id = archive(client, {'sample': 'dirty'})
    payload = issue(client, batch_id).json['payload']
    dry_u, gel_moment = payload['totals']['dry_u'], int(payload['totals']['gel_moment'])
    low_msag = round(payload['plan']['gel_low_sag'] * 1000)
    high_msag = round(payload['plan']['gel_high_sag'] * 1000)
    # 整数叉乘判定区间，无浮点
    assert dry_u * low_msag <= gel_moment <= dry_u * high_msag
    # 展示 SAG 由客户自行四舍五入复算，与凭据一致
    sag = (Decimal(gel_moment) / dry_u / 1000).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    assert str(sag) == payload['totals']['gel_sag']
    # 干物与称量同样可独立复算门槛
    assert dry_u >= payload['plan']['dry_min_g'] * payload['scales']['dry']
    assert payload['plan']['dry_min_g'] == 8900
    assert payload['totals']['mass_g'] == payload['plan']['target_g']
    # 凭据号是负载的内容哈希，客户可验证未被篡改
    assert hashlib.sha256(canonical(payload)).hexdigest() == issue(client, batch_id).json['credential_id']


def test_retry_does_not_duplicate_credential(client):
    batch_id = archive(client, {'sample': 'clean'})
    first = issue(client, batch_id)
    second = issue(client, batch_id)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json == second.json
    assert len(client.get('/api/credentials').json['credentials']) == 1


def test_concurrent_issue_publishes_single_credential(tmp_path, dirty):
    from concurrent.futures import ThreadPoolExecutor
    from app.main import create_app
    from app.modules.batches.service import preserve
    from app.modules.credentials.service import issue as grant
    archive_root, cred_root = tmp_path / 'archive', tmp_path / 'credentials'
    record, _ = preserve(archive_root, dirty)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: grant(cred_root, record), range(7)))
    assert sum(fresh for _, fresh in results) == 1
    assert len(list(cred_root.glob('*/credential.json'))) == 1
    assert len({env['credential_id'] for env, _ in results}) == 1


def test_gate_failure_blocks_issue_with_explicit_codes(client, dirty):
    dirty['plan'].update(gel_low_sag=195, gel_high_sag=200)
    batch_id = archive(client, dirty)
    reply = issue(client, batch_id)
    assert reply.status_code == 422 and reply.json['code'] == 'CREDENTIAL_GATE_FAILED'
    # 未签发则状态查询 404，下载 404
    assert client.get('/api/credentials/' + batch_id).status_code == 404
    assert client.get('/api/download/' + batch_id).status_code == 404


def test_dry_gate_reported_when_plan_demands_more_dry_than_achievable(client, dirty):
    # 干物下限高于可达干物时，寻优不可行，阻断码须如实包含干物门槛
    dirty['plan']['dry_min_g'] = 9999
    batch_id = archive(client, dirty)
    reply = issue(client, batch_id)
    assert reply.status_code == 422
    record = client.get('/api/batches/' + batch_id).json
    payload, passed = build_payload(record)
    assert not passed and 'GATE_DRY' in payload['blocking']


def test_revoke_invalidates_credential_and_stops_download_but_archive_remains(client):
    batch_id = archive(client, {'sample': 'clean'})
    issued = issue(client, batch_id).json
    # 有效时可下载
    download = client.get('/api/download/' + batch_id)
    assert download.status_code == 200 and download.json == issued
    assert download.headers['Content-Disposition'].startswith('attachment;')
    # 撤回
    revoked = client.post('/api/credentials/' + batch_id + '/revoke')
    assert revoked.status_code == 200 and revoked.json['status'] == 'REVOKED'
    assert revoked.json['revoked_at'] and revoked.json['credential_id'] == issued['credential_id']
    # 旧凭据状态仍可查，但下载停止
    status = client.get('/api/credentials/' + batch_id)
    assert status.status_code == 200 and status.json['status'] == 'REVOKED'
    assert client.get('/api/download/' + batch_id).status_code == 410
    # 撤回后重试签发不会复活、不出新件
    again = issue(client, batch_id)
    assert again.status_code == 200 and again.json['status'] == 'REVOKED'
    # 留档原件仍可完整复查
    record = client.get('/api/batches/' + batch_id)
    assert record.status_code == 200 and record.json['batch_id'] == batch_id
    assert record.json['stages']['stock']['rows']


def test_revoke_unknown_credential_is_404(client):
    batch_id = archive(client, {'sample': 'clean'})
    reply = client.post('/api/credentials/' + batch_id + '/revoke')
    assert reply.status_code == 404 and reply.json['code'] == 'CREDENTIAL_NOT_FOUND'


def test_credential_listing_exposes_status_per_batch(client):
    first = archive(client, {'sample': 'clean'})
    second = archive(client, {'sample': 'dirty'})
    issue(client, first)
    rows = client.get('/api/credentials').json['credentials']
    assert [row['payload']['batch_id'] for row in rows] == [first]
    client.post('/api/credentials/' + first + '/revoke')
    issue(client, second)
    statuses = {row['payload']['batch_id']: row['status']
                for row in client.get('/api/credentials').json['credentials']}
    assert statuses == {first: 'REVOKED', second: 'ISSUED'}


def test_credential_survives_application_restart(tmp_path, dirty, monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('PECTIN_ARCHIVE', str(tmp_path / 'archive'))
    monkeypatch.setenv('PECTIN_CREDENTIALS', str(tmp_path / 'credentials'))
    client = create_app().test_client()
    batch_id = client.post('/api/batches', json=dirty).json['batch_id']
    issued = issue(client, batch_id).json
    restarted = create_app().test_client()
    assert restarted.get('/api/credentials/' + batch_id).json == issued
    assert restarted.get('/api/download/' + batch_id).status_code == 200


def test_customer_recomputes_using_only_public_credential_numbers(client):
    """模拟客户：只拿到凭据文件，不访问任何内部接口即可复算全部四项判定。"""
    batch_id = archive(client, {'sample': 'dirty'})
    credential = issue(client, batch_id).json['payload']

    plan, totals, scales = credential['plan'], credential['totals'], credential['scales']
    dry_u, gel_moment = totals['dry_u'], int(totals['gel_moment'])

    customer_checks = {
        'mass': totals['mass_g'] == plan['target_g'],
        'dry': dry_u >= plan['dry_min_g'] * scales['dry'],
        'gel_low': gel_moment >= dry_u * round(plan['gel_low_sag'] * scales['gel_sag']),
        'gel_high': gel_moment <= dry_u * round(plan['gel_high_sag'] * scales['gel_sag']),
        'reconciled': credential['reconcile']['balanced'] and credential['reconcile']['shortage_g'] == 0,
    }
    assert customer_checks == credential['checks']
    assert all(customer_checks.values())
    # 客户自行算出的 SAG 与车间展示值一致（下限附近 153.333，距下限 150 可量化核对）
    sag = (Decimal(gel_moment) / dry_u / scales['gel_sag']).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    assert str(sag) == totals['gel_sag']
