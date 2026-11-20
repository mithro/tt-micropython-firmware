'''
Tests for UserConfig handling of the DEFAULT 'project' list and
'switch_interval'.

Run with:
    PYTHONPATH=src pytest test/test_user_config.py
'''
import pytest

from ttboard.config.user_config import UserConfig


@pytest.fixture
def make_config(tmp_path):
    def _make(text: str) -> UserConfig:
        ini = tmp_path / 'config.ini'
        ini.write_text(text)
        return UserConfig(str(ini))
    return _make


def test_single_project_unchanged(make_config):
    conf = make_config('[DEFAULT]\nproject = tt_um_factory_test\n')
    assert conf.default_project == 'tt_um_factory_test'
    assert conf.default_projects == ['tt_um_factory_test']
    assert conf.switch_interval is None


def test_no_project(make_config):
    conf = make_config('[DEFAULT]\nmode = SAFE\n')
    assert conf.default_project is None
    assert conf.default_projects == []


def test_empty_project(make_config):
    conf = make_config('[DEFAULT]\nproject =\n')
    assert conf.default_project is None
    assert conf.default_projects == []


def test_project_list(make_config):
    conf = make_config('[DEFAULT]\n'
                       'project = tt_um_a, tt_um_b,tt_um_c ,\n'
                       'switch_interval = 15\n')
    assert conf.default_projects == ['tt_um_a', 'tt_um_b', 'tt_um_c']
    # first entry is what gets loaded at boot, and what older callers see
    assert conf.default_project == 'tt_um_a'
    assert conf.switch_interval == 15


def test_switch_interval_fractional(make_config):
    conf = make_config('[DEFAULT]\nproject = a, b\nswitch_interval = 2.5\n')
    assert conf.switch_interval == 2.5


def test_switch_interval_before_project(make_config):
    conf = make_config('[DEFAULT]\nswitch_interval = 30\nproject = a, b\n')
    assert conf.default_projects == ['a', 'b']
    assert conf.switch_interval == 30


def test_switch_interval_invalid(make_config):
    conf = make_config('[DEFAULT]\nproject = a, b\nswitch_interval = soon\n')
    assert conf.switch_interval is None
