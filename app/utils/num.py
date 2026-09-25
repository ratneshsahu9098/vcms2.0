"""Numeric parsing helpers (safe request-value coercion)."""


def to_float(raw, default=0.0):
    """Coerce a form/query value to float; empty, junk or NaN returns default."""
    if raw is None:
        return default
    if isinstance(raw, bool):
        return default
    if isinstance(raw, (int, float)):
        return float(raw) if raw == raw else default
    text = str(raw).strip().replace(",", "")
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        return default
    return value if value == value else default
