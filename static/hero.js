/* Hero enhancement: a living gradient mesh behind the landing copy.
 *
 * The base theme already gives the high tier a drifting aurora + the three.js
 * globe. This adds two things on top, and only when they're worth it (full tier,
 * motion welcome, a real pointer, and anime.js present):
 *
 *   1. A gradient MESH of independent colour blobs, each wandering on its own
 *      eased loop via anime.js — organic in a way a single keyframe can't be.
 *   2. POINTER PARALLAX: the mesh and the globe drift a few pixels against the
 *      cursor at different depths, so the scene reacts to the reader.
 *
 * It's purely decorative and fully progressive: if anything here is missing or
 * throws, the CSS aurora stays exactly as it was — nothing regresses.
 */
(() => {
  const root = document.documentElement;
  const hero = document.querySelector('.hero');
  const mesh = hero?.querySelector('[data-hero-mesh]');
  if (!hero || !mesh) return;

  const finePointer = matchMedia('(pointer: fine)').matches;
  const motionOK = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (root.dataset.perf !== 'high' || !motionOK) return;

  const blobs = [...mesh.querySelectorAll('i')];
  const globe = hero.querySelector('[data-hero-parallax]');

  // anime.js is a plain global (vendored UMD). Without it we still light up the
  // mesh (CSS gives it a static look); we just skip the wandering drift.
  const anime = window.anime;
  if (anime && blobs.length) {
    blobs.forEach((blob, i) => {
      anime({
        targets: blob,
        translateX: () => [anime.random(-30, 30), anime.random(-40, 40)],
        translateY: () => [anime.random(-24, 24), anime.random(-34, 34)],
        scale: () => [anime.random(92, 108) / 100, anime.random(96, 118) / 100],
        duration: () => anime.random(7000, 12000),
        easing: 'easeInOutSine',
        direction: 'alternate',
        loop: true,
        delay: i * 350,
      });
    });
  }

  // Turn the mesh on (this also hides the plain aurora, see enhance.css), only
  // now that we know the mesh will actually be driven.
  hero.classList.add('hero-mesh-on');

  /* ---- Pointer parallax (fine pointers only; touch keeps the idle drift) ---- */
  if (!finePointer) return;

  let raf = 0;
  let targetX = 0;
  let targetY = 0;
  let curX = 0;
  let curY = 0;

  const frame = () => {
    // Ease toward the pointer target so motion stays smooth, not jittery.
    curX += (targetX - curX) * 0.08;
    curY += (targetY - curY) * 0.08;
    mesh.style.transform = `translate3d(${curX * 26}px, ${curY * 20}px, 0)`;
    if (globe) globe.style.transform = `translate3d(${curX * -16}px, ${curY * -12}px, 0)`;
    if (Math.abs(targetX - curX) > 0.001 || Math.abs(targetY - curY) > 0.001) {
      raf = requestAnimationFrame(frame);
    } else {
      raf = 0;
    }
  };
  const kick = () => {
    if (!raf) raf = requestAnimationFrame(frame);
  };

  hero.addEventListener('pointermove', (event) => {
    const rect = hero.getBoundingClientRect();
    targetX = (event.clientX - rect.left) / rect.width - 0.5;
    targetY = (event.clientY - rect.top) / rect.height - 0.5;
    kick();
  });
  hero.addEventListener('pointerleave', () => {
    targetX = 0;
    targetY = 0;
    kick();
  });
})();
