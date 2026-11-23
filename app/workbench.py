import json

from flask import Blueprint, abort, current_app, render_template, request

from .config import REVISION
from .errors import TrialError
from .input import load
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.credentials.registry import listing as credential_listing
from .modules.credentials.registry import lookup
from .modules.credentials.service import build_payload, issue, revoke
from .pipeline import process
from .stages import LABELS, PLAN_FIELDS, STAGES

station = Blueprint('station', __name__)


def materials(mode):
    if mode != 'custom':
        return load(mode)
    try:
        proposal = json.loads(request.form.get('proposal', '{}'))
    except ValueError:
        raise TrialError('BAD_PROPOSAL_JSON') from None
    return {'assays': request.form.get('assays', ''), 'plan': {key: request.form.get(key, '') for key in PLAN_FIELDS},
            'proposal': proposal}


def _credential_view(root, cred_root, batch_id):
    record = read(root, batch_id)
    payload, passed = build_payload(record)
    envelope = lookup(cred_root, batch_id)
    return {'batch_id': batch_id, 'payload': payload, 'passed': passed, 'envelope': envelope}


@station.route('/', methods=['GET', 'POST'])
@station.route('/trial/<stage>', methods=['GET', 'POST'])
def review(stage='stock'):
    if stage not in LABELS:
        abort(404)
    mode = request.values.get('sample', 'dirty')
    data, pack, error, record, entries, fresh = {}, None, None, None, [], False
    root = current_app.config['ARCHIVE']
    cred_root = current_app.config['CREDENTIALS']
    source = {}
    try:
        source = materials(mode)
        if stage in ('batches', 'certificate'):
            if stage == 'batches' and request.method == 'POST':
                record, fresh = preserve(root, source)
            entries = history(root)
            if stage == 'certificate':
                selected = request.args.get('batch') or (entries[0]['batch_id'] if entries else None)
                if request.method == 'POST' and request.form.get('action') in ('issue', 'revoke'):
                    selected = request.form.get('batch_id') or selected
                    if request.form['action'] == 'issue':
                        issue(cred_root, read(root, selected))
                    else:
                        revoke(cred_root, selected)
                credentials = {item['payload']['batch_id']: item for item in credential_listing(cred_root)}
                if selected:
                    pack = _credential_view(root, cred_root, selected)
                    pack['envelope'] = credentials.get(selected)
                entries = [{**row, 'credential': credentials.get(row['batch_id'])} for row in entries]
        else:
            data = process(source, stage)
    except TrialError as exc:
        error = exc.code
    form_plan = request.form if mode == 'custom' else source.get('plan', {})
    form_assays = request.form.get('assays', '') if mode == 'custom' else source.get('assays', '')
    form_proposal = request.form.get('proposal', '{}') if mode == 'custom' else json.dumps(source.get('proposal', {}))
    return render_template('station.html', stages=STAGES, labels=LABELS, fields=PLAN_FIELDS,
                           revision=REVISION, stage=stage, mode=mode, data=data, error=error,
                           form_plan=form_plan, form_assays=form_assays, form_proposal=form_proposal,
                           record=record, fresh=fresh, entries=entries, pack=pack)
