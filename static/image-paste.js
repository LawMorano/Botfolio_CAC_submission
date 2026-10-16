/*
 * Shared image picker + clipboard paste, used by both upload forms.
 *
 * A native <input type="file"> throws away its whole selection every time the
 * picker reopens, and it can't take a Ctrl+V screenshot at all. This wires an
 * input so repeated picks accumulate, a pasted screenshot (Snipping Tool, or
 * any clipboard image) is added as a real file, and both honour the same
 * 8-image / 8 MB / PNG-JPG-WebP limits the server enforces. It keeps
 * input.files in sync through a DataTransfer, so the ordinary form submit
 * carries exactly what the list shows — no extra field, no server change.
 */

const MAX_IMAGES = 8;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;                 // matches the server
const ALLOWED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

const imageKey = (file) => `${file.name}:${file.size}:${file.lastModified}`;

// Clipboard images arrive as nameless blobs, so give each a real filename with
// the right extension — the server derives the type from it.
function pastedImageName(type) {
  const ext = type === 'image/jpeg' ? 'jpg' : type === 'image/webp' ? 'webp' : 'png';
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return `screenshot-${stamp}-${Math.random().toString(36).slice(2, 6)}.${ext}`;
}

export function initImagePaste({ input, summary, count, list, clearButton, status }) {
  if (!input) return null;
  let selected = [];

  let statusTimer;
  const announce = (message) => {
    if (!status) return;
    status.textContent = message;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => { status.textContent = ''; }, 6000);
  };

  function sync() {
    const transfer = new DataTransfer();
    selected.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    if (summary) summary.hidden = selected.length === 0;
    if (count) count.textContent = `${selected.length} of ${MAX_IMAGES} images selected`;
    if (!list) return;
    list.replaceChildren();
    selected.forEach((file, index) => {
      const item = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = file.name;
      const remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'text-button'; remove.textContent = 'Remove';
      remove.addEventListener('click', () => { selected.splice(index, 1); sync(); });
      item.append(name, remove); list.appendChild(item);
    });
  }

  // Add Files from any source — the picker or a clipboard paste — honouring the
  // cap and skipping duplicates, oversized files, and unsupported types.
  // Reports what it skipped so callers can explain it.
  function addFiles(files) {
    const known = new Set(selected.map(imageKey));
    const skipped = { full: false, tooBig: false, badType: false };
    let added = 0;
    for (const file of files) {
      if (selected.length >= MAX_IMAGES) { skipped.full = true; break; }
      if (file.type && !ALLOWED_IMAGE_TYPES.has(file.type)) { skipped.badType = true; continue; }
      if (file.size > MAX_IMAGE_BYTES) { skipped.tooBig = true; continue; }
      const key = imageKey(file);
      if (known.has(key)) continue;
      selected.push(file); known.add(key); added += 1;
    }
    sync();
    return { added, skipped };
  }

  input.addEventListener('change', () => { addFiles(input.files); });
  if (clearButton) clearButton.addEventListener('click', () => { selected = []; sync(); });

  document.addEventListener('paste', (event) => {
    const items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    let sawImage = false, sawBadType = false;
    const images = [];
    for (const item of items) {
      if (item.kind !== 'file' || !item.type.startsWith('image/')) continue;
      sawImage = true;
      const blob = item.getAsFile();
      if (!blob) continue;
      if (!ALLOWED_IMAGE_TYPES.has(blob.type)) { sawBadType = true; continue; }
      images.push(new File([blob], pastedImageName(blob.type), { type: blob.type }));
    }
    if (!sawImage) return;                     // ordinary text paste — leave it alone
    event.preventDefault();                    // an image paste is meant for us
    if (!images.length) {
      announce(sawBadType ? 'Pasted images must be PNG, JPG, or WebP.' : 'Could not read that image.');
      return;
    }
    const { added, skipped } = addFiles(images);
    if (added) announce(`${added} screenshot${added === 1 ? '' : 's'} added.`);
    else if (skipped.full) announce(`You already have ${MAX_IMAGES} images — remove one first.`);
    else if (skipped.tooBig) announce('That screenshot is larger than 8 MB.');
    else announce('That screenshot is already added.');
  });

  sync();
  return { addFiles };
}
