/* Drive the real static/viewer.js with the real vendored three.js and the real
 * OrbitControls, and check the camera can never be scrolled or panned into a
 * view where the model is not on screen.
 *
 * Only the two WebGL-bound classes are replaced. That matters: the bug this
 * guards against lived in OrbitControls' own arithmetic, so a hand-written
 * stand-in for the controls would have happily passed while the shipped viewer
 * still froze. The shims are written to a temporary directory and the two real
 * sources are copied there with their bare "three" specifier rewritten, since
 * outside a browser there is no import map to resolve it.
 *
 * Run directly (`node tests/viewer_orbit_harness.mjs`) or through
 * tests/test_viewer_orbit.py, which reports the failures as unittest ones.
 */
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const REPO = fileURLToPath(new URL('..', import.meta.url));
const SOURCE = process.argv[2] || path.join(REPO, 'static/viewer.js');
const VENDOR = path.join(REPO, 'static/vendor/three');

const shims = mkdtempSync(path.join(tmpdir(), 'botfolio-viewer-'));

/* An `export *` re-export is shadowed by an explicit local export of the same
 * name, so naming these two swaps them out while every other three.js export
 * stays the genuine article. */
writeFileSync(path.join(shims, 'three.mjs'), `
export * from ${JSON.stringify(pathToFileURL(path.join(VENDOR, 'three.module.js')).href)};

export class WebGLRenderer {
  constructor() {
    this._ratio = 1;
    this._width = 0;
    this._height = 0;
    this.frames = 0;
    this.domElement = canvas();
  }
  setPixelRatio(value) { this._ratio = value; }
  getPixelRatio() { return this._ratio; }
  setSize(w, h) { this._width = w; this._height = h; }
  getSize(target) { return target.set(this._width, this._height); }
  render() { this.frames += 1; }
  dispose() {}
}

/* Building a real environment map needs a GL context; nothing here looks at
 * the texture, only that the viewer can be constructed. */
export class PMREMGenerator {
  fromEquirectangular() { return {texture: {isTexture: true, dispose() {}}}; }
  dispose() {}
}

/* A dispatchable event target. Both the canvas and its owner document need to
 * be one: the controls listen for pointerdown on the canvas but move the
 * listener for pointermove and pointerup onto the document, so a drag that is
 * only delivered to the canvas is silently ignored. */
function target() {
  const listeners = new Map();
  return {
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener(type, fn) {
      const list = listeners.get(type) || [];
      const at = list.indexOf(fn);
      if (at >= 0) list.splice(at, 1);
    },
    // OrbitControls adds and removes handlers while dispatching, so the list
    // is copied before it is walked.
    dispatch(type, event) {
      for (const fn of [...(listeners.get(type) || [])]) {
        fn({type, preventDefault() {}, stopPropagation() {}, ...event});
      }
    },
  };
}

function canvas() {
  return Object.assign(target(), {
    width: 0, height: 0, style: {},
    // The controls divide their rotate and pan steps by clientHeight; leaving
    // it undefined turns every gesture into a silent NaN.
    clientWidth: 960, clientHeight: 640,
    getBoundingClientRect() {
      return {left: 0, top: 0, right: 960, bottom: 640, width: 960, height: 640};
    },
    setPointerCapture() {}, releasePointerCapture() {}, hasPointerCapture() { return true; },
    getRootNode() { return target(); },
    ownerDocument: target(),
    toDataURL() { return 'data:image/jpeg;base64,stub'; },
    remove() {},
  });
}
`);

const rewrite = (source, specifiers) => Object.entries(specifiers).reduce(
  (code, [from, to]) => code.split(`'${from}'`).join(`'${to}'`), source);

writeFileSync(path.join(shims, 'OrbitControls.mjs'), rewrite(
  readFileSync(path.join(VENDOR, 'addons/controls/OrbitControls.js'), 'utf8'),
  {three: './three.mjs'}));

// The loaders are imported at module scope and never reached: these tests move
// a camera, they do not parse a file.
for (const name of ['STLLoader', 'OBJLoader', 'GLTFLoader']) {
  writeFileSync(path.join(shims, `${name}.mjs`),
    `export class ${name} { parse() { throw new Error('not loaded in tests'); } }\n`);
}

writeFileSync(path.join(shims, 'viewer.mjs'), rewrite(readFileSync(SOURCE, 'utf8'), {
  'three': './three.mjs',
  'three/addons/controls/OrbitControls.js': './OrbitControls.mjs',
  'three/addons/loaders/STLLoader.js': './STLLoader.mjs',
  'three/addons/loaders/OBJLoader.js': './OBJLoader.mjs',
  'three/addons/loaders/GLTFLoader.js': './GLTFLoader.mjs',
}));

/* --- the smallest browser the viewer actually touches ------------------- */

// A 3x display, so a missing cap on the pixel ratio shows up as a failure
// rather than as the 1 a stub would default to.
globalThis.window = {addEventListener() {}, removeEventListener() {}, devicePixelRatio: 3};
globalThis.document = {addEventListener() {}, removeEventListener() {}, pointerLockElement: null};
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};

const {ModelViewer, orientationFromViews} =
  await import(pathToFileURL(path.join(shims, 'viewer.mjs')).href);
// The same three.js the viewer itself resolved, so a Vector3 built here is the
// one its arithmetic expects. Imported before the shims are swept away.
const THREE = await import(pathToFileURL(path.join(shims, 'three.mjs')).href);
rmSync(shims, {recursive: true, force: true});

const viewer = () => {
  const container = {clientWidth: 960, clientHeight: 640, appendChild() {}};
  const view = new ModelViewer(container);
  return {view, container, canvas: view.renderer.domElement};
};

// One wheel notch is 100 units; the controls turn that into a fixed 0.95 (or
// 1/0.95) multiplier per notch, which is why a long scroll runs away.
const scroll = (view, canvas, deltaY, notches) => {
  for (let i = 0; i < notches; i += 1) {
    canvas.dispatch('wheel', {deltaY, deltaMode: 0, clientX: 480, clientY: 320});
    view.controls.update();
  }
};

// pointerdown lands on the canvas, but the controls then listen for the rest of
// the gesture on the document, exactly as a browser delivers it.
const drag = (view, canvas, from, to) => {
  const pointer = {pointerId: 1, button: 0, buttons: 1, pointerType: 'mouse'};
  canvas.dispatch('pointerdown', {...pointer, clientX: from[0], clientY: from[1]});
  canvas.ownerDocument.dispatch('pointermove', {...pointer, clientX: to[0], clientY: to[1]});
  canvas.ownerDocument.dispatch('pointerup', {...pointer, clientX: to[0], clientY: to[1]});
  // Damping spreads one gesture over several frames.
  for (let i = 0; i < 60; i += 1) view.controls.update();
};

const radius = (view) => view.camera.position.distanceTo(view.controls.target);

// controls.update() round-trips the position through spherical coordinates, so
// a restored view comes back a few ulps off what was stored.
const near = (actual, expected, what) => assert.ok(
  Math.abs(actual - expected) < 1e-6, `${what}: ${actual}, expected ${expected}`);

const results = [];
const test = (name, fn) => {
  try { fn(); results.push(['PASS', name]); }
  catch (error) { results.push(['FAIL', `${name}\n    ${error.message}`]); }
};

/* --- what the model has to stay visible through ------------------------- */

test('the default view sits between the two limits', () => {
  const {view} = viewer();
  assert.ok(radius(view) > view.controls.minDistance, 'starts inside the near limit');
  assert.ok(radius(view) < view.controls.maxDistance, 'starts past the far limit');
});

test('the near limit clears the model, which reaches radius 1', () => {
  // _normalize() scales by the bounding sphere of the box, so a corner of the
  // mesh sits at radius 1. Anything closer puts the camera inside the surface,
  // where back-face culling leaves nothing but the background colour.
  const {view} = viewer();
  assert.ok(view.controls.minDistance > 1, `minDistance is ${view.controls.minDistance}`);
});

test('the limits keep the whole model inside the frustum', () => {
  // The model spans radius - 1 to radius + 1 in camera distance, so each limit
  // has to clear its plane by more than the model itself.
  const {view} = viewer();
  assert.ok(view.controls.maxDistance + 1 < view.camera.far,
            `maxDistance ${view.controls.maxDistance} vs far ${view.camera.far}`);
  assert.ok(view.controls.minDistance - 1 > view.camera.near,
            `minDistance ${view.controls.minDistance} vs near ${view.camera.near}`);
});

test('scrolling in as far as it will go never enters the model', () => {
  const {view, canvas} = viewer();
  scroll(view, canvas, -100, 400);
  assert.ok(radius(view) > 1, `camera is inside the model, at ${radius(view)}`);
});

test('scrolling out as far as it will go never leaves the frustum', () => {
  const {view, canvas} = viewer();
  scroll(view, canvas, 100, 400);
  assert.ok(radius(view) + 1 < view.camera.far,
            `model is past the far plane, at ${radius(view)}`);
});

test('a trackpad pinch is bounded too', () => {
  // The controls multiply a ctrl-held wheel delta by ten, so a pinch covers in
  // one gesture what the wheel takes dozens of notches to reach.
  const {view, canvas} = viewer();
  for (let i = 0; i < 40; i += 1) {
    canvas.dispatch('wheel', {deltaY: -100, deltaMode: 0, clientX: 480, clientY: 320, ctrlKey: true});
    view.controls.update();
  }
  assert.ok(radius(view) > 1, `ended up inside the model, at ${radius(view)}`);
});

test('the camera still moves after being scrolled to the limit', () => {
  // The failure this replaces was not a slow view but a dead one: the orbit
  // radius reached zero, and since it is only ever multiplied, no drag could
  // ever grow it again.
  const {view, canvas} = viewer();
  scroll(view, canvas, -100, 400);
  const before = view.camera.position.clone();
  drag(view, canvas, [480, 320], [620, 400]);
  assert.ok(view.camera.position.distanceTo(before) > 0.01, 'dragging changed nothing');
});

test('panning cannot strand the model off screen', () => {
  // The pan step scales with the orbit radius, so a right-drag while zoomed out
  // moves the orbit centre much further than the same drag while zoomed in.
  const {view, canvas} = viewer();
  scroll(view, canvas, 100, 40);
  for (let i = 0; i < 20; i += 1) {
    const pointer = {pointerId: 1, button: 2, buttons: 2, pointerType: 'mouse'};
    canvas.dispatch('pointerdown', {...pointer, clientX: 100, clientY: 100});
    canvas.ownerDocument.dispatch('pointermove', {...pointer, clientX: 900, clientY: 600});
    canvas.ownerDocument.dispatch('pointerup', {...pointer, clientX: 900, clientY: 600});
    for (let f = 0; f < 30; f += 1) view.controls.update();
  }
  // The model is a unit sphere at the origin, so an orbit centre a handful of
  // radii away has already taken it off screen for good.
  assert.ok(view.controls.target.length() < 5,
            `target ended ${view.controls.target.length()} from the model`);
});

/* --- and what a saved camera has to survive ----------------------------- */

test('a saved view is replayed as it was captured', () => {
  const {view} = viewer();
  view.setCameraState({position: [0, 0, 4], target: [0, 0, 0]});
  near(view.camera.position.x, 0, 'x');
  near(view.camera.position.y, 0, 'y');
  near(view.camera.position.z, 4, 'z');
  assert.deepEqual(view.controls.target.toArray(), [0, 0, 0]);
});

test('a saved view keeps its angle when its distance is pulled back', () => {
  const {view} = viewer();
  view.setCameraState({position: [0, 0, 900], target: [0, 0, 0]});
  assert.ok(radius(view) + 1 < view.camera.far, `restored past the far plane, at ${radius(view)}`);
  // Straight down -z is what was captured, and that much is worth keeping.
  near(view.camera.position.x, 0, 'x');
  near(view.camera.position.y, 0, 'y');
  assert.ok(view.camera.position.z > 0, 'flipped to the other side of the model');
});

test('a saved view from inside the model is pushed back out', () => {
  const {view} = viewer();
  view.setCameraState({position: [0.05, 0, 0], target: [0, 0, 0]});
  assert.ok(radius(view) > 1, `restored inside the model, at ${radius(view)}`);
});

test('a saved camera sitting on its own target falls back to the default view', () => {
  // Zero orbit radius is the one state the controls cannot climb out of, so it
  // must never be restored, however faithfully it was recorded.
  const {view} = viewer();
  view.setCameraState({position: [1, 2, 3], target: [1, 2, 3]});
  assert.ok(radius(view) > 1, `restored at ${radius(view)}`);
  assert.deepEqual(view.controls.target.toArray(), [0, 0, 0]);
});

test('a saved camera full of nonsense falls back to the default view', () => {
  const {view} = viewer();
  view.setCameraState({position: [NaN, 0, 0], target: [0, Infinity, 0]});
  assert.ok(Number.isFinite(radius(view)), 'orbit radius is not a number');
  assert.ok(radius(view) > 1, `restored at ${radius(view)}`);
});

test('a saved target far from the model is brought back within reach', () => {
  const {view} = viewer();
  view.setCameraState({position: [400, 0, 0], target: [396, 0, 0]});
  assert.ok(view.controls.target.length() < 5,
            `target restored ${view.controls.target.length()} from the model`);
});

/* --- and the frames it should not be spending --------------------------- */

test('a hidden viewer stops drawing', () => {
  // The viewer sits in a <dialog> that nothing tears down on close, so a loop
  // that kept running would cost frames for the rest of the page's life.
  const {view, container} = viewer();
  view._animate();
  const drawn = view.renderer.frames;
  container.clientWidth = 0;
  container.clientHeight = 0;
  view._animate();
  assert.equal(view.renderer.frames, drawn, 'rendered into a hidden container');
  container.clientWidth = 960;
  container.clientHeight = 640;
  view._animate();
  assert.equal(view.renderer.frames, drawn + 1, 'did not start drawing again');
});

test('the pixel ratio is capped below what a 3x display asks for', () => {
  const {view} = viewer();
  assert.ok(view.renderer.getPixelRatio() <= 2,
            `pixel ratio is ${view.renderer.getPixelRatio()}`);
});

/* --- and which way round the model is ----------------------------------- */

const dir = (x, y, z) => new THREE.Vector3(x, y, z).normalize();

// Compared component by component rather than by distance, so a failure names
// the axis that went wrong — a swapped pair and a mirrored one land the same
// distance away and would report identically.
const nearDir = (actual, expected, what) => {
  for (const axis of ['x', 'y', 'z']) {
    near(actual[axis], expected[axis], `${what} ${axis} (got ${actual.toArray()})`);
  }
};

const turn = (quaternion, vector) =>
  vector.clone().applyQuaternion(new THREE.Quaternion().fromArray(quaternion));

// A box rather than a cube: _normalize() works off the bounding box, so a model
// the same size on every axis would hide a scale applied to the wrong one.
const withModel = () => {
  const made = viewer();
  made.view._setModel(new THREE.Mesh(
    new THREE.BoxGeometry(1, 2, 3), new THREE.MeshBasicMaterial()));
  return made;
};

test('a model already facing the right way is corrected by nothing', () => {
  const same = orientationFromViews(dir(0, 0, 1), dir(0, 1, 0));
  assert.ok(same, 'refused the case it should handle best');
  assert.ok(same.angleTo(new THREE.Quaternion()) < 1e-6,
            `turned an already-correct model by ${same.angleTo(new THREE.Quaternion())}`);
});

test('the front and top the author points out land on the axes the views use', () => {
  // A Z-up export, which is what most STLs out of CAD are: the part's front
  // faces -Y and its top faces +Z, so Front shows an end and Top shows a flank.
  const fixed = orientationFromViews(dir(0, -1, 0), dir(0, 0, 1)).toArray();
  nearDir(turn(fixed, dir(0, -1, 0)), dir(0, 0, 1), 'front');
  nearDir(turn(fixed, dir(0, 0, 1)), dir(0, 1, 0), 'top');
});

test('the four sides nobody sets are the ones that follow, not their mirrors', () => {
  // The whole claim of the sequence is that two faces fix six. Getting the
  // handedness backwards still produces a tidy basis and a plausible front and
  // top — it just swaps left with right, silently, on every model.
  const front = dir(1, 1, 0);
  const top = dir(0, 0, 1);
  const right = new THREE.Vector3().crossVectors(top, front);
  const fixed = orientationFromViews(front, top).toArray();
  nearDir(turn(fixed, front), dir(0, 0, 1), 'front');
  nearDir(turn(fixed, top), dir(0, 1, 0), 'top');
  nearDir(turn(fixed, right), dir(1, 0, 0), 'right');
  nearDir(turn(fixed, right.clone().negate()), dir(-1, 0, 0), 'left');
});

test('a top set too near the front is refused rather than guessed at', () => {
  // What is left of the top once the front is taken out of it is what decides
  // the other four sides. A few degrees apart and that remainder is whichever
  // pixel the drag happened to finish on.
  assert.equal(orientationFromViews(dir(0, 0, 1), dir(0.1, 0, 1)), null,
               'accepted two views a few degrees apart');
  assert.equal(orientationFromViews(dir(0, 0, 1), dir(0, 0, 1)), null,
               'accepted the same view twice');
  assert.equal(orientationFromViews(dir(0, 0, 1), dir(0, 0, -1)), null,
               'accepted a top set from directly behind the front');
  assert.ok(orientationFromViews(dir(0, 0, 1), dir(0, 0.4, 1)),
            'refused two views far enough apart to have been meant');
});

test('re-orienting the model does not move the picture', () => {
  // The camera turns with the model, so nothing on screen shifts and only the
  // names of the faces change. Without that the confirmation would swing away
  // from whatever the user was looking at when they pressed the button.
  const {view} = withModel();
  const before = view.viewDirection();
  assert.ok(view.reorient(dir(0, -1, 0), dir(0, 0, 1)), 'refused a right-angled pair');
  nearDir(view.viewDirection(), before, 'the direction the camera looks from');
});

test('running the sequence again replaces the first answer instead of stacking', () => {
  // Both captures are read in the model's own coordinates, so a second run
  // starts from the file rather than from wherever the first run left things.
  const {view} = withModel();
  view.reorient(dir(0, -1, 0), dir(0, 0, 1));
  assert.ok(view.getModelOrientation(), 'the first run stored nothing');
  view.reorient(dir(0, 0, 1), dir(0, 1, 0));
  assert.equal(view.getModelOrientation(), null,
               'a second run naming the axes the file already has left a correction behind');
});

test('a correction outlives the model being loaded again', () => {
  const {view} = withModel();
  view.reorient(dir(0, -1, 0), dir(0, 0, 1));
  const fixed = view.getModelOrientation();
  view._setModel(new THREE.Mesh(new THREE.BoxGeometry(1, 2, 3), new THREE.MeshBasicMaterial()));
  nearDir(turn(fixed, dir(0, -1, 0)), dir(0, 0, 1), 'front after reloading');
  assert.ok(view.model.quaternion.angleTo(new THREE.Quaternion().fromArray(fixed)) < 1e-6,
            'the reloaded model came back on the axes the file gave it');
});

test('a stored correction that is not four numbers is ignored', () => {
  const {view} = withModel();
  for (const bad of [null, 'front', [0, 0, 1], [0, 0, 0, 0], [NaN, 0, 0, 1], [0, 0, 0, Infinity]]) {
    view.reorient(dir(0, -1, 0), dir(0, 0, 1));
    view.setModelOrientation(bad);
    assert.equal(view.getModelOrientation(), null, `kept ${JSON.stringify(bad)}`);
    assert.ok(view.model.quaternion.angleTo(new THREE.Quaternion()) < 1e-6,
              `left the model turned by ${JSON.stringify(bad)}`);
  }
});

test('the saved state carries a correction only once there is one', () => {
  const {view} = withModel();
  assert.equal('orientation' in view.getCameraState(), false,
               'stored a correction for a design that never ran the sequence');
  view.reorient(dir(0, -1, 0), dir(0, 0, 1));
  assert.equal(view.getCameraState().orientation.length, 4, 'did not store the correction');
});

test('a saved correction is restored along with the camera', () => {
  const {view} = withModel();
  const fixed = orientationFromViews(dir(0, -1, 0), dir(0, 0, 1)).toArray();
  view.setCameraState({position: [0, 0, 4], target: [0, 0, 0], orientation: fixed});
  near(view.camera.position.z, 4, 'z');
  assert.ok(view.model.quaternion.angleTo(new THREE.Quaternion().fromArray(fixed)) < 1e-6,
            'restored the camera but not the correction it was measured against');
});

test('all six views are different, and each keeps the model in frame', () => {
  const {view} = withModel();
  const seen = [];
  for (const face of ['front', 'back', 'left', 'right', 'top', 'bottom']) {
    view.setView(face);
    assert.ok(radius(view) > 1, `${face} put the camera inside the model, at ${radius(view)}`);
    assert.ok(radius(view) + 1 < view.camera.far, `${face} put the model past the far plane`);
    for (const [other, position] of seen) {
      assert.ok(view.camera.position.distanceTo(position) > 0.1,
                `${face} and ${other} are the same view`);
    }
    seen.push([face, view.camera.position.clone()]);
  }
});

test('recentring pulls a panned view back onto the model without turning it', () => {
  // A panned orbit centre makes "facing the camera" mean something other than
  // "facing the model", which is the judgement both capture steps rest on.
  const {view} = withModel();
  const before = view.viewDirection();
  view.controls.target.set(1.5, 0, 0);
  view.camera.position.add(new THREE.Vector3(1.5, 0, 0));
  view.recentre();
  assert.ok(view.controls.target.length() < 1e-6,
            `orbit centre left ${view.controls.target.length()} from the model`);
  nearDir(view.viewDirection(), before, 'the direction the camera looks from');
});

let failed = 0;
for (const [state, name] of results) {
  console.log(`${state}  ${name}`);
  if (state === 'FAIL') failed += 1;
}
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
