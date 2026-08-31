"""Tests for recall/scripts/log_telemetry.py pure parsers."""
import importlib.util
import os

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "log_telemetry.py")
_spec = importlib.util.spec_from_file_location("log_telemetry", _SCRIPT)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)


def test_parse_bool_truthy():
    for s in ("true", "1", "yes", "y", "TRUE", " Yes ", "Y"):
        assert _m._parse_bool(s) is True, s


def test_parse_bool_falsy():
    for s in ("false", "0", "no", "n", "", "  ", "maybe", "2"):
        assert _m._parse_bool(s) is False, s


def test_parse_slots_basic():
    assert _m._parse_slots("1,2,3") == [1, 2, 3]


def test_parse_slots_strips_whitespace():
    assert _m._parse_slots(" 1 , 2 ,3 ") == [1, 2, 3]


def test_parse_slots_drops_below_one_and_nonint():
    # 0 is below the 1-indexed floor; 'a' is non-int -> both skipped.
    assert _m._parse_slots("0,1,a,2") == [1, 2]


def test_parse_slots_empty():
    assert _m._parse_slots("") == []
    assert _m._parse_slots("   ") == []
    assert _m._parse_slots(None) == []
