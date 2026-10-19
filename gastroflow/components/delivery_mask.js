function formatDeliveryDigits(value, kind) {
  const digits = value.replace(/\D/g, "").slice(0, kind === "date" ? 8 : 4);
  if (digits.length <= 2) return digits;
  if (kind === "time") return digits.slice(0, 2) + ":" + digits.slice(2);
  if (digits.length <= 4) return digits.slice(0, 2) + "-" + digits.slice(2);
  return digits.slice(0, 2) + "-" + digits.slice(2, 4) + "-" + digits.slice(4);
}

function attachDeliveryMask(input, kind) {
  if (!input) return;
  let before = null;
  let composing = false;
  const digits = (value) => value.replace(/\D/g, "");
  const caretAfterDigits = (value, count) => {
    if (count === 0) return 0;
    let seen = 0;
    for (let index = 0; index < value.length; index++) {
      if (/\d/.test(value[index]) && ++seen === count) return index + 1;
    }
    return value.length;
  };
  const remember = (event) => {
    before = { value: input.value, start: input.selectionStart, end: input.selectionEnd, type: event.inputType };
  };
  const mask = (event) => {
    if (composing || event?.isComposing) return;
    let raw = input.value;
    let start = digits(raw.slice(0, input.selectionStart ?? raw.length)).length;
    let end = digits(raw.slice(0, input.selectionEnd ?? raw.length)).length;
    // Deleting a separator must not restore it forever and trap the cursor.
    if (before && before.start === before.end && digits(before.value) === digits(raw)) {
      const position = digits(before.value.slice(0, before.start)).length;
      if (before.type === "deleteContentBackward" && position > 0) {
        raw = digits(raw).slice(0, position - 1) + digits(raw).slice(position);
        start = end = position - 1;
      } else if (before.type === "deleteContentForward") {
        raw = digits(raw).slice(0, position) + digits(raw).slice(position + 1);
        start = end = position;
      }
    }
    const formatted = formatDeliveryDigits(raw, kind);
    if (input.value !== formatted) {
      input.value = formatted;
      input.setSelectionRange(caretAfterDigits(formatted, start), caretAfterDigits(formatted, end));
    }
    before = null;
  };
  const startComposition = () => { composing = true; };
  const finishComposition = () => { composing = false; mask(); };
  const normalize = () => { before = null; mask(); };
  input.addEventListener("beforeinput", remember);
  input.addEventListener("input", mask);
  input.addEventListener("compositionstart", startComposition);
  input.addEventListener("compositionend", finishComposition);
  input.addEventListener("blur", normalize);
  const form = input.form;
  form?.addEventListener("submit", normalize, true);
  normalize();
  return () => {
    input.removeEventListener("beforeinput", remember);
    input.removeEventListener("input", mask);
    input.removeEventListener("compositionstart", startComposition);
    input.removeEventListener("compositionend", finishComposition);
    input.removeEventListener("blur", normalize);
    form?.removeEventListener("submit", normalize, true);
  };
}
