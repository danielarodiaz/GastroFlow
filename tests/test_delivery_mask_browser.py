"""Browser regression tests for the exact mask shipped in the public app.

Needs Playwright plus Chromium or Microsoft Edge. Backend-only environments skip
the browser tests; the component integration assertions always run.
"""

from pathlib import Path

import pytest

from gastroflow.components.delivery_input import MASK_SCRIPT, delivery_date_input, delivery_time_input
from gastroflow.states.public_order_state import PublicOrderState


def test_delivery_fields_keep_edits_in_the_browser_and_sync_only_on_blur():
    for create, name, handler in [
        (delivery_time_input, "horario_entrega", PublicOrderState.complete_delivery_time),
        (delivery_date_input, "fecha_entrega", PublicOrderState.complete_delivery_date),
    ]:
        field = create(name=name, default_value="", on_blur=handler)
        assert field.value is None
        assert "on_change" not in field.event_triggers
        assert "on_blur" in field.event_triggers
        assert MASK_SCRIPT in field._get_all_custom_code()
        hooks = list(field._get_all_hooks())
        assert any(f"attachDeliveryMask(ref_{name}.current" in str(hook) for hook in hooks)
        assert any("defaultValue" in prop for prop in field.render()["props"])
        with pytest.raises(ValueError, match="default_value"):
            create(name=name, value="2115")


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        if Path(runtime.chromium.executable_path).exists():
            instance = runtime.chromium.launch(headless=True)
        elif Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe").exists():
            instance = runtime.chromium.launch(channel="msedge", headless=True)
        else:
            pytest.skip("Install Playwright Chromium to run the browser mask tests.")
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.set_content("""
        <form>
          <label>Fecha<input name="fecha_entrega" type="text" inputmode="numeric" maxlength="10"></label>
          <label>Horario<input name="horario_entrega" type="text" inputmode="numeric" maxlength="5"></label>
          <button type="submit">Confirmar</button>
        </form>
    """)
    page.add_script_tag(content=MASK_SCRIPT)
    page.evaluate("""() => {
        window.blurs = [];
        const date = document.querySelector('[name="fecha_entrega"]');
        const time = document.querySelector('[name="horario_entrega"]');
        window.disposeDate = attachDeliveryMask(date, "date");
        window.disposeTime = attachDeliveryMask(time, "time");
        for (const input of [date, time]) {
            input.addEventListener('blur', () => window.blurs.push(input.value));
        }
        document.querySelector('form').addEventListener('submit', (event) => {
            event.preventDefault();
            window.submitted = Object.fromEntries(new FormData(event.target));
        });
    }""")
    yield page
    page.close()


@pytest.mark.parametrize("delay", [0, 80, 350])
def test_time_stays_formatted_while_typing_after_pause_and_after_blur(page, delay):
    field = page.locator('[name="horario_entrega"]')
    field.press_sequentially("2115", delay=delay)
    assert field.input_value() == "21:15"
    assert page.evaluate("window.blurs") == []
    page.wait_for_timeout(1200)
    assert field.input_value() == "21:15"
    page.locator('[name="fecha_entrega"]').focus()
    assert field.input_value() == "21:15"
    assert page.evaluate("window.blurs") == ["21:15"]
    # A stale default value or unrelated parent render cannot replace the edit.
    field.evaluate("input => {input.defaultValue = '2115'; window.disposeTime(); window.disposeTime = attachDeliveryMask(input, 'time');}")
    assert field.input_value() == "21:15"


def test_time_can_be_erased_replaced_and_submitted_without_blur(page):
    field = page.locator('[name="horario_entrega"]')
    field.fill("2115")
    assert field.input_value() == "21:15"
    for expected in ("21:1", "21", "2", ""):
        field.press("Backspace")
        assert field.input_value() == expected
    field.press_sequentially("0915")
    assert field.input_value() == "09:15"
    field.evaluate("input => input.setSelectionRange(4, 5)")
    field.press("2")
    assert field.input_value() == "09:12"
    field.press("Enter")
    assert page.evaluate("window.submitted.horario_entrega") == "09:12"
    assert page.evaluate("window.blurs") == []


def test_date_formats_locally_without_inserting_a_year_or_blocking_deletion(page):
    field = page.locator('[name="fecha_entrega"]')
    field.press_sequentially("1810", delay=80)
    assert field.input_value() == "18-10"
    page.wait_for_timeout(1200)
    assert field.input_value() == "18-10"
    field.fill("18012026")
    assert field.input_value() == "18-01-2026"
    for expected in ("18-01-202", "18-01-20", "18-01-2", "18-01", "18-0", "18", "1", ""):
        field.press("Backspace")
        assert field.input_value() == expected
    field.press_sequentially("1910")
    field.press("Enter")
    assert field.input_value() == "19-10"
    assert page.evaluate("window.submitted.fecha_entrega") == "19-10"


def test_deleting_next_to_separator_does_not_trap_cursor(page):
    field = page.locator('[name="horario_entrega"]')
    field.fill("2115")
    field.evaluate("input => input.setSelectionRange(3, 3)")
    field.press("Backspace")
    assert len(field.input_value().replace(":", "")) == 3
    field.press("ControlOrMeta+A")
    field.press("Backspace")
    assert field.input_value() == ""
