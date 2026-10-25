import copy
import pytest
from autoshort import core

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    original=core.ROOT
    (tmp_path/'config.toml').write_text((original/'config.toml').read_text(),encoding='utf-8')
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'DATA',tmp_path/'data')
    return tmp_path

@pytest.fixture
def ctx(workspace):
    return core.Context(core.new_run('Histoires vraies insolites'))
