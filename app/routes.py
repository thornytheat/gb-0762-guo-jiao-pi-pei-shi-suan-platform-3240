from flask import Blueprint, current_app, jsonify

from .errors import TrialError
from .input import from_request
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.credentials.registry import listing, lookup, read_issued
from .modules.credentials.service import issue, revoke
from .pipeline import process

api = Blueprint('trial_api', __name__, url_prefix='/api')


def preview(stage):
    return process(from_request(), stage)[stage]


@api.post('/assay')
def assay():
    return preview('assay')


@api.post('/dry')
def dry():
    return preview('dry')


@api.post('/formula')
def formula():
    return preview('formula')


@api.post('/blend')
def blend():
    return preview('blend')


@api.post('/stock')
def stock():
    return preview('stock')


@api.post('/batches')
def batches():
    record, fresh = preserve(current_app.config['ARCHIVE'], from_request())
    return {'batch_id': record['batch_id'], 'created': fresh, 'record': record}, 201 if fresh else 200


@api.get('/batches')
def list_batches():
    return {'batches': history(current_app.config['ARCHIVE'])}


@api.get('/batches/<identifier>')
def batch(identifier):
    return read(current_app.config['ARCHIVE'], identifier)


@api.post('/credentials/<identifier>')
def grant(identifier):
    """签发最小凭据；同一留档重试只返回既有凭据，不重复出件。"""
    record = read(current_app.config['ARCHIVE'], identifier)
    envelope, fresh = issue(current_app.config['CREDENTIALS'], record)
    return envelope, 201 if fresh else 200


@api.get('/credentials')
def credentials():
    return {'credentials': listing(current_app.config['CREDENTIALS'])}


@api.get('/credentials/<identifier>')
def credential(identifier):
    """查凭据状态（含已撤回）。"""
    envelope = lookup(current_app.config['CREDENTIALS'], identifier)
    if envelope is None:
        raise TrialError('CREDENTIAL_NOT_FOUND', 404)
    return envelope


@api.post('/credentials/<identifier>/revoke')
def revoke_credential(identifier):
    """撤回：旧凭据立即失效并停止下载，留档原件仍可复查。"""
    envelope, _ = revoke(current_app.config['CREDENTIALS'], identifier)
    return envelope


@api.get('/download/<identifier>')
def download(identifier):
    """仅有效凭据可下载；未签发 404，已撤回 410。"""
    envelope = read_issued(current_app.config['CREDENTIALS'], identifier)
    response = jsonify(envelope)
    response.headers['Content-Disposition'] = f'attachment; filename="pectin-credential-{identifier[:12]}.json"'
    return response
