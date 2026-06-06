"""Shared helpers for tool action parameter resolution."""


def _present(value) -> bool:
    return value is not None and str(value).strip() != ""


def resolve_alias(
    action: dict,
    keys: tuple[str, ...],
    *,
    nested_key: str = "parametro",
    default=None,
    allow_legacy_string: bool = False,
):
    """Resolve a tool parameter by priority: top-level keys, nested legacy dict, legacy string."""
    for key in keys:
        value = action.get(key)
        if _present(value):
            return value

    nested = action.get(nested_key)
    if isinstance(nested, dict):
        for key in keys:
            value = nested.get(key)
            if _present(value):
                return value

    if allow_legacy_string and isinstance(nested, str) and nested.strip():
        return nested

    return default
