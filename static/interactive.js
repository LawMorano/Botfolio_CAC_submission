/* Pointer-tracking card glow — a "full tier" flourish.
 *
 * Only runs when the high visual tier is active and the device has a fine
 * pointer, so low-end, mobile, and touch devices never pay for it. It feeds the
 * --mx/--my custom properties that enhance.css reads to place a soft accent
 * glow under the cursor. No-op everywhere else.
 */
(() => {
  const root = document.documentElement;
  if (root.dataset.perf !== 'high') return;
  if (!window.matchMedia || matchMedia('(pointer: fine)').matches === false) return;

  const track = (element) => {
    element.addEventListener('pointermove', (event) => {
      const rect = element.getBoundingClientRect();
      element.style.setProperty('--mx', `${((event.clientX - rect.left) / rect.width) * 100}%`);
      element.style.setProperty('--my', `${((event.clientY - rect.top) / rect.height) * 100}%`);
    });
  };

  document.querySelectorAll('.card, [data-glow]').forEach(track);
})();
