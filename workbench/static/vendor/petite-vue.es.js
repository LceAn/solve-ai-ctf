/* CTF Workbench — CSP-safe Petite-Vue bundle wrapper
 *
 * petite-vue-csp (the CSP-safe fork of petite-vue) expects the reactivity core
 * to be injected at call time: createApp({ reactive, effect, remove, stop }, data).
 * It does NOT bundle or export reactive() itself.
 *
 * This wrapper wires @vue/reactivity (also CSP-safe: no new Function, no eval)
 * into petite-vue-csp and re-exports { createApp, reactive, nextTick } so consumer
 * modules can use the same import surface as the standard petite-vue package.
 *
 * Vendored files (all local, CSP script-src 'self' compatible):
 *   ./vue-reactivity.es.js  — @vue/reactivity v3 ESM browser build (exports reactive/effect/stop/...)
 *   ./petite-vue-csp.es.js  — petite-vue-csp ESM build (exports createApp/nextTick, uses CSP-safe expression parser instead of new Function)
 */
import { reactive, effect, stop } from "./vue-reactivity.es.js";
import { createApp as _createApp, nextTick } from "./petite-vue-csp.es.js";

/* remove(arr, el) — splice-based removal, mirrors @vue/shared remove() used by
 * petite-vue's internal block/effect cleanup. Inlined here to avoid vendoring
 * the entire @vue/shared package for one trivial function. */
function remove(arr, el) {
  const i = arr.indexOf(el);
  if (i > -1) arr.splice(i, 1);
}

/* Wire the reactivity core into petite-vue-csp's createApp.
 * petite-vue-csp signature: createApp(imports, initialData?) where imports
 * must provide { reactive, effect, remove, stop }. The standard petite-vue
 * package bundles this wiring internally; the CSP fork leaves it to the caller. */
function createApp(initialData) {
  return _createApp({ reactive, effect, remove, stop }, initialData);
}

export { createApp, reactive, nextTick };
