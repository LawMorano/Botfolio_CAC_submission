/* The "Reset viewer sequence": two clicks that tell the viewer which way a
 * model is actually facing.
 *
 * An STL records no axis convention whatsoever, and OBJ and GLB record
 * whichever one the exporter happened to use, so a design can arrive lying on
 * its side or standing on its nose with nothing in the file to say so. When
 * that happens the Front button shows an end cap, Top shows a flank, and there
 * is no angle the author can drag to that fixes it for the next visitor.
 *
 * The way out is to have someone who knows the part point out two of its faces.
 * A front and a top pin down the other four between them, so the sequence asks
 * for exactly those two and derives the rest — see orientationFromViews in
 * viewer.js for the arithmetic.
 *
 * Only the design's owner and admins can run it: the correction is stored on
 * the design and changes what every later visitor sees, which is also why the
 * button opens a screen explaining that rather than opening step one.
 *
 * On the design page all of this happens inside an open <dialog>. That rules
 * out a second dialog for the warning screen — showModal() puts only the
 * topmost dialog in the top layer and makes everything under it inert, which
 * would leave the model unrotatable during the very steps that ask the user to
 * rotate it — and it rules out a position:fixed overlay, which cannot paint
 * above a top-layer dialog at all. So the panel here is an absolutely
 * positioned child of the viewer's own container, which is inside whichever
 * dialog is open and therefore neither inert nor painted under it. The overlay
 * passes pointer events straight through except on the panel itself, so the
 * model stays draggable during both capture steps.
 */

const STEP_COPY = {
  front: {
    title: 'Step 1 of 2 — set the front',
    body: 'Turn the model until you are looking straight at the face you would call its front, then set it.',
    action: 'Set front',
  },
  top: {
    title: 'Step 2 of 2 — set the top',
    body: 'Now turn the model until you are looking straight down at its top, then set it.',
    action: 'Set top',
  },
};

/* Offered on the way out so the four sides nobody set by hand can be checked
 * rather than taken on trust — the whole claim of the sequence is that setting
 * two of these fixes all six. */
const DERIVED_VIEWS = [
  ['front', 'Front'], ['back', 'Back'], ['left', 'Left'],
  ['right', 'Right'], ['top', 'Top'], ['bottom', 'Bottom'],
];

let sequence = 0;

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};

/* Mount the sequence.
 *
 *   viewer     a ModelViewer with a model already loaded
 *   button     the trigger the page has already placed and styled
 *   host       the element the panel is drawn over. It needs a position other
 *              than static, which .viewer and .viewer-modal__shell both have
 *   save       async (cameraState) => void. Throw with a message the owner
 *              should read. Called once per completed sequence, per undo and
 *              per removal
 *   ownerName  the design's owner, when that is somebody other than whoever is
 *              looking at it, so an admin is told whose work they are changing
 *   coverHint  a sentence about the gallery picture, which the sequence does
 *              not re-render
 *
 * Returns { isActive, destroy }. isActive() lets the page keep Escape and a
 * stray backdrop click from closing the viewer out from under a half-finished
 * sequence; destroy() takes the panel away with the viewer.
 */
export function mountOrientationWizard({ viewer, button, host, save, ownerName, coverHint }) {
  if (!viewer || !button || !host) return { isActive: () => false, destroy() {} };

  const overlay = element('div', 'viewer-orient');
  overlay.hidden = true;

  const panel = element('div', 'viewer-orient__panel');
  panel.setAttribute('role', 'dialog');

  sequence += 1;
  const title = element('h3', 'viewer-orient__title');
  title.id = `viewer-orient-title-${sequence}`;
  panel.setAttribute('aria-labelledby', title.id);

  const body = element('p', 'viewer-orient__body');
  const note = element('p', 'viewer-orient__note');
  const message = element('p', 'viewer-orient__message');
  message.setAttribute('role', 'status');
  message.hidden = true;

  const sides = element('div', 'viewer-orient__sides');
  sides.hidden = true;
  for (const [view, label] of DERIVED_VIEWS) {
    const control = element('button', 'btn btn--quiet', label);
    control.type = 'button';
    control.addEventListener('click', () => viewer.setView(view));
    sides.append(control);
  }

  const actions = element('div', 'viewer-orient__actions');
  const cancel = element('button', 'btn btn--quiet', 'Cancel');
  cancel.type = 'button';
  const undo = element('button', 'btn btn--danger', 'Undo');
  undo.type = 'button';
  const confirm = element('button', 'btn btn--primary', 'Start');
  confirm.type = 'button';
  actions.append(cancel, undo, confirm);

  panel.append(title, body, note, message, sides, actions);
  overlay.append(panel);
  host.append(overlay);

  let step = null;
  let front = null;
  // What the design looked like before this run, so the completion step can put
  // it back. A front eyeballed slightly off is easy at a 45-degree field of
  // view, and without this the only way back would be to guess at the old
  // angles a second time.
  let previous = null;
  let busy = false;

  const setMessage = (text, kind) => {
    message.textContent = text || '';
    message.hidden = !text;
    message.classList.toggle('is-bad', kind === 'bad');
  };

  const close = () => {
    step = null;
    front = null;
    previous = null;
    overlay.hidden = true;
    overlay.classList.remove('viewer-orient--blocking');
    button.hidden = false;
    button.focus();
  };

  const render = () => {
    overlay.hidden = false;
    button.hidden = true;
    // Only the explanation and the result cover the model. The two capture
    // steps must leave it draggable, which is the whole point of them.
    overlay.classList.toggle('viewer-orient--blocking',
                             step === 'warning' || step === 'done');
    sides.hidden = step !== 'done';
    undo.hidden = !(
      (step === 'warning' && viewer.getModelOrientation())
      || (step === 'done' && previous !== undefined)
    );
    undo.textContent = step === 'done'
      ? 'Undo — put it back'
      : 'Remove the current correction';
    cancel.textContent = step === 'done' ? 'Close' : 'Cancel';
    confirm.disabled = busy;
    undo.disabled = busy;

    if (step === 'warning') {
      title.textContent = 'Reset viewer sequence';
      body.textContent =
        'This sets which way this model is facing for everyone who opens it, '
        + 'not just for you, and it replaces whatever orientation is saved now. '
        + 'You will be asked to turn the model to its front and set that, then '
        + 'to its top and set that. The back, left, right and bottom are worked '
        + 'out from those two, and the view buttons start showing the right faces.';
      note.textContent =
        (ownerName ? `This design belongs to ${ownerName}. ` : '')
        + 'All parts will be shown and any motion reset to the start before you '
        + 'begin. Nothing is saved until both steps are done, and you can run '
        + 'the sequence again or undo it afterwards. The model file itself is '
        + 'not changed.';
      confirm.textContent = 'Start the sequence';
      return;
    }

    if (step === 'done') {
      title.textContent = 'Orientation saved';
      body.textContent =
        'The front and top are set, and the other four sides follow from them. '
        + 'Check each one below — run the sequence again if any of them look wrong.';
      note.textContent = coverHint || '';
      confirm.textContent = 'Done';
      return;
    }

    const copy = STEP_COPY[step];
    title.textContent = copy.title;
    body.textContent = copy.body;
    note.textContent = 'Drag to rotate, scroll to zoom. The model stays where you leave it.';
    confirm.textContent = copy.action;
  };

  const open = (next) => {
    step = next;
    setMessage('');
    render();
    confirm.focus();
  };

  /* Both captures have to be judgements about the whole model at rest. An
   * isolated part means the user lines up that bracket's front rather than the
   * assembly's; a scrubbed clip means they line up an arm swung out to a pose
   * that does not exist when the page opens; and a panned orbit centre makes
   * "facing the camera" mean something other than "facing the model". */
  const settle = () => {
    viewer.showAllParts();
    if (viewer.hasAnimation()) {
      if (viewer.isPlaying()) viewer.togglePlay();
      viewer.seek(0);
    }
    viewer.recentre();
  };

  const store = async (state, working) => {
    busy = true;
    render();
    setMessage(working);
    try {
      await save(state);
    } catch (error) {
      busy = false;
      render();
      // The change is live in this viewer but was not stored. Saying "saved"
      // here would send the owner away believing the design is fixed for
      // everybody else too.
      setMessage(error.message || 'That could not be saved.', 'bad');
      return false;
    }
    busy = false;
    return true;
  };

  const finish = async () => {
    const top = viewer.viewDirection();
    if (!top) return setMessage('Move the camera off the model first.', 'bad');

    if (!viewer.reorient(front, top)) {
      // Keep the front already set: the common mistake is pressing "Set top"
      // after barely moving, and making them redo both steps for it would be
      // punishing.
      return setMessage(
        'That is nearly the same view as the front you set. Keep the front, '
        + 'rotate about a quarter turn so you are looking down at the top of '
        + 'the model, then press Set top again.', 'bad');
    }

    // Read the camera before the confirmation snap, not after: reorient() has
    // turned the saved angle along with the model so it still frames the same
    // part of it, and setView('front') would overwrite that with a face-on
    // view nobody chose.
    if (!await store(viewer.getCameraState(), 'Saving…')) return;
    viewer.setView('front');
    open('done');
  };

  confirm.addEventListener('click', async () => {
    if (busy) return;
    if (step === 'done') return close();
    if (step === 'warning') {
      previous = viewer.getModelOrientation();
      settle();
      return open('front');
    }

    const direction = viewer.viewDirection();
    if (!direction) return setMessage('Move the camera off the model first.', 'bad');

    if (step === 'front') {
      front = direction;
      return open('top');
    }
    await finish();
  });

  undo.addEventListener('click', async () => {
    if (busy) return;
    // From the warning screen this clears whatever is saved; from the
    // completion step it restores what was there when this run started, which
    // for a first run is the same thing.
    viewer.setModelOrientation(step === 'done' ? previous : null);
    viewer.resetView();
    if (!await store(viewer.getCameraState(), 'Putting it back…')) return;
    close();
  });

  cancel.addEventListener('click', () => {
    if (!busy) close();
  });

  const isActive = () => !overlay.hidden;

  const onKey = (event) => {
    if (event.key !== 'Escape' || !isActive() || busy) return;
    // The design page's viewer sits in a <dialog>, which closes itself on
    // Escape. While the sequence is open that key belongs to the sequence —
    // otherwise a stray press between the two steps takes the whole viewer
    // down and throws away the front the user has just lined up.
    event.preventDefault();
    event.stopPropagation();
    close();
  };
  document.addEventListener('keydown', onKey, true);

  button.addEventListener('click', () => open('warning'));

  return {
    isActive,
    destroy() {
      document.removeEventListener('keydown', onKey, true);
      overlay.remove();
    },
  };
}
