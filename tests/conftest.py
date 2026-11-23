import pytest

from app.input import load
from app.main import create_app


@pytest.fixture
def dirty():
    return load('dirty')


@pytest.fixture
def clean():
    return load('clean')


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / 'archive')
    app.config['CREDENTIALS'] = str(tmp_path / 'credentials')
    return app.test_client()
