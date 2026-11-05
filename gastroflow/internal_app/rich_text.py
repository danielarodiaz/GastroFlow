"""Small bundled rich-text editor; no external assets or services."""

from pathlib import Path

from streamlit.components.v1 import declare_component

_editor = declare_component("notice_rich_text", path=str(Path(__file__).with_name("rich_text_editor")))


def rich_text_editor(initial_html: str, key: str) -> str:
    result = _editor(initial_html=initial_html, key=key, default={"html": initial_html})
    return str((result or {}).get("html", initial_html))
