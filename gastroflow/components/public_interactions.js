const publicInteractionStates = new WeakMap();

function attachPublicInteractions(root) {
  if (!root) return;
  let state = publicInteractionStates.get(root);
  if (!state) {
    state = {navigation: null, cart: null};
    publicInteractionStates.set(root, state);
  }
  const clear = (kind) => {
    const pending = state[kind];
    if (!pending) return;
    pending.element.removeAttribute("aria-busy");
    pending.element.removeAttribute("aria-disabled");
    pending.element.removeAttribute("data-public-busy");
    pending.element.style.removeProperty("opacity");
    pending.element.style.removeProperty("cursor");
    pending.status.remove();
    state[kind] = null;
  };
  const revision = (kind) => root.dataset[kind === "cart" ? "cartRevision" : "navigationRevision"];
  for (const kind of ["navigation", "cart"]) {
    if (state[kind] && state[kind].revision !== revision(kind)) clear(kind);
  }
  const block = (event) => {event.preventDefault(); event.stopImmediatePropagation();};
  const begin = (kind, element) => {
    const status = document.createElement("span");
    status.setAttribute("role", "status");
    status.textContent = kind === "cart" ? " Agregando al carrito…" : " Abriendo…";
    element.insertAdjacentElement("afterend", status);
    element.setAttribute("aria-busy", "true");
    element.setAttribute("aria-disabled", "true");
    element.dataset.publicBusy = "true";
    element.style.opacity = "0.65";
    element.style.cursor = "wait";
    state[kind] = {element, status, revision: revision(kind)};
  };
  const onMouseDown = (event) => {
    // Keep focus on the current input until navigation is dispatched. A blur
    // round trip must not rerender/move the target between mouse down and click.
    if (event.button === 0 && event.target.closest("button[data-public-navigation]")) event.preventDefault();
  };
  const onClick = (event) => {
    const step = event.target.closest("button[data-quantity-step]");
    if (step) {
      const form = step.closest("form");
      if (!form || state.cart) return block(event);
      const input = form.querySelector('[name="detail_quantity"]');
      const next = Math.max(1, (Number(input.value) || 1) + Number(step.dataset.quantityStep));
      input.value = String(next);
      form.querySelector("[data-quantity-display]").textContent = String(next);
      return;
    }
    const button = event.target.closest("button[data-public-navigation]");
    if (!button || button.disabled) return;
    if (state.navigation || state.cart) return block(event);
    begin("navigation", button);
  };
  const onSubmit = (event) => {
    if (!event.target.matches("form[data-public-cart-action]")) return;
    if (state.cart || state.navigation) return block(event);
    begin("cart", event.target.querySelector('button[type="submit"]'));
  };
  root.addEventListener("mousedown", onMouseDown, true);
  root.addEventListener("click", onClick, true);
  root.addEventListener("submit", onSubmit, true);
  return () => {
    root.removeEventListener("mousedown", onMouseDown, true);
    root.removeEventListener("click", onClick, true);
    root.removeEventListener("submit", onSubmit, true);
  };
}
