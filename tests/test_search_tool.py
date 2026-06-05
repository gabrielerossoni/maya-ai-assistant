import warnings

from tools.search_tool import SearchTool


class FakeDDGS:
    def __enter__(self):
        warnings.warn(
            "This package (`duckduckgo_search`) has been renamed to `ddgs`! Use `pip install ddgs`!",
            RuntimeWarning,
        )
        return self

    def __exit__(self, *_args):
        return False

    def text(self, *_args, **_kwargs):
        return [{"title": "Titolo", "body": "Corpo"}]


def test_search_tool_suppresses_duckduckgo_package_rename_warning(monkeypatch):
    monkeypatch.setattr("tools.search_tool.DDGS", FakeDDGS)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = SearchTool().execute({"query": "test"})

    assert result["status"] == "ok"
    assert caught == []
