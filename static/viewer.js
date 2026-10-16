/*
 * 3D model viewer + preview capture.
 *
 * three.js is vendored under /static/vendor/three/ rather than loaded from a
 * CDN: the assignment requires the app to run on a grader's machine, and a CDN
 * link would quietly make it require their internet as well. The import map
 * that resolves the bare "three" specifier lives in templates/base.html.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const CAPTURE_WIDTH = 1024;
const CAPTURE_HEIGHT = 768;
const BACKGROUND = 0x131820;

/* Orbit limits, in model radii. _normalize() puts every model inside a
 * bounding sphere of radius 1 at the origin, so one set of absolute numbers
 * bounds every file rather than needing to be recomputed per load.
 *
 * Without them OrbitControls only ever multiplies the orbit radius, so the
 * wheel walks the camera all the way through the mesh (inside a closed
 * surface back-face culling leaves nothing but the background colour) or out
 * past the far plane, and either way the model vanishes and dragging changes
 * nothing visible — which reads as the viewer having locked up. MIN_ORBIT sits
 * above 1 because that bounding sphere comes from the box diagonal, so a
 * corner of the mesh can reach radius 1 exactly. */
const MIN_ORBIT = 1.4;
const MAX_ORBIT = 20;

/* How far the orbit centre may be panned from the model. Panning moves by a
 * step proportional to the orbit radius, so a couple of drags while zoomed out
 * would otherwise strand the model somewhere off in empty space. */
const MAX_PAN = 2;

/* Retina displays ask for the square of this many fragments. Past 2 the extra
 * detail is invisible and a heavy assembly slows to the point of feeling
 * frozen. */
const MAX_PIXEL_RATIO = 2;

/* How far apart the two captures of the orientation sequence have to be, as
 * the square of the sine of the angle between them, before the second one says
 * anything usable. The front capture is taken exactly as given and the top
 * capture contributes only the part of itself at right angles to it, so two
 * directions a few degrees apart leave that remainder to be decided by which
 * pixel the drag happened to end on. This is about 18 degrees. */
const MIN_AXIS_SEPARATION = 0.1;

/* Build the correction that puts a model's own front on +Z and its own top on
 * +Y, given those two directions in the model's coordinates.
 *
 * An STL carries no axis convention at all and an OBJ or GLB carries whichever
 * one its exporter used, so a file can arrive lying on its side with no way for
 * the viewer to tell. Two directions the author points out are enough to fix
 * every face: the front and the top of an object determine its other four
 * sides, and this rebuilds the whole basis from them.
 *
 * The two will not be exactly at right angles, since they come from a person
 * dragging a model around, so only the front is honoured exactly; the top is
 * reduced to the part of itself perpendicular to the front. The result is a
 * proper rotation rather than a general transform, so nothing is skewed,
 * scaled or mirrored by it. Returns null when the two are too close together
 * to span a plane. */
export function orientationFromViews(frontDir, topDir) {
  const front = frontDir.clone().normalize();
  const up = topDir.clone().normalize();
  if (!Number.isFinite(front.length()) || !Number.isFinite(up.length())) return null;

  up.sub(front.clone().multiplyScalar(up.dot(front)));
  if (up.lengthSq() < MIN_AXIS_SEPARATION) return null;
  up.normalize();

  // right = up x front keeps the triple right-handed, so makeBasis builds a
  // rotation and not a reflection.
  const right = new THREE.Vector3().crossVectors(up, front);
  // makeBasis writes its arguments as the columns, giving the matrix that maps
  // +X, +Y and +Z onto them. Wanted here is the opposite direction of travel —
  // model axes onto world axes — and for a rotation the transpose is the
  // inverse.
  const basis = new THREE.Matrix4().makeBasis(right, up, front).transpose();
  return new THREE.Quaternion().setFromRotationMatrix(basis);
}

/* STEP is a boundary representation — solids and surfaces, not triangles — so
 * there is no loader here that could draw one without an OpenCascade kernel.
 * These uploads are accepted and served for download, and reaching the viewer
 * with one means saying so plainly rather than "could not be parsed". The
 * friendly flag keeps the message through loadFile's catch. */
const cadSourceError = (name) => {
  if (!/\.(step|stp)$/i.test(name || '')) return null;
  const error = new Error('STEP files are CAD source rather than a mesh, so they cannot open in the browser viewer. Download it to open the solids in your own CAD software.');
  error.friendly = true;
  return error;
};

export class ModelViewer {
  constructor(container) {
    this.container = container;
    this.model = null;

    // The correction from the orientation sequence, kept on the viewer rather
    // than on the model so it survives a model being swapped out and back in.
    this._orientation = new THREE.Quaternion();

    // Assembly playback state. A GLB can carry baked motion (mates exported as
    // animation tracks) and a part hierarchy; the mixer drives the motion and
    // _parts is the flat show/hide list the parts panel walks.
    this._clock = new THREE.Clock();
    this._mixer = null;
    this._clips = [];
    this._action = null;
    this._activeClip = 0;
    this._playing = false;
    this._parts = [];

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(BACKGROUND);

    const { clientWidth: w, clientHeight: h } = container;
    this.camera = new THREE.PerspectiveCamera(45, (w || 1) / (h || 1), 0.01, 100);
    this.camera.position.set(2.2, 1.6, 2.2);

    // preserveDrawingBuffer is what makes toDataURL() work. Without it the
    // browser is free to clear the buffer after each frame and the captured
    // preview comes back blank.
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));
    this.renderer.setSize(w, h);
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = MIN_ORBIT;
    this.controls.maxDistance = MAX_ORBIT;
    this.controls.maxTargetRadius = MAX_PAN;

    this._ambient = new THREE.HemisphereLight(0xdfe8ff, 0x30343d, 2.2);
    this.scene.add(this._ambient);
    this._key = new THREE.DirectionalLight(0xffffff, 2.4);
    this._key.position.set(4, 6, 3);
    this.scene.add(this._key);
    this._fill = new THREE.DirectionalLight(0xffffff, 0.8);
    this._fill.position.set(-4, -1, -3);
    this.scene.add(this._fill);

    this._applyEnvironment();
    this._setExposure(false);

    this._onResize = this._onResize.bind(this);
    window.addEventListener('resize', this._onResize);
    if (window.ResizeObserver) {
      this._observer = new ResizeObserver(this._onResize);
      this._observer.observe(container);
    }

    this._animate();
  }

  _animate() {
    this._frame = requestAnimationFrame(() => this._animate());
    const dt = this._clock.getDelta();
    // The viewer lives inside a <dialog> that is display:none while closed, and
    // nothing tears it down on close, so without this the loop keeps drawing
    // frames nobody can see for the rest of the page's life. Reading the delta
    // first and then dropping it means a reopened assembly resumes where it
    // paused rather than jumping forward by however long the dialog was shut.
    if (!this.container.clientWidth || !this.container.clientHeight) return;
    // Advance every frame so the clock stays in step; the action itself is
    // paused when not playing, so a still assembly holds its pose.
    if (this._mixer) this._mixer.update(dt);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  _onResize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  /* A vertical gradient used as scene.environment. Lights alone are not enough
   * for glTF: metallic-roughness materials show reflected surroundings, so
   * anything with metalness near 1 renders black in a scene with no
   * environment, however many lights it has. */
  _applyEnvironment() {
    // The gradient only varies vertically, but every row is still written out:
    // PMREMGenerator sizes its cubemap from the source width, and anything
    // narrow enough rounds down to a degenerate size that compiles to a broken
    // shader — which takes out every standard material in the scene, not just
    // the environment.
    const WIDTH = 256;
    const HEIGHT = 128;
    const sky = [159, 180, 216];
    const ground = [34, 38, 46];

    const data = new Uint8Array(WIDTH * HEIGHT * 4);
    for (let y = 0; y < HEIGHT; y++) {
      const t = y / (HEIGHT - 1);
      for (let x = 0; x < WIDTH; x++) {
        const i = (y * WIDTH + x) * 4;
        for (let c = 0; c < 3; c++) {
          data[i + c] = Math.round(sky[c] + (ground[c] - sky[c]) * t);
        }
        data[i + 3] = 255;
      }
    }

    const gradient = new THREE.DataTexture(data, WIDTH, HEIGHT);
    gradient.mapping = THREE.EquirectangularReflectionMapping;
    gradient.colorSpace = THREE.SRGBColorSpace;
    gradient.needsUpdate = true;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromEquirectangular(gradient).texture;
    pmrem.dispose();
    gradient.dispose();
  }

  /* Two exposures, because the two kinds of file want different light.
   *
   * STL and OBJ are lit hard on purpose: they are a single flat grey, and the
   * only thing separating one face from the next is how brightly it catches
   * the key light. glTF arrives with colours somebody chose, and that same rig
   * washes a saturated orange out to pale peach, so it gets dimmer lights and
   * a stronger environment — which is what its metallic-roughness materials
   * are reflecting anyway. */
  _setExposure(ownMaterials) {
    this._ambient.intensity = ownMaterials ? 0.75 : 2.2;
    this._key.intensity = ownMaterials ? 1.5 : 2.4;
    this._fill.intensity = ownMaterials ? 0.35 : 0.8;
    this.scene.environmentIntensity = ownMaterials ? 0.6 : 0.1;
  }

  _material() {
    return new THREE.MeshStandardMaterial({
      color: 0xc7ccd4,
      metalness: 0.25,
      roughness: 0.55,
      flatShading: false,
    });
  }

  /* Centre the model at the origin and scale it so its bounding sphere has
   * radius 1. Every model then sits in the same coordinate space, which is
   * what lets a saved camera position be replayed against a different file. */
  _normalize(object) {
    const box = new THREE.Box3().setFromObject(object);
    if (box.isEmpty()) return object;

    const centre = box.getCenter(new THREE.Vector3());
    object.position.sub(centre);

    const wrapper = new THREE.Group();
    wrapper.add(object);

    const radius = box.getBoundingSphere(new THREE.Sphere()).radius || 1;
    wrapper.scale.setScalar(1 / radius);
    return wrapper;
  }

  /* Drop any assembly playback tied to the outgoing model. Mates/parts belong
   * to one GLB; STL and OBJ have neither, so every load starts from empty. */
  _resetAssembly() {
    if (this._mixer) this._mixer.stopAllAction();
    this._mixer = null;
    this._clips = [];
    this._action = null;
    this._activeClip = 0;
    this._playing = false;
    this._parts = [];
  }

  _setModel(object) {
    this._resetAssembly();
    if (this.model) {
      this.scene.remove(this.model);
      this.model.traverse((child) => {
        if (!child.isMesh) return;
        child.geometry?.dispose();
        // glTF meshes can carry an array of materials, and each material can
        // hold several textures. Neither is freed by disposing the material.
        for (const material of [child.material].flat().filter(Boolean)) {
          for (const value of Object.values(material)) {
            if (value?.isTexture) value.dispose();
          }
          material.dispose();
        }
      });
    }
    this.model = this._normalize(object);
    this.model.quaternion.copy(this._orientation);
    this.scene.add(this.model);
    this.resetView();
  }

  loadSTL(arrayBuffer) {
    this._setExposure(false);
    const geometry = new STLLoader().parse(arrayBuffer);
    // Plenty of STLs arrive without usable normals and render flat black.
    geometry.computeVertexNormals();
    this._setModel(new THREE.Mesh(geometry, this._material()));
  }

  loadOBJ(text) {
    this._setExposure(false);
    const group = new OBJLoader().parse(text);
    const material = this._material();
    group.traverse((child) => {
      if (child.isMesh) {
        child.material = material;
        if (!child.geometry.attributes.normal) child.geometry.computeVertexNormals();
      }
    });
    this._setModel(group);
  }

  /* Parse a GLB (glTF binary) assembly. Unlike STL/OBJ this is a whole model
   * in one file: the part hierarchy, the materials somebody chose, and any
   * baked motion (mates exported as animation tracks). Returns a promise
   * because GLTFLoader.parse hands its result back through a callback. */
  loadGLB(arrayBuffer) {
    this._setExposure(true);
    return new Promise((resolve, reject) => {
      new GLTFLoader().parse(
        arrayBuffer,
        '',
        (gltf) => {
          try {
            this._setModel(gltf.scene);
            this._collectParts();
            this._setupAnimations(gltf.animations);
            resolve();
          } catch (err) {
            reject(err);
          }
        },
        (err) => reject(err instanceof Error ? err : new Error('That GLB could not be parsed.')),
      );
    });
  }

  _hasMesh(node) {
    let found = false;
    node.traverse((child) => { if (child.isMesh) found = true; });
    return found;
  }

  /* Build the flat show/hide list the parts panel walks. The real components
   * of an assembly are the children of the glTF root; single-child wrapper
   * nodes (a lone "Scene" container) are stepped through so the list lands on
   * the parts a person would recognise, not one node that hides everything. */
  _collectParts() {
    this._parts = [];
    if (!this.model || !this.model.children.length) return;

    let root = this.model.children[0];
    while (root.children.length === 1 && this._hasMesh(root.children[0])) {
      root = root.children[0];
    }

    const components = root.children.length ? root.children : [root];
    components.forEach((node, i) => {
      if (!this._hasMesh(node)) return;
      this._parts.push({
        id: this._parts.length,
        name: node.name || `Part ${i + 1}`,
        object: node,
        visible: true,
      });
    });
  }

  /* Wire up the baked motion. Empty or zero-length clips (some exporters emit
   * a stub) are dropped so hasAnimation() only reports real motion. The mixer
   * targets the normalized wrapper, which still contains every named node. */
  _setupAnimations(clips) {
    const usable = (clips || []).filter((clip) => clip && clip.duration > 0);
    if (!usable.length || !this.model) return;

    this._clips = usable;
    this._mixer = new THREE.AnimationMixer(this.model);
    this.selectClip(0, false);
  }

  hasAnimation() {
    return this._clips.length > 0;
  }

  clipNames() {
    return this._clips.map((clip, i) => clip.name || `Motion ${i + 1}`);
  }

  activeClip() {
    return this._activeClip;
  }

  /* Switch to clip `index`. It is played but immediately paused unless
   * autoplay is set, so the assembly holds the first pose until asked to run. */
  selectClip(index, autoplay = false) {
    if (!this._mixer || !this._clips[index]) return;
    if (this._action) this._action.stop();
    this._activeClip = index;
    this._action = this._mixer.clipAction(this._clips[index]);
    this._action.reset();
    this._action.play();
    this._action.paused = !autoplay;
    this._playing = !!autoplay;
  }

  isPlaying() {
    return this._playing;
  }

  togglePlay() {
    if (!this._action) return false;
    // A scrubbed-to-the-end clip would otherwise "resume" by looping; nudge it
    // back to the start so pressing play always runs the motion through.
    if (this._playing === false && this._action.time >= this._clips[this._activeClip].duration) {
      this._action.time = 0;
    }
    this._playing = !this._playing;
    this._action.paused = !this._playing;
    return this._playing;
  }

  /* Move to a point in the clip, 0..1. Leaves play/pause as it is: the mixer
   * applies the new pose on the next frame even while paused. */
  seek(fraction) {
    if (!this._action) return;
    const clamped = Math.min(1, Math.max(0, fraction));
    this._action.time = clamped * this._clips[this._activeClip].duration;
  }

  progress() {
    if (!this._action) return 0;
    const duration = this._clips[this._activeClip].duration || 1;
    return Math.min(1, this._action.time / duration);
  }

  parts() {
    return this._parts.map(({ id, name, visible }) => ({ id, name, visible }));
  }

  _part(id) {
    return this._parts.find((part) => part.id === id) || null;
  }

  setPartVisible(id, visible) {
    const part = this._part(id);
    if (!part) return;
    part.visible = !!visible;
    part.object.visible = part.visible;
  }

  isolatePart(id) {
    for (const part of this._parts) {
      part.visible = part.id === id;
      part.object.visible = part.visible;
    }
  }

  showAllParts() {
    for (const part of this._parts) {
      part.visible = true;
      part.object.visible = true;
    }
  }

  /* Read a File chosen in a file input. Returns a promise. */
  loadFile(file) {
    const name = (file.name || '').toLowerCase();
    const reader = new FileReader();

    return new Promise((resolve, reject) => {
      reader.onerror = () => reject(new Error('Could not read that file.'));
      reader.onload = async () => {
        try {
          if (name.endsWith('.obj')) this.loadOBJ(reader.result);
          else if (name.endsWith('.stl')) this.loadSTL(reader.result);
          else if (name.endsWith('.glb')) await this.loadGLB(reader.result);
          else throw cadSourceError(name) || new Error('Only STL, OBJ, and GLB models are supported.');
          resolve();
        } catch (err) {
          reject(err instanceof Error && err.friendly
            ? err
            : new Error('That file could not be parsed as a 3D model.'));
        }
      };
      if (name.endsWith('.obj')) reader.readAsText(file);
      else reader.readAsArrayBuffer(file);
    });
  }

  /* Load a model already stored on the server. */
  async loadURL(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error('Could not download the model.');

    const name = response.url.toLowerCase().split('?')[0];
    if (name.endsWith('.obj')) this.loadOBJ(await response.text());
    else if (name.endsWith('.stl')) this.loadSTL(await response.arrayBuffer());
    else if (name.endsWith('.glb')) await this.loadGLB(await response.arrayBuffer());
    else throw cadSourceError(name) || new Error('Only STL, OBJ, and GLB models are supported.');
  }

  resetView() {
    this.camera.position.set(2.2, 1.6, 2.2);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  /* Put the orbit centre back on the model without giving up the angle the
   * user has dragged to.
   *
   * Panning moves that centre, and the pan limit allows twice the radius of the
   * model, so a panned view can leave the thing half off the edge of the canvas
   * with the camera aimed past it. "Facing the camera" then stops meaning
   * "facing the model", which is the entire judgement the orientation sequence
   * asks a person to make. Moving the camera by the same vector as the target
   * keeps the direction and the distance between them, so the shot does not
   * spin — it only slides back onto the model. */
  recentre() {
    this.camera.position.sub(this.controls.target);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  /* The six faces, in the convention of every CAD package these uploads come
   * out of: the front is seen from +Z, the right from +X, the top from +Y.
   *
   * Only two of them are ever set by hand. Once the correction has put the
   * model's own front on +Z and its own top on +Y, the other four are just the
   * remaining axes — which is what makes pointing out a front and a top enough
   * to fix every side. 'side' is what the pages called the +X view before
   * there was a left to tell it apart from, and still answers to that. */
  setView(direction) {
    const views = {
      front: [0, 0, 3],
      back: [0, 0, -3],
      right: [3, 0, 0],
      side: [3, 0, 0],
      left: [-3, 0, 0],
      // Looking straight down the up axis is the one direction the controls
      // cannot describe in spherical coordinates, so both poles are nudged a
      // hair off it.
      top: [0, 3, 0.001],
      bottom: [0, -3, 0.001],
    };
    if (!views[direction]) return;
    this.camera.position.fromArray(views[direction]);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  /* The correction currently applied to the model, or null when the file is
   * being shown with its own axes. Null rather than the identity quaternion so
   * that a design that never ran the sequence stores nothing. */
  getModelOrientation() {
    const identity = new THREE.Quaternion();
    return this._orientation.angleTo(identity) < 1e-6
      ? null
      : this._orientation.toArray();
  }

  /* Apply a stored correction. Anything that is not four finite numbers, and
   * anything of no length, means "show the file's own axes" — this value comes
   * back from a database column, so it is rebuilt rather than trusted. */
  setModelOrientation(orientation) {
    const next = new THREE.Quaternion();
    if (Array.isArray(orientation) && orientation.length === 4
        && orientation.every((n) => typeof n === 'number' && Number.isFinite(n))) {
      next.fromArray(orientation);
      if (next.lengthSq() > 1e-6) next.normalize();
      else next.identity();
    }
    this._orientation.copy(next);
    if (this.model) this.model.quaternion.copy(next);
    this.controls.update();
  }

  /* Which way the camera is currently looking at the model from, in the
   * model's own coordinates rather than the world's.
   *
   * The distinction matters when the sequence is run a second time: by then a
   * correction is already in place, and a direction read straight off the world
   * would be measured against the corrected model instead of against the file.
   * Undoing the current correction puts both runs in the same frame, so the
   * second one replaces the first rather than compounding with it. */
  viewDirection() {
    const direction = this.camera.position.clone().sub(this.controls.target);
    if (!(direction.length() > 1e-6)) return null;
    return direction.normalize().applyQuaternion(this._orientation.clone().invert());
  }

  /* Re-orient the model from a captured front and top.
   *
   * The camera is turned by the same amount as the model, which leaves the
   * rendered picture pixel-for-pixel identical: nothing appears to move, and
   * what changes is only which face the viewer now calls the front. That also
   * keeps a preview angle captured earlier pointed at the same part of the
   * model instead of swinging round to a different one.
   *
   * Returns the new orientation as four numbers, or null when the two captures
   * were too close together to define one. */
  reorient(frontDir, topDir) {
    const next = orientationFromViews(frontDir, topDir);
    if (!next) return null;

    const delta = next.clone().multiply(this._orientation.clone().invert());
    this.camera.position.applyQuaternion(delta);
    this.controls.target.applyQuaternion(delta);
    this.setModelOrientation(next.toArray());
    return this.getModelOrientation();
  }

  getCameraState() {
    const state = {
      position: this.camera.position.toArray(),
      target: this.controls.target.toArray(),
    };
    const orientation = this.getModelOrientation();
    if (orientation) state.orientation = orientation;
    return state;
  }

  /* A saved camera is replayed on every open, so a bad one is not a passing
   * glitch but a design that always opens to a dead view. Rather than trust the
   * stored numbers, keep the direction the author framed and pull the distance
   * and the orbit centre back inside the same limits the controls enforce. */
  setCameraState(state) {
    if (!state) return;
    // Before the camera, because the orientation decides what the camera is
    // pointing at, and because a design can carry a correction without ever
    // having had a preview angle captured.
    this.setModelOrientation(state.orientation);
    if (!Array.isArray(state.position)) return;

    const position = new THREE.Vector3().fromArray(state.position);
    const target = Array.isArray(state.target)
      ? new THREE.Vector3().fromArray(state.target)
      : new THREE.Vector3();
    const offset = position.sub(target);

    // A position sitting exactly on its target is the one state OrbitControls
    // cannot climb out of: the radius is only ever multiplied, so zero stays
    // zero however the user drags. There is no direction to preserve in that
    // case, and none in a NaN either, so both fall back to the default view.
    if (!Number.isFinite(target.length()) || !(offset.length() > 1e-4)) {
      this.resetView();
      return;
    }

    target.clampLength(0, MAX_PAN);
    offset.clampLength(MIN_ORBIT, MAX_ORBIT);
    this.camera.position.copy(target).add(offset);
    this.controls.target.copy(target);
    this.controls.update();
  }

  /* Render one frame at a fixed size and return it as a JPEG data URL.
   * JPEG rather than PNG because a full-resolution PNG data URL runs to
   * several megabytes and base64 inflates it another third on the way up. */
  capture() {
    const size = this.renderer.getSize(new THREE.Vector2());
    const ratio = this.renderer.getPixelRatio();

    this.renderer.setPixelRatio(1);
    this.renderer.setSize(CAPTURE_WIDTH, CAPTURE_HEIGHT, false);
    this.camera.aspect = CAPTURE_WIDTH / CAPTURE_HEIGHT;
    this.camera.updateProjectionMatrix();
    this.renderer.render(this.scene, this.camera);

    const dataURL = this.renderer.domElement.toDataURL('image/jpeg', 0.85);

    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(size.x, size.y, false);
    this.camera.aspect = size.x / size.y;
    this.camera.updateProjectionMatrix();

    return dataURL;
  }

  destroy() {
    cancelAnimationFrame(this._frame);
    this._mixer?.stopAllAction();
    window.removeEventListener('resize', this._onResize);
    this._observer?.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

export function webglAvailable() {
  try {
    const canvas = document.createElement('canvas');
    return !!(window.WebGLRenderingContext &&
              (canvas.getContext('webgl2') || canvas.getContext('webgl')));
  } catch (err) {
    return false;
  }
}
