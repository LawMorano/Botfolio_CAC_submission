/* Wires the "Visual detail" toggle in the footer.
 *
 * The tier itself is decided before first paint by an inline script in
 * base.html; this only reflects the current choice and lets the user change it.
 * Auto  -> forget the override, fall back to capability detection.
 * Full  -> force the high tier.
 * Lite  -> force the low tier.
 * Changing it reloads so heavy modules (e.g. the hero globe) re-decide cleanly.
 */
(() => {
  const toggle = document.querySelector('[data-perf-toggle]');
  if (!toggle) return;

  const mode = document.documentElement.dataset.perfMode || 'auto';
  toggle.querySelectorAll('[data-perf-set]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.perfSet === mode));
    button.addEventListener('click', () => {
      try {
        if (button.dataset.perfSet === 'auto') localStorage.removeItem('botfolio-perf');
        else localStorage.setItem('botfolio-perf', button.dataset.perfSet);
      } catch (error) {
        /* Private mode / storage disabled — nothing we can persist. */
      }
      location.reload();
    });
  });
})();
