"""客户凭据：只暴露可独立复算的聚合数据，不泄露逐批化验与库存。

判定门槛（全部满足才可签发）：
  称量 mass_g == target_g；干物 dry_u >= dry_min_u；
  凝胶 gel_low <= gel_sag <= gel_high（毫 SAG 整数叉乘）；
  领用对账 balanced 且 shortage_g == 0。
"""
from datetime import datetime, timezone

from app.errors import TrialError
from app.modules.batches.seal import canonical, sha
from app.modules.formula.metrics import quality
from .registry import lookup, publish, revoke as store_revoke

ISSUED = 'ISSUED'
REVOKED = 'REVOKED'
GATE_CODES = {'mass': 'GATE_MASS', 'dry': 'GATE_DRY', 'gel_low': 'GATE_GEL_LOW', 'gel_high': 'GATE_GEL_HIGH'}


def build_payload(record):
    """从完整留档提取最小凭据负载：聚合值与计划约束，不含批号/逐批化验/逐批库存。"""
    stages = record['stages']
    plan = stages['plan']
    blend, stock = stages['blend'], stages['stock']
    dry_u, gel_moment = blend.get('dry_u', 0), int(blend.get('gel_moment', 0))
    checks = quality(plan, stock['issued_g'], dry_u, gel_moment)
    checks['reconciled'] = bool(stock['balanced'] and stock['shortage_g'] == 0)
    passed = all(checks.values()) and blend['status'] == 'FEASIBLE'
    blocking = [code for key, code in GATE_CODES.items() if not checks[key]]
    if not checks['reconciled']:
        blocking.append('GATE_RECONCILE')
    if blend['status'] != 'FEASIBLE':
        blocking.append('GATE_BLEND_' + blend['status'])
    return {
        'schema': 'pectin-credential-1.0',
        'batch_id': record['batch_id'],
        'assay_sha256': record['assay_sha256'],
        'as_of': plan['as_of'],
        'plan': {
            'target_g': plan['target_g'], 'step_g': plan['step_g'],
            'dry_min_g': plan['dry_min_u'] // 10_000,
            'gel_low_sag': plan['gel_low_sag'] / 1000, 'gel_high_sag': plan['gel_high_sag'] / 1000,
        },
        'scales': {'gel_sag': 1000, 'dry': 10000},
        'totals': {
            'mass_g': stock['issued_g'],
            'dry_u': dry_u, 'dry_g': blend.get('dry_g'),
            'gel_moment': str(gel_moment), 'gel_sag': blend.get('gel_sag'),
        },
        'reconcile': {'balanced': stock['balanced'], 'shortage_g': stock['shortage_g']},
        'checks': checks,
        'can_issue': passed,
        'blocking': blocking,
        'counts': {'accepted_lots': stages['assay']['counts']['accepted'],
                   'isolated_lines': stages['assay']['counts']['isolated']},
    }, passed


def issue(root, record, now=None):
    """签发凭据。重试不重复出件；已撤回的旧凭据不会复活。"""
    payload, passed = build_payload(record)
    if not passed:
        raise TrialError('CREDENTIAL_GATE_FAILED', 422)
    existing = lookup(root, record['batch_id'])
    if existing is not None:
        return existing, False
    envelope = {
        'credential_id': sha(canonical(payload)),
        'status': ISSUED,
        'issued_at': (now or datetime.now(timezone.utc)).isoformat(timespec='seconds'),
        'revoked_at': None,
        'payload': payload,
    }
    return publish(root, record['batch_id'], envelope)


def revoke(root, batch_id, now=None):
    """撤回凭据：旧凭据立即失效并停止下载；留档原件不动。"""
    existing = lookup(root, batch_id)
    if existing is None:
        raise TrialError('CREDENTIAL_NOT_FOUND', 404)
    if existing['status'] == REVOKED:
        return existing, False
    clock = now or datetime.now(timezone.utc)
    updated = {**existing, 'status': REVOKED, 'revoked_at': clock.isoformat(timespec='seconds')}
    return store_revoke(root, batch_id, updated), True
