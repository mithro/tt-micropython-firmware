'''
Tests for the minimal ini parser used by config.ini.

Run with:
    PYTHONPATH=src pytest test/test_config_parser.py
'''
import io

from ttboard.config.parser import ConfigParser


def parse(text: str) -> ConfigParser:
    conf = ConfigParser()
    conf.read(fp=io.StringIO(text))
    return conf


def test_basic_types():
    conf = parse('[DEFAULT]\n'
                 'project = tt_um_factory_test\n'
                 'start_in_reset = no\n'
                 'rp_clock_frequency = 125e6\n'
                 'ui_in = 0b11001000\n'
                 'uio_oe_pico = 0xff\n'
                 'clock_frequency = 10\n')
    assert conf.get('DEFAULT', 'project') == 'tt_um_factory_test'
    assert conf.get('DEFAULT', 'start_in_reset') is False
    assert conf.get('DEFAULT', 'rp_clock_frequency') == 125e6
    assert conf.get('DEFAULT', 'ui_in') == 0b11001000
    assert conf.get('DEFAULT', 'uio_oe_pico') == 0xff
    assert conf.get('DEFAULT', 'clock_frequency') == 10


def test_option_name_prefix_of_earlier_option():
    # 'project' is a prefix of 'project_extra'; when the longer name
    # comes first the shorter option must still get its own value.
    conf = parse('[DEFAULT]\n'
                 'project_extra = 15\n'
                 'project = tt_um_a\n')
    assert conf.get('DEFAULT', 'project') == 'tt_um_a'
    assert conf.get('DEFAULT', 'project_extra') == 15


def test_option_name_prefix_of_later_option():
    conf = parse('[DEFAULT]\n'
                 'project = tt_um_a\n'
                 'project_extra = 15\n')
    assert conf.get('DEFAULT', 'project') == 'tt_um_a'
    assert conf.get('DEFAULT', 'project_extra') == 15


def test_comma_list_stays_a_string():
    conf = parse('[DEFAULT]\n'
                 'project = tt_um_a, tt_um_b,tt_um_c\n')
    assert conf.get('DEFAULT', 'project') == 'tt_um_a, tt_um_b,tt_um_c'


def test_trailing_comment_stripped():
    conf = parse('[DEFAULT]\n'
                 'project = tt_um_a, tt_um_b # two projects\n')
    assert conf.get('DEFAULT', 'project') == 'tt_um_a, tt_um_b'


def test_commented_out_option_ignored():
    conf = parse('[DEFAULT]\n'
                 '# project = tt_um_old\n'
                 'project = tt_um_new\n')
    assert conf.get('DEFAULT', 'project') == 'tt_um_new'
