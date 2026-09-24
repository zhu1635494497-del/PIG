from __future__ import annotations

import unicodedata


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def safe_display_name(value: str) -> str:
    cleaned = "".join(
        "\ufffd"
        if unicodedata.category(character) in {"Cc", "Cf"}
        else character
        for character in value
    )
    return cleaned or "(unnamed)"


def logical_segment(value: str) -> str:
    cleaned = safe_display_name(value)
    escaped = cleaned.replace("%", "%25").replace("!", "%21")
    escaped = escaped.replace("/", "%2F").replace("\\", "%5C")
    if escaped in {".", ".."}:
        escaped = escaped.replace(".", "%2E")
    return escaped


def folder_child_path(parent: str, original_name: str) -> str:
    return f"{parent.rstrip('/')}/{logical_segment(original_name)}"


def archive_child_path(parent: str, safe_parts: tuple[str, ...]) -> str:
    suffix = "/".join(logical_segment(part) for part in safe_parts)
    return f"{parent}!/{suffix}"


def blocked_archive_child_path(parent: str, original_name: str) -> str:
    return f"{parent}!/{logical_segment(original_name)}"


def safe_filesystem_segment(display_name: str, *, maximum: int = 180) -> str:
    """Create one friendly cross-Windows filesystem segment."""

    normalized = unicodedata.normalize("NFC", safe_display_name(display_name))
    cleaned = "".join(
        "_" if character in '<>:"/\\|?*' else character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf"}
    ).strip(" .")
    cleaned = cleaned[:maximum].rstrip(" .") or "file"
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def safe_working_filename(display_name: str, trusted_suffix: str) -> str:
    """Create a friendly Windows-safe basename under a generated Item directory."""

    if not trusted_suffix.startswith("."):
        raise ValueError("trusted_suffix must start with a dot")
    cleaned = safe_filesystem_segment(display_name)
    suffix = trusted_suffix.lower()
    stem = cleaned[: -len(suffix)] if cleaned.lower().endswith(suffix) else cleaned
    maximum_stem_length = max(1, 180 - len(suffix))
    stem = stem[:maximum_stem_length].rstrip(" .") or "file"
    return f"{stem}{suffix}"
