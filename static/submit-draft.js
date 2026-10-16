/* Keeps what has been typed into the upload form across a reload.
 *
 * Publishing a design is a long form, and losing it to a stray Ctrl+R or a
 * closed tab is the kind of thing that stops someone bothering a second time.
 * The text of a whole form is tiny — under a kilobyte — so it lives in
 * localStorage and comes back on the next visit.
 *
 * What is deliberately NOT saved:
 *   the model and image files  a browser will not let script rebuild a File,
 *                              and a robot assembly can run to gigabytes
 *   preview_data_url           a 1024x768 JPEG data URL, well over a hundred
 *                              kilobytes and a hundred times the rest of the
 *                              draft put together, and meaningless once the
 *                              model it was rendered from is gone
 *   camera_json                describes a view of that same absent model
 *   model_upload_token         points at a quarantined upload that expires
 *   csrf_token                 issued per session; a stale one only fails
 *   upload_certification       a legal confirmation, re-affirmed every time
 *
 * That last one is not only legal hygiene: the checkbox gates the publish
 * button, so a restored form cannot be sent until someone reads it and ticks
 * the box, which is the moment they will notice the model is missing.
 *
 * This runs before the page's own module, so the archetype filter and the CAD
 * link toggle re-run over the restored values and heal anything stale.
 */
(() => {
  const form = document.getElementById('submit-form');
  if (!form) return;

  const STORAGE_KEY = 'botfolio-submit-draft';
  const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
  // Far more than a full form of text, far less than the ~5MB localStorage
  // gives an origin. A draft past this is a pasted novel, not a design.
  // Characters, not bytes: what storage counts is UTF-16 units.
  const MAX_DRAFT_CHARS = 256_000;
  const SAVE_DELAY_MS = 400;

  const SKIP_NAMES = new Set(['csrf_token', 'upload_certification']);
  const SKIP_TYPES = new Set(['file', 'hidden', 'password', 'submit', 'button', 'reset']);

  // The form is rendered per account, so a draft from whoever used this
  // browser last must not surface under someone else's name.
  const owner = form.dataset.draftOwner || '';

  const savable = () => [...form.elements].filter((field) => (
    field.name && !SKIP_NAMES.has(field.name) && !SKIP_TYPES.has(field.type)
  ));

  const valueOf = (field) => (
    field.type === 'checkbox' || field.type === 'radio'
      ? (field.checked ? field.value : '')
      : field.value
  );

  function initialValueOf(field) {
    // A select has no defaultValue — that property belongs to inputs and
    // textareas. Reading it anyway makes every pre-selected dropdown look
    // edited, so an admin's "Individual" attribution or a ?season= link would
    // save a draft of an untouched form and then announce it on every visit.
    if (field.tagName === 'SELECT') {
      const preselected = [...field.options].find((option) => option.defaultSelected);
      return preselected ? preselected.value : '';
    }
    if (field.type === 'checkbox' || field.type === 'radio') {
      return field.defaultChecked ? field.value : '';
    }
    return field.defaultValue;
  }

  // The page wires its dropdowns together with change handlers, so a value put
  // there by script has to say so: the admin team fields stay hidden and the
  // archetype list stays unfiltered otherwise.
  function announceChange(fields) {
    for (const field of fields) {
      field.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }

  function read() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    } catch (error) {
      return null; /* Private mode, or a draft from an older shape. */
    }
  }

  function clear() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      /* Storage disabled — there was nothing saved to remove. */
    }
  }

  function save() {
    // Values are grouped by name because the contributor rows repeat theirs,
    // and are restored in the same document order they were collected.
    const values = {};
    let filled = false;
    for (const field of savable()) {
      const value = valueOf(field);
      (values[field.name] ||= []).push(value);
      if (value && value !== initialValueOf(field)) filled = true;
    }
    if (!filled) {
      clear();
      return;
    }
    const payload = JSON.stringify({owner, saved: Date.now(), values});
    if (payload.length > MAX_DRAFT_CHARS) return;
    try {
      localStorage.setItem(STORAGE_KEY, payload);
    } catch (error) {
      clear(); /* Quota, private mode — drop it rather than half-write. */
    }
  }

  function restore(draft) {
    const queues = {};
    for (const [name, list] of Object.entries(draft.values)) queues[name] = [...list];
    const changed = [];
    for (const field of savable()) {
      const queue = queues[field.name];
      if (!queue || !queue.length) continue;
      const value = queue.shift();
      if (field.type === 'checkbox' || field.type === 'radio') {
        field.checked = value === field.value;
      } else if (field.tagName === 'SELECT'
                 && ![...field.options].some((option) => option.value === value)) {
        continue; /* The season or team is gone; leave the default showing. */
      } else {
        field.value = value;
      }
      if (value) changed.push(field);
    }
    announceChange(changed);
    return changed.length;
  }

  function announce() {
    const notice = document.createElement('p');
    notice.className = 'note draft-notice';
    // Say what did not come back as well as what did. The files are the one
    // part of the form a browser will not let script hand back.
    notice.textContent = 'Restored what you had typed here earlier. '
      + 'Add the model and pictures again before publishing. ';
    const discard = document.createElement('button');
    discard.type = 'button';
    discard.className = 'text-button';
    discard.textContent = 'Start fresh';
    discard.addEventListener('click', () => {
      // Not location.reload(): a reload is exactly what a browser repopulates
      // form fields after, so the discarded answers would walk straight back
      // in, with the draft now gone and the button no longer able to help.
      clear();
      form.reset();
      announceChange(savable());
      notice.remove();
    });
    notice.append(discard);
    form.prepend(notice);
  }

  const draft = read();
  if (draft && draft.values && draft.owner === owner
      && Date.now() - draft.saved < MAX_AGE_MS) {
    if (restore(draft)) announce();
  } else if (draft) {
    clear(); /* Expired, or belongs to another account on this browser. */
  }

  let timer;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(save, SAVE_DELAY_MS);
  };
  const flush = () => {
    clearTimeout(timer);
    save();
  };
  form.addEventListener('input', schedule);
  form.addEventListener('change', schedule);

  // The debounce is a bet on the tab still being there in 400ms, so settle it
  // on the way out. pagehide covers closing and navigating away;
  // visibilitychange is the one a phone actually fires when it is swiped away.
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });

  // Once the design is live the draft is only in the way. The page announces
  // success by revealing the "view your design" link rather than navigating.
  new MutationObserver(() => {
    if (document.getElementById('upload-page')?.classList.contains('is-complete')) {
      clearTimeout(timer);
      clear();
    }
  }).observe(document.getElementById('upload-page') || form,
             {attributes: true, attributeFilter: ['class']});
})();
