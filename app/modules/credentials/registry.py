"""凭据登记处：按留档批号一凭据，原子发布；撤回只改状态，留档目录不动。"""
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.errors import TrialError
from app.modules.batches.seal import canonical

FILENAME = 'credential.json'


def _dir(root, batch_id):
    if not re.fullmatch('[a-f0-9]{64}', batch_id):
        raise TrialError('BATCH_NOT_FOUND', 404)
    return Path(root) / batch_id


def lookup(root, batch_id):
    target = _dir(root, batch_id) / FILENAME
    if not target.exists():
        return None
    return json.loads(target.read_bytes())


def read_issued(root, batch_id):
    """供下载使用：不存在 404，已撤回 410。"""
    envelope = lookup(root, batch_id)
    if envelope is None:
        raise TrialError('CREDENTIAL_NOT_FOUND', 404)
    if envelope['status'] != 'ISSUED':
        raise TrialError('CREDENTIAL_REVOKED', 410)
    return envelope


def listing(root, limit=50):
    base = Path(root)
    if not base.exists():
        return []
    paths = sorted((p for p in base.glob('*/' + FILENAME)), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:limit]
    return [json.loads(p.read_bytes()) for p in paths]


def _atomic(target, envelope):
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=directory, delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(canonical(envelope))
            file.flush()
            os.fsync(file.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)


def publish(root, batch_id, envelope):
    """原子发布，返回 (落盘凭据, 是否首次)。并发下仅一个硬链接成功。"""
    target = _dir(root, batch_id) / FILENAME
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=directory, delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(canonical(envelope))
            file.flush()
            os.fsync(file.fileno())
            try:
                os.link(temp, target)
            except FileExistsError:
                return lookup(root, batch_id), False
            return envelope, True
        finally:
            temp.unlink(missing_ok=True)


def revoke(root, batch_id, envelope):
    target = _dir(root, batch_id) / FILENAME
    _atomic(target, envelope)
    return envelope
