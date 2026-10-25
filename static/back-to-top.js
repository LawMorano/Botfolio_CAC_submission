/* Show the back-to-top control after scrolling down the page. */
(() => {
  const button = document.querySelector('[data-to-top]');
  if (!button) return;

  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const threshold = 600;
  let ticking = false;

  const update = () => {
    ticking = false;
    const show = window.scrollY > threshold;
    button.hidden = !show;
    button.classList.toggle('is-visible', show);
  };

  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(update);
  }, { passive: true });

  button.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
  });

  update();
})();
