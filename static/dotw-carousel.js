/*
 * Designs of the Week — a merry-go-round coverflow.
 *
 * Up to four awarded designs ride a rotating stage. Only three are ever on the
 * front: the centre (sharp, and a click opens it) and its two blurred
 * neighbours; anything else is spun to the back seat and hidden. Advancing —
 * via the arrows, the arrow keys, or a click on a side card — swings every card
 * one seat along, so the whole thing reads as a carousel turning.
 *
 * Auto-rotate: advance every 10 seconds without repainting a countdown.
 * Hover, keyboard focus and hidden tabs pause the timer. Reduced motion
 * disables automatic rotation; manual navigation remains available.
 *
 * Enhancement only: the markup ships with the centre design already showing, so
 * a failed or slow script degrades to a single static card rather than nothing.
 * Reduced motion is honoured in CSS (the seats snap instead of swinging).
 */
(function () {
  const root = document.querySelector('[data-dotw-carousel]');
  if (!root) return;

  const cards = Array.from(root.querySelectorAll('[data-dotw-card]'));
  if (cards.length < 2) return; // a single award is just a static card

  const prev = root.querySelector('[data-dotw-prev]');
  const next = root.querySelector('[data-dotw-next]');
  const len = cards.length;

  const CYCLE_MS = 10000;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let index = cards.findIndex((c) => c.classList.contains('is-center'));
  if (index < 0) index = 0;

  let timer = null;
  let remaining = CYCLE_MS;
  let startedAt = 0;
  let hovered = root.matches(':hover');

  // Signed distance from the centre, wrapped so a card always takes the shortest
  // way round the ring: … -1 = left seat, 0 = centre, 1 = right seat, … The two
  // seats at ±1 are the blurred neighbours; every other card sits in the back.
  function seatOf(n) {
    let raw = (n - index + len) % len;
    if (raw > len / 2) raw -= len;
    if (raw === 0) return 'is-center';
    if (raw === -1) return 'is-left';
    if (raw === 1) return 'is-right';
    return 'is-back';
  }

  function render() {
    cards.forEach((card, n) => {
      const seat = seatOf(n);
      card.classList.remove('is-center', 'is-left', 'is-right', 'is-back');
      card.classList.add(seat);
      const front = seat === 'is-center';
      card.toggleAttribute('aria-hidden', !front);
      if (front) card.removeAttribute('tabindex');
      else card.setAttribute('tabindex', '-1');
    });
  }

  function show(i) {
    index = (i + len) % len;
    render();
    stopTimer();
    remaining = CYCLE_MS;
    schedule();
  }

  render();

  prev && prev.addEventListener('click', () => show(index - 1));
  next && next.addEventListener('click', () => show(index + 1));

  // A click on a side card rotates it to the centre instead of following its
  // link; the centre card follows its link to the design as normal.
  cards.forEach((card, n) => {
    card.addEventListener('click', (e) => {
      if (n !== index) { e.preventDefault(); show(n); }
    });
  });

  // Left/right keys turn the ring when the carousel (or a control) has focus.
  root.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { show(index - 1); e.preventDefault(); }
    else if (e.key === 'ArrowRight') { show(index + 1); e.preventDefault(); }
  });

  // One timeout per turn; nothing paints or runs continuously between turns.
  function stopTimer() {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
    remaining = Math.max(0, remaining - (performance.now() - startedAt));
  }

  function schedule() {
    if (timer !== null || hovered || root.contains(document.activeElement)
        || document.hidden || reduceMotion.matches) return;
    startedAt = performance.now();
    timer = setTimeout(() => {
      timer = null;
      show(index + 1);
    }, remaining);
  }

  root.addEventListener('pointerenter', () => { hovered = true; stopTimer(); });
  root.addEventListener('pointerleave', () => { hovered = false; schedule(); });
  root.addEventListener('focusin', stopTimer);
  root.addEventListener('focusout', (e) => {
    if (!root.contains(e.relatedTarget)) {
      // Wait until the browser updates activeElement after focusout.
      setTimeout(schedule, 0);
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopTimer();
    else schedule();
  });
  reduceMotion.addEventListener('change', () => {
    if (reduceMotion.matches) stopTimer();
    else schedule();
  });

  schedule();
})();
