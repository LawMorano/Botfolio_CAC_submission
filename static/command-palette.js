/* Command palette (⌘K / Ctrl-K).
 *
 * A keyboard-first way to search the whole site from anywhere. It reuses the
 * same grouped-results endpoint as the topbar search (global_search_api), so
 * results stay identical — this is a faster door to the same room.
 *
 * A utility, not decoration: it loads on every tier. The only motion is the
 * open/close transition, which style.css drops under reduced motion.
 *
 * Exposes window.botfolioCmdk = { open, close, toggle } so shortcuts.js and any
 * other trigger can drive it without re-implementing the modal.
 */
(() => {
  const root = document.querySelector('[data-cmdk]');
  if (!root) return;

  const input = root.querySelector('.cmdk__input');
  const results = root.querySelector('.cmdk__results');
  const dialog = root.querySelector('.cmdk__dialog');
  const endpoint = root.dataset.searchEndpoint;
  const searchPage = root.dataset.searchPage || '';
  const MIN_QUERY = 2;
  const DEBOUNCE_MS = 160;

  let timer = null;
  let controller = null;
  let activeIndex = -1;
  let lastFocused = null;

  const options = () => [...results.querySelectorAll('[role="option"]')];

  const isOpen = () => !root.hidden;

  function open() {
    if (isOpen()) return;
    lastFocused = document.activeElement;
    root.hidden = false;
    // Force a reflow so the CSS enter transition runs from the hidden state.
    void root.offsetWidth;
    root.classList.add('is-open');
    document.documentElement.classList.add('cmdk-open');
    input.value = '';
    results.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
    input.focus();
  }

  function close() {
    if (!isOpen()) return;
    root.classList.remove('is-open');
    document.documentElement.classList.remove('cmdk-open');
    controller?.abort();
    clearTimeout(timer);
    activeIndex = -1;
    // Wait out the fade before hiding so the exit transition is visible.
    const done = () => {
      root.hidden = true;
      root.removeEventListener('transitionend', done);
    };
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      root.hidden = true;
    } else {
      root.addEventListener('transitionend', done);
      // Fallback in case transitionend never fires (e.g. display quirks).
      setTimeout(done, 260);
    }
    if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  }

  const toggle = () => (isOpen() ? close() : open());

  function setActive(index) {
    const items = options();
    if (!items.length) {
      activeIndex = -1;
      return;
    }
    activeIndex = (index + items.length) % items.length;
    items.forEach((item, i) => item.classList.toggle('is-active', i === activeIndex));
    const active = items[activeIndex];
    input.setAttribute('aria-activedescendant', active.id);
    active.scrollIntoView({ block: 'nearest' });
  }

  function renderEmpty(message) {
    results.replaceChildren();
    const empty = document.createElement('p');
    empty.className = 'cmdk__empty';
    empty.textContent = message;
    results.append(empty);
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    activeIndex = -1;
  }

  function render(data) {
    results.replaceChildren();
    activeIndex = -1;
    const groups = (data.groups || []).filter((group) => group.items?.length);
    if (!groups.length) {
      renderEmpty(`No matches for “${data.query}”.`);
      return;
    }
    let optionIndex = 0;
    groups.forEach((group) => {
      const section = document.createElement('section');
      section.className = 'cmdk__group';
      const heading = document.createElement('h2');
      heading.textContent = group.label;
      section.append(heading);
      group.items.forEach((item) => {
        const link = document.createElement('a');
        link.id = `cmdk-option-${optionIndex++}`;
        link.href = item.url;
        link.className = 'cmdk__option';
        link.setAttribute('role', 'option');
        const title = document.createElement('strong');
        title.textContent = item.title;
        if (item.badge) {
          const tag = document.createElement('span');
          tag.className = 'registry-tag';
          tag.textContent = item.badge;
          title.append(tag);
        }
        link.append(title);
        if (item.subtitle) {
          const subtitle = document.createElement('span');
          subtitle.textContent = item.subtitle;
          link.append(subtitle);
        }
        section.append(link);
      });
      results.append(section);
    });
    if (searchPage) {
      const all = document.createElement('a');
      all.className = 'cmdk__all';
      all.href = `${searchPage}?q=${encodeURIComponent(data.query)}`;
      all.setAttribute('role', 'option');
      all.id = `cmdk-option-${optionIndex++}`;
      all.textContent = `View all results for “${data.query}”`;
      results.append(all);
    }
    input.setAttribute('aria-expanded', 'true');
  }

  async function search() {
    const query = input.value.trim();
    if (query.length < MIN_QUERY) {
      renderEmpty('Type to search designs, people, teams, tags and pages…');
      return;
    }
    controller?.abort();
    controller = new AbortController();
    try {
      const response = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`, {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('Search unavailable');
      const data = await response.json();
      if (input.value.trim() === data.query) render(data);
    } catch (error) {
      if (error.name !== 'AbortError') renderEmpty('Search is unavailable right now.');
    }
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(search, DEBOUNCE_MS);
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive(activeIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive(activeIndex - 1);
    } else if (event.key === 'Enter') {
      const active = options()[activeIndex];
      if (active) {
        event.preventDefault();
        active.click();
      }
    }
  });

  // Pointer hover should track the active option so mouse and keyboard agree.
  results.addEventListener('mousemove', (event) => {
    const option = event.target.closest('[role="option"]');
    if (!option) return;
    const index = options().indexOf(option);
    if (index >= 0 && index !== activeIndex) setActive(index);
  });

  root.querySelectorAll('[data-cmdk-dismiss]').forEach((el) =>
    el.addEventListener('click', close),
  );

  // Focus trap + global close, scoped to when the palette is open.
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab' || !isOpen()) return;
    const focusables = dialog.querySelectorAll(
      'a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])',
    );
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  // The ⌘K / Ctrl-K global shortcut. Works even from inside a text field.
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && (event.key === 'k' || event.key === 'K')) {
      event.preventDefault();
      toggle();
    }
  });

  window.botfolioCmdk = { open, close, toggle };
})();
