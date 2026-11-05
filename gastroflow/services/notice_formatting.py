"""Limited rich text shared by the editor preview and public notice dialog."""

from html import escape
from html.parser import HTMLParser
import re

TAGS = {"p", "div", "span", "br", "strong", "b", "em", "i", "u", "s", "h2", "h3", "ul", "ol", "li"}
STYLE_VALUES = {
    "text-align": r"left|center|right|justify",
    "color": r"#[0-9a-fA-F]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)",
    "font-family": r"Arial|Georgia|Courier New|sans-serif|serif|monospace",
    "font-size": r"(?:12|14|16|18|20|24|28|32|36|48)px",
    "font-weight": r"bold|normal|[1-9]00",
    "font-style": r"italic|normal",
    "text-decoration": r"underline|line-through|none",
    "text-decoration-line": r"underline|line-through|none",
}


class NoticeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.text = []
        self.stack = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "svg", "math"}:
            self.blocked += 1
            return
        if self.blocked or tag not in TAGS:
            return
        styles = []
        for name, value in attrs:
            if name == "style" and value:
                for declaration in value.split(";"):
                    key, _, content = declaration.partition(":")
                    key, content = key.strip().lower(), content.strip().strip("\"'")
                    pattern = STYLE_VALUES.get(key)
                    if pattern and re.fullmatch(pattern, content, re.I):
                        styles.append(f"{key}:{content}")
        attribute = f' style="{escape(";".join(styles), quote=True)}"' if styles else ""
        self.output.append(f"<{tag}{attribute}>")
        if tag == "br":
            self.text.append("\n")
        else:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object", "svg", "math"}:
            self.blocked = max(0, self.blocked - 1)
            return
        if self.blocked or tag not in self.stack:
            return
        while self.stack:
            closed = self.stack.pop()
            self.output.append(f"</{closed}>")
            if closed in {"p", "div", "h2", "h3", "li"}:
                self.text.append("\n")
            if closed == tag:
                break

    def handle_data(self, data):
        if not self.blocked:
            self.output.append(escape(data))
            self.text.append(data)


def clean_notice_html(value: str) -> tuple[str, str]:
    parser = NoticeHTML()
    parser.feed(value)
    parser.close()
    while parser.stack:
        parser.output.append(f"</{parser.stack.pop()}>")
    return "".join(parser.output), "".join(parser.text).replace("\xa0", " ").strip()


def notice_html(row: dict) -> str:
    if row.get("mensaje_html"):
        return clean_notice_html(row["mensaje_html"])[0]
    return "<p>" + escape(row.get("mensaje", "")).replace("\n", "<br>") + "</p>"
