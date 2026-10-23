"""Immediate quantity controls and feedback while server navigation is pending."""

from pathlib import Path

from reflex.components.el.elements.typography import Div

INTERACTIONS_SCRIPT = Path(__file__).with_name("public_interactions.js").read_text(encoding="utf-8")


class PublicInteractions(Div):
    def add_imports(self):
        return {"react": ["useEffect"]}

    def add_custom_code(self):
        return [INTERACTIONS_SCRIPT]

    def add_hooks(self):
        return [f"useEffect(() => attachPublicInteractions({self.get_ref()}.current));"]


public_interactions = PublicInteractions.create
