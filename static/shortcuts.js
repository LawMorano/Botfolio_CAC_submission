/* Keyboard shortcuts.
 *
 *   /            focus the topbar search
 *   g then g/t/x/h   go to Gallery / Teams / Tags / Home
 *   ?            open the shortcuts help overlay
 *   Esc          close the help overlay
 *   Ctrl/⌘ + K   command palette (owned by command-palette.js)
 *
 * Single-key shortcuts never fire while the reader is typing in a field or when
 * a modal is open, so they can't hijack real input. Destinations are read from
 * the nav in the DOM rather than hard-coded, so they follow the routes.
 */
(() => {
  const searchInput = document.getElementById('global-search-input');
  const overlay = document.querySelector('[data-shortcuts]');

  // Build the "g" jump table from the links already in the page, so URLs stay
  // in lockstep with Flask's routes without duplicating them here.
  const byText = {};
  document.querySelectorAll('.topbar__nav a').forEach((link) => {
    byText[link.textContent.trim().toLowerCase()] = link.href;
  });
  const brand = document.querySelector('.brand');
  const jumps = {
    g: byText.gallery,
    t: byText.teams,
    x: byText.tags,
    h: brand ? brand.href : '/',
  };

  const isTyping = () => {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    return (
      tag === 'INPUT' ||
      tag === 'TEXTAREA' ||
      tag === 'SELECT' ||
      el.isContentEditable
    );
  };

  const paletteOpen = () => {
    const cmdk = document.querySelector('[data-cmdk]');
    return cmdk && !cmdk.hidden;
  };

  function openOverlay() {
    if (!overlay) return;
    overlay.hidden = false;
    void overlay.offsetWidth;
    overlay.classList.add('is-open');
  }
  function closeOverlay() {
    if (!overlay || overlay.hidden) return;
    overlay.classList.remove('is-open');
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      overlay.hidden = true;
    } else {
      const done = () => {
        overlay.hidden = true;
        overlay.removeEventListener('transitionend', done);
      };
      overlay.addEventListener('transitionend', done);
      setTimeout(done, 260);
    }
  }
  const overlayOpen = () => overlay && !overlay.hidden;

  overlay?.querySelectorAll('[data-shortcuts-dismiss]').forEach((el) =>
    el.addEventListener('click', closeOverlay),
  );

  let awaitingJump = false;
  let jumpTimer = null;
  const armJump = () => {
    awaitingJump = true;
    clearTimeout(jumpTimer);
    jumpTimer = setTimeout(() => {
      awaitingJump = false;
    }, 1200);
  };

  document.addEventListener('keydown', (event) => {
    // Esc closes the help overlay (the palette handles its own Esc).
    if (event.key === 'Escape' && overlayOpen()) {
      event.preventDefault();
      closeOverlay();
      return;
    }

    // Never steal keys while typing, mid-chord with a modifier, or over a modal.
    if (isTyping() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (paletteOpen() || overlayOpen()) return;

    if (awaitingJump) {
      const url = jumps[event.key.toLowerCase()];
      awaitingJump = false;
      clearTimeout(jumpTimer);
      if (url) {
        event.preventDefault();
        window.location.href = url;
      }
      return;
    }

    if (event.key === '/') {
      if (!searchInput) return;
      event.preventDefault();
      searchInput.focus({ preventScroll: true });
      searchInput.select?.();
    } else if (event.key === '?') {
      event.preventDefault();
      openOverlay();
    } else if (event.key === 'g' || event.key === 'G') {
      armJump();
    }
  });
})();
