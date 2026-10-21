// Keep one tracker and one ordered list across layouts. Without JS it stays open.
(() => {
  const tracker = document.querySelector('.academy__tracker');
  if (!tracker) return;
  const compact = window.matchMedia('(max-width: 800px)');
  const sync = () => { tracker.open = !compact.matches; };
  sync();
  compact.addEventListener('change', sync);
})();
