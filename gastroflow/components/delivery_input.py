"""Uncontrolled inputs: format immediately in the browser, sync only on blur.

Form submission reads their current DOM values, even before a blur event arrives.
No state update can replace an in-progress edit with a delayed server response.
"""

from pathlib import Path
from typing import ClassVar

from reflex.components.el.elements.forms import Input

MASK_SCRIPT = Path(__file__).with_name("delivery_mask.js").read_text(encoding="utf-8")


class DeliveryInput(Input):
    mask_kind: ClassVar[str] = "time"

    @classmethod
    def create(cls, *children, **props):
        if "value" in props or "on_change" in props:
            raise ValueError("Delivery inputs use default_value and synchronize on_blur only.")
        props.setdefault("id", props.get("name"))
        if not props.get("id"):
            raise ValueError("Delivery inputs require a stable id or name.")
        props.setdefault("type", "text")
        props.setdefault("input_mode", "numeric")
        props.setdefault("auto_complete", "off")
        return super().create(*children, **props)

    def add_imports(self):
        return {"react": ["useEffect"]}

    def add_custom_code(self):
        return [MASK_SCRIPT]

    def add_hooks(self):
        # Run after each render: the cart form itself is conditionally mounted.
        return [f'useEffect(() => attachDeliveryMask({self.get_ref()}.current, "{self.mask_kind}"));']


class DeliveryDateInput(DeliveryInput):
    mask_kind: ClassVar[str] = "date"


delivery_date_input = DeliveryDateInput.create
delivery_time_input = DeliveryInput.create
