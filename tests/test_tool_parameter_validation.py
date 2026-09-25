from tools.param_utils import resolve_alias


def test_resolve_alias_prefers_top_level_then_nested_then_legacy_string():
    keys = ("query", "value")

    assert resolve_alias({"query": "top", "parametro": {"query": "nested"}}, keys) == "top"
    assert resolve_alias({"parametro": {"value": "nested"}}, keys) == "nested"
    assert resolve_alias({"parametro": "legacy"}, keys, allow_legacy_string=True) == "legacy"
    assert resolve_alias({"parametro": "legacy"}, keys, default="fallback") == "fallback"
