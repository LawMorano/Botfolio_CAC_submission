/* Exercise static/submit-draft.js against a stubbed DOM, no browser needed.
 *
 * The stubs are deliberately picky about the ways a real form differs from an
 * object literal: a select carries no defaultValue, only its options know what
 * the server pre-selected, and setting .value by hand fires no change event.
 * Getting any of those wrong here would certify a bug as passing.
 *
 * Run directly (`node tests/submit_draft_harness.mjs`) or through
 * tests/test_submit_draft.py, which reports the failures as unittest ones.
 */
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SOURCE = process.argv[2]
  || fileURLToPath(new URL('../static/submit-draft.js', import.meta.url));
const CODE = readFileSync(SOURCE, 'utf8');

/* --- the smallest DOM the script actually touches ----------------------- */

class Field {
  constructor({name, type = 'text', value = '', options = null,
               tagName = 'INPUT', preselected = null, defaultChecked = false}) {
    this.name = name;
    this.type = type;
    this.tagName = options ? 'SELECT' : tagName;
    this.checked = defaultChecked;
    this.defaultChecked = defaultChecked;
    this.dispatched = [];
    if (options) {
      // A real select has no defaultValue at all. Only the options carry
      // defaultSelected, which is what the "selected" attribute renders to.
      this.options = options.map((option) => (
        {value: option, defaultSelected: option === preselected}
      ));
      this.value = preselected || '';
    } else {
      this.value = value;
      this.defaultValue = value;
    }
    this.initial = this.value;
  }

  dispatchEvent(event) { this.dispatched.push(event.type); }

  reset() {
    this.value = this.initial;
    this.checked = this.defaultChecked;
  }
}

function makeForm(fields, owner = '7') {
  const listeners = {};
  return {
    id: 'submit-form',
    dataset: {draftOwner: owner},
    elements: fields,
    classList: {contains: () => false},
    addEventListener(kind, fn) { (listeners[kind] ||= []).push(fn); },
    prepend(node) { this.prepended = node; },
    reset() { fields.forEach((field) => field.reset()); this.wasReset = true; },
    fire(kind) { (listeners[kind] || []).forEach((fn) => fn()); },
  };
}

function install(form, store) {
  const timers = new Map();
  const page = {};
  let nextTimer = 1;
  const sandbox = {};
  sandbox.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      if (store.__throw) throw new Error('QuotaExceededError');
      store[k] = String(v);
    },
    removeItem: (k) => { delete store[k]; },
  };
  sandbox.Event = class { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } };
  sandbox.document = {
    visibilityState: 'visible',
    getElementById: (id) => (id === 'submit-form' ? form : null),
    createElement: () => ({
      className: '', textContent: '', type: '',
      addEventListener(kind, fn) { if (kind === 'click') this.click = fn; },
      append(child) { this.child = child; },
      remove() { this.removed = true; },
    }),
    addEventListener(kind, fn) { (page[kind] ||= []).push(fn); },
  };
  sandbox.window = {addEventListener(kind, fn) { (page[kind] ||= []).push(fn); }};
  sandbox.MutationObserver = class { observe() {} };
  sandbox.location = {reload() { sandbox.location.reloaded = true; }};
  sandbox.setTimeout = (fn) => { const id = nextTimer++; timers.set(id, fn); return id; };
  sandbox.clearTimeout = (id) => timers.delete(id);
  sandbox.Date = Date;
  sandbox.JSON = JSON;
  sandbox.Set = Set;
  sandbox.Object = Object;
  return {
    sandbox,
    flush: () => { for (const fn of timers.values()) fn(); timers.clear(); },
    page: (kind) => (page[kind] || []).forEach((fn) => fn()),
  };
}

function run(fields, store, owner = '7') {
  const form = makeForm(fields, owner);
  const {sandbox, flush, page} = install(form, store);
  // A fresh execution per case. The script is an IIFE, so importing it twice
  // would hand back the cached module and never re-run it.
  vm.runInNewContext(CODE, vm.createContext(sandbox), {filename: SOURCE});
  return {form, flush, page, sandbox};
}

const KEY = 'botfolio-submit-draft';
const results = [];
const test = (name, fn) => {
  try { fn(); results.push(['PASS', name]); }
  catch (error) { results.push(['FAIL', `${name}\n    ${error.message}`]); }
};

const sample = () => [
  new Field({name: 'csrf_token', type: 'hidden', value: 'secret-token'}),
  new Field({name: 'preview_data_url', type: 'hidden', value: 'data:image/jpeg;base64,AAAA'}),
  new Field({name: 'model_file', type: 'file'}),
  new Field({name: 'title'}),
  new Field({name: 'description', tagName: 'TEXTAREA'}),
  new Field({name: 'season_id', options: ['', '1', '2']}),
  new Field({name: 'contributor_username'}),
  new Field({name: 'contributor_username'}),
  new Field({name: 'upload_certification', type: 'checkbox', value: 'accepted'}),
];

// What an admin sees: a dropdown the server rendered with a real option already
// chosen, next to the number field it reveals.
const adminSample = () => [
  ...sample(),
  new Field({name: 'admin_attribution', options: ['individual', 'team'],
             preselected: 'individual'}),
  new Field({name: 'admin_team_number', type: 'number'}),
];

test('a filled form is saved, and weighs almost nothing', () => {
  const fields = sample();
  const store = {};
  const {form, flush} = run(fields, store);
  fields[3].value = 'Swerve drive bracket';
  fields[4].value = 'A drivetrain part.'.repeat(40);
  fields[5].value = '2';
  fields[6].value = 'ada';
  form.fire('input');
  flush();
  assert.ok(store[KEY], 'nothing was saved');
  const saved = JSON.parse(store[KEY]);
  assert.equal(saved.values.title[0], 'Swerve drive bracket');
  assert.equal(saved.values.season_id[0], '2');
  console.log(`    draft size: ${store[KEY].length} characters`);
  assert.ok(store[KEY].length < 4000, `draft too big: ${store[KEY].length}`);
});

test('the excluded fields never reach storage', () => {
  const fields = sample();
  const store = {};
  const {form, flush} = run(fields, store);
  fields[3].value = 'Bracket';
  fields[8].checked = true;
  form.fire('input');
  flush();
  const saved = JSON.parse(store[KEY]);
  for (const banned of ['csrf_token', 'preview_data_url', 'model_file', 'upload_certification']) {
    assert.ok(!(banned in saved.values), `${banned} was saved`);
  }
  assert.ok(!store[KEY].includes('secret-token'), 'the CSRF token leaked into storage');
  assert.ok(!store[KEY].includes('base64'), 'the preview image leaked into storage');
});

test('an untouched form saves nothing at all', () => {
  const store = {};
  const {form, flush} = run(sample(), store);
  form.fire('input');
  flush();
  assert.equal(store[KEY], undefined, 'an empty form wrote a draft');
});

test('a dropdown the server pre-selected is not mistaken for typing', () => {
  // An admin form arrives with Attribution already on "Individual". Reading a
  // select's non-existent defaultValue would make that look like an edit, and
  // every later visit would announce a restored draft over a blank form.
  const store = {};
  const {form, flush} = run(adminSample(), store);
  form.fire('input');
  flush();
  assert.equal(store[KEY], undefined, 'a pre-selected dropdown wrote a draft');
});

test('a dropdown moved off its pre-selected value is saved', () => {
  const fields = adminSample();
  const store = {};
  const {form, flush} = run(fields, store);
  fields[9].value = 'team';
  form.fire('change');
  flush();
  assert.equal(JSON.parse(store[KEY]).values.admin_attribution[0], 'team');
});

test('a saved draft comes back on the next load', () => {
  const store = {};
  const first = run(sample(), store);
  first.form.elements[3].value = 'Swerve bracket';
  first.form.elements[6].value = 'ada';
  first.form.elements[7].value = 'grace';
  first.form.fire('input');
  first.flush();

  const fresh = sample();
  const second = run(fresh, store);
  assert.equal(fresh[3].value, 'Swerve bracket');
  assert.equal(fresh[6].value, 'ada', 'first contributor row lost');
  assert.equal(fresh[7].value, 'grace', 'repeated field names got crossed');
  assert.ok(second.form.prepended, 'the user was not told a draft was restored');
});

test('a restored field tells the page it changed', () => {
  // The page hides the admin team number until Attribution says "team", and
  // filters the archetype list by season, both on change. A value set by
  // script fires nothing on its own, so the script has to say so itself.
  const store = {[KEY]: JSON.stringify({
    owner: '7', saved: Date.now(),
    values: {title: ['Bracket'], admin_attribution: ['team']},
  })};
  const fields = adminSample();
  run(fields, store);
  assert.equal(fields[9].value, 'team');
  assert.ok(fields[9].dispatched.includes('change'),
            'the attribution dropdown was moved in silence');
});

test('the certification checkbox is never re-ticked', () => {
  const store = {[KEY]: JSON.stringify({
    owner: '7', saved: Date.now(),
    values: {title: ['Bracket'], upload_certification: ['accepted']},
  })};
  const fields = sample();
  run(fields, store);
  assert.equal(fields[8].checked, false, 'a legal confirmation was restored');
  assert.equal(fields[3].value, 'Bracket');
});

test('start fresh empties the form instead of reloading it', () => {
  // A reload is precisely what a browser repopulates form fields after, so
  // reloading would hand back the answers the user just asked to discard.
  const store = {[KEY]: JSON.stringify({
    owner: '7', saved: Date.now(), values: {title: ['Bracket'], contributor_username: ['ada']},
  })};
  const fields = sample();
  const {form, sandbox} = run(fields, store);
  form.prepended.child.click();   // the "Start fresh" button inside the notice
  assert.equal(store[KEY], undefined, 'the draft survived start fresh');
  assert.equal(fields[3].value, '', 'the form still holds the discarded title');
  assert.ok(!sandbox.location.reloaded, 'start fresh reloaded the page');
  assert.ok(form.prepended.removed, 'the restored notice was left on screen');
});

test("another account's draft is discarded, not shown", () => {
  const store = {[KEY]: JSON.stringify({
    owner: '99', saved: Date.now(), values: {title: ['Someone elses secret']},
  })};
  const fields = sample();
  const {form} = run(fields, store, '7');
  assert.equal(fields[3].value, '');
  assert.equal(store[KEY], undefined, 'the other account draft was left behind');
  assert.ok(!form.prepended, 'claimed to restore a draft it refused');
});

test('a draft older than a week is dropped', () => {
  const eightDays = Date.now() - 8 * 24 * 60 * 60 * 1000;
  const store = {[KEY]: JSON.stringify({
    owner: '7', saved: eightDays, values: {title: ['Stale']},
  })};
  const fields = sample();
  run(fields, store);
  assert.equal(fields[3].value, '');
  assert.equal(store[KEY], undefined);
});

test('a season that no longer exists leaves the default showing', () => {
  const store = {[KEY]: JSON.stringify({
    owner: '7', saved: Date.now(), values: {title: ['Bracket'], season_id: ['404']},
  })};
  const fields = sample();
  run(fields, store);
  assert.equal(fields[5].value, '', 'a removed season was forced into the select');
  assert.equal(fields[3].value, 'Bracket', 'one bad field discarded the rest');
});

test('a closing tab is not left to the debounce', () => {
  const fields = sample();
  const store = {};
  const {form, page} = run(fields, store);
  fields[3].value = 'Typed and closed';
  form.fire('input');       // schedules a save 400ms out that will never fire
  page('pagehide');
  assert.equal(JSON.parse(store[KEY]).values.title[0], 'Typed and closed');
});

test('a backgrounded tab saves too', () => {
  const fields = sample();
  const store = {};
  const {form, page, sandbox} = run(fields, store);
  fields[3].value = 'Swiped away';
  form.fire('input');
  sandbox.document.visibilityState = 'hidden';
  page('visibilitychange');
  assert.equal(JSON.parse(store[KEY]).values.title[0], 'Swiped away');
});

test('storage being unavailable is survivable', () => {
  const store = {__throw: true};
  const fields = sample();
  const {form, flush} = run(fields, store);
  fields[3].value = 'Bracket';
  form.fire('input');
  flush();
  assert.ok(true, 'no exception escaped');
});

test('corrupt stored JSON does not break the page', () => {
  const store = {[KEY]: '{not json'};
  const fields = sample();
  run(fields, store);
  assert.equal(fields[3].value, '');
});

let failed = 0;
for (const [state, name] of results) {
  console.log(`${state}  ${name}`);
  if (state === 'FAIL') failed += 1;
}
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
