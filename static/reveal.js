/*
 * Scroll-in reveals.
 *
 * The hidden state lives in style.css under `html.reveal-on`, which the inline
 * script in base.html sets before the first paint. All this file does is
 * decide when each element has earned its `.is-revealed`. If it never loads,
 * or throws, the safety net at the bottom still shows everything.
 */

/* Must stay in step with the `html.reveal-on :is(...)` list in style.css.
   Anything here that is not there simply will not animate; anything there but
   not here would stay invisible, which is why the two are kept adjacent. */
const REVEAL_SELECTOR = [
  '.hero__copy > *',
  '.hero__preview',
  '.section-head',
  '.grid > *',
  '.how__steps > li',
  '.two-col > *',
  '.scores > *',
  '.panel',
  '.detail-card',
  '.ai-assistant',
  '.contact-card',
  '.discord-card',
  '.profile-hero',
  '.taglist__item',
  '.comment',
  '.note',
  '.empty',
  '.table tbody tr',
].join(',');

// Siblings come in one after another. Capped so a long gallery page does not
// end up with a two-second wait on its last card.
const STAGGER_MS = 70;
const MAX_STEPS = 6;

/* Start before the element is fully on screen, so by the time the reader's eye
   arrives the movement is already finished. */
const OBSERVER_OPTIONS = { rootMargin: '0px 0px -8% 0px', threshold: 0.01 };

function revealAll(root = document) {
  for (const el of root.querySelectorAll(REVEAL_SELECTOR)) el.classList.add('is-revealed');
}

function mountReveals() {
  const elements = [...document.querySelectorAll(REVEAL_SELECTOR)];
  if (!elements.length) return;

  // Stagger runs per parent, so two grids side by side each start from zero
  // rather than the second one waiting out the first.
  const seen = new Map();
  for (const el of elements) {
    const index = seen.get(el.parentElement) ?? 0;
    seen.set(el.parentElement, index + 1);
    el.style.setProperty('--reveal-delay', `${Math.min(index, MAX_STEPS) * STAGGER_MS}ms`);
  }

  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('is-revealed');
      // One-way: scrolling back up should not replay it.
      observer.unobserve(entry.target);
    }
  }, OBSERVER_OPTIONS);

  for (const el of elements) observer.observe(el);
}

function start() {
  // reveal-on is only set when motion is welcome and the APIs exist; without it
  // nothing is hidden in the first place and there is nothing to do.
  if (!document.documentElement.classList.contains('reveal-on')) return;

  try {
    mountReveals();
  } catch (err) {
    // Never let a failure here leave the page blank.
    revealAll();
    throw err;
  }

  // Backstop for anything the observer never reports on — an element inside a
  // scroll container it cannot see, a browser that fires nothing on a hidden
  // tab. Cheap insurance against a page that stays empty.
  setTimeout(revealAll, 3000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start, { once: true });
} else {
  start();
}
