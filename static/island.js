/* Scroll-reactive chrome: the dynamic-island topbar, the back-to-top button,
 * and the reading-progress bar. They share one rAF-throttled scroll pass so the
 * page only measures layout once per frame.
 *
 * Tiering, per piece:
 *   - Island morph  — high tier + motion only. Elsewhere reveal.js's quieter
 *                     `is-stuck` shadow still does its job and the bar stays put.
 *   - Back-to-top   — every tier (a utility, not a flourish); it just skips the
 *                     smooth-scroll animation under reduced motion.
 *   - Reading bar   — high tier + motion only (purely decorative).
 */
(() => {
  const root = document.documentElement;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const highTier = root.dataset.perf === 'high';
  const motionOK = highTier && !reduceMotion;

  const bar = document.querySelector('.topbar');
  const toTop = document.querySelector('[data-to-top]');
  const progressFill = document.querySelector('[data-reading-progress] .reading-progress__fill');

  const ISLAND_THRESHOLD = 240; // px scrolled before the bar condenses
  const TOTOP_THRESHOLD = 600; // px scrolled before back-to-top appears

  /* ---- Island morph (high tier + motion, IntersectionObserver) ---- */
  if (bar && motionOK && 'IntersectionObserver' in window) {
    // Purely a class toggle: every visual change (width, padding, radius, the
    // search shrink, the collapsing wordmark) is a CSS transition, so the morph
    // stays smooth and nothing re-renders. The placeholder is left untouched.
    const setIsland = (on) => {
      if (bar.classList.contains('is-island') === on) return;
      bar.classList.toggle('is-island', on);
    };
    const sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    sentinel.style.cssText =
      `position:absolute;top:${ISLAND_THRESHOLD}px;left:0;width:1px;height:1px;pointer-events:none`;
    document.body.prepend(sentinel);
    new IntersectionObserver(([entry]) => {
      const passed = !entry.isIntersecting && entry.boundingClientRect.top < 0;
      setIsland(passed);
    }).observe(sentinel);
  }

  /* ---- Reading progress + back-to-top (shared rAF scroll pass) ---- */
  const progressActive = progressFill && motionOK;
  if (progressActive) root.classList.add('has-reading-progress');

  const needScroll = progressActive || toTop;
  if (needScroll) {
    let ticking = false;

    const measure = () => {
      ticking = false;
      const doc = document.documentElement;
      const scrollTop = window.scrollY || doc.scrollTop;

      if (progressActive) {
        const max = doc.scrollHeight - doc.clientHeight;
        const ratio = max > 0 ? Math.min(scrollTop / max, 1) : 0;
        progressFill.style.transform = `scaleX(${ratio})`;
      }
      if (toTop) {
        const show = scrollTop > TOTOP_THRESHOLD;
        if (show === toTop.hidden) {
          toTop.hidden = !show;
          toTop.classList.toggle('is-visible', show);
        }
      }
    };

    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(measure);
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    measure(); // set initial state (e.g. reloaded mid-page)
  }

  if (toTop) {
    toTop.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
    });
  }
})();
