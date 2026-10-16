(() => {
  const form = document.querySelector('[data-global-search]');
  if (!form) return;

  const input = form.querySelector('input[type="search"]');
  const results = form.querySelector('.global-search__results');
  const endpoint = form.dataset.searchEndpoint;
  let timer = null;
  let controller = null;
  let activeIndex = -1;

  const options = () => [...results.querySelectorAll('[role="option"]')];
  const close = () => {
    results.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    activeIndex = -1;
  };

  const setActive = (index) => {
    const items = options();
    if (!items.length) return;
    activeIndex = (index + items.length) % items.length;
    items.forEach((item, itemIndex) => item.classList.toggle('is-active', itemIndex === activeIndex));
    const active = items[activeIndex];
    input.setAttribute('aria-activedescendant', active.id);
    active.scrollIntoView({block: 'nearest'});
  };

  const render = (data) => {
    results.replaceChildren();
    activeIndex = -1;
    const groups = (data.groups || []).filter((group) => group.items?.length);
    if (!groups.length) {
      const empty = document.createElement('p');
      empty.className = 'global-search__empty';
      empty.textContent = `No matches for “${data.query}”.`;
      results.append(empty);
    } else {
      let optionIndex = 0;
      groups.forEach((group) => {
        const section = document.createElement('section');
        section.className = 'global-search__group';
        const heading = document.createElement('h2');
        heading.textContent = group.label;
        section.append(heading);
        group.items.forEach((item) => {
          const link = document.createElement('a');
          link.id = `global-search-option-${optionIndex++}`;
          link.href = item.url;
          link.setAttribute('role', 'option');
          const title = document.createElement('strong');
          title.textContent = item.title;
          if (item.badge) {
            const tag = document.createElement('span');
            tag.className = 'registry-tag';
            tag.textContent = item.badge;
            title.append(tag);
          }
          const subtitle = document.createElement('span');
          subtitle.textContent = item.subtitle;
          link.append(title, subtitle);
          section.append(link);
        });
        results.append(section);
      });
      const allResults = document.createElement('a');
      allResults.className = 'global-search__all';
      allResults.href = `${form.action}?q=${encodeURIComponent(data.query)}`;
      allResults.textContent = `View all results for “${data.query}”`;
      results.append(allResults);
    }
    results.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  const search = async () => {
    const query = input.value.trim();
    if (query.length < 2) {
      close();
      return;
    }
    controller?.abort();
    controller = new AbortController();
    try {
      const response = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`, {
        headers: {'Accept': 'application/json'}, signal: controller.signal,
      });
      if (!response.ok) throw new Error('Search unavailable');
      const data = await response.json();
      if (input.value.trim() === data.query) render(data);
    } catch (error) {
      if (error.name !== 'AbortError') close();
    }
  };

  // The search field lives in the sticky top bar, so it stays pinned near the
  // top of the viewport at any scroll offset. The page's `scroll-padding-top`
  // makes the browser treat it as "clipped" behind that padding and scroll the
  // page toward the top trying to clear it — which it never can, so the page
  // creeps upward. This fires not just on focus but on every keystroke, as the
  // browser re-scrolls the caret into view against that padding. Hold the scroll
  // padding at zero for the whole time the field is focused so the browser sees
  // it as already in view and leaves the page where it is; restore on blur.
  const html = document.documentElement;
  let previousPadding = null;
  const suppressFocusScroll = () => {
    if (previousPadding !== null) return;
    previousPadding = html.style.scrollPaddingTop;
    html.style.scrollPaddingTop = '0px';
  };
  const restoreFocusScroll = () => {
    if (previousPadding === null) return;
    html.style.scrollPaddingTop = previousPadding;
    previousPadding = null;
  };
  input.addEventListener('pointerdown', suppressFocusScroll);
  input.addEventListener('focus', suppressFocusScroll);
  input.addEventListener('blur', restoreFocusScroll);

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(search, 180);
  });
  input.addEventListener('focus', () => {
    if (input.value.trim().length >= 2) search();
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (results.hidden) search(); else setActive(activeIndex + 1);
    } else if (event.key === 'ArrowUp' && !results.hidden) {
      event.preventDefault(); setActive(activeIndex - 1);
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault(); options()[activeIndex].click();
    } else if (event.key === 'Escape') {
      close(); input.blur();
    }
  });
  document.addEventListener('click', (event) => {
    if (!form.contains(event.target)) close();
  });
})();
