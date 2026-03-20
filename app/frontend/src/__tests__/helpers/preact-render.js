/**
 * Minimal Preact render/cleanup helper for vitest + happy-dom.
 *
 * Renders a component into a detached container and provides cleanup
 * to unmount between tests.
 */
import { h, render as preactRender } from "preact";

let container = null;

/**
 * Render a Preact component into the DOM.
 * @param {Function} Component - Preact component function
 * @param {Object} [props] - Props to pass
 * @returns {HTMLElement} The container element
 */
export function render(Component, props = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  preactRender(h(Component, props), container);
  return container;
}

/**
 * Unmount the rendered component and remove the container.
 */
export function cleanup() {
  if (container) {
    preactRender(null, container);
    container.remove();
    container = null;
  }
}
