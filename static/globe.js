/*
 * Landing-page hero globe.
 *
 * The logo is a robot head sitting on a green-and-blue world, so this animates
 * that idea: robots spread across the continents until they hold all of them,
 * then people take the world back, and it runs again. The two fronts advance
 * from different directions, so the reclaim is not the takeover played
 * backwards.
 *
 * It is decoration, so it stays out of the way: nothing is built at all below
 * the breakpoint, the loop stops whenever the section is off-screen or the tab
 * is hidden, and a reduced-motion preference gets a still frame of the world
 * before any of it starts.
 */

import * as THREE from 'three';
import { webglAvailable } from './viewer.js';

/* Must match the min-width guarding .hero__globe in style.css. Below it the
 * hero is a single column and there is no space to the right to fill. */
const MIN_WIDTH = 1040;

const MAP_WIDTH = 512;
const MAP_HEIGHT = 256;

// Seconds. The two holds are what make the loop readable — without them the
// world flips over the moment it finishes changing hands.
const TAKEOVER = 9;
const HOLD_ROBOT = 2;
const RECLAIM = 7;
const HOLD_HUMAN = 2.5;
const CYCLE = TAKEOVER + HOLD_ROBOT + RECLAIM + HOLD_HUMAN;

const ease = (t) => t * t * (3 - 2 * t);

/* ------------------------------------------------------------------ noise */

/* Value noise sampled in 3D and read along the sphere's surface normal rather
 * than across the flat texture. Sampling the texture's own uv would pinch
 * every continent at the poles and split them at the seam. */
function hash(x, y, z) {
  let h = Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(z, 1274126177);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

function noise3(x, y, z) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
  const xf = ease(x - xi), yf = ease(y - yi), zf = ease(z - zi);

  const lerp = (a, b, t) => a + (b - a) * t;
  const corner = (dx, dy, dz) => hash(xi + dx, yi + dy, zi + dz);

  const x00 = lerp(corner(0, 0, 0), corner(1, 0, 0), xf);
  const x10 = lerp(corner(0, 1, 0), corner(1, 1, 0), xf);
  const x01 = lerp(corner(0, 0, 1), corner(1, 0, 1), xf);
  const x11 = lerp(corner(0, 1, 1), corner(1, 1, 1), xf);

  return lerp(lerp(x00, x10, yf), lerp(x01, x11, yf), zf);
}

function fbm(x, y, z, octaves = 4) {
  let sum = 0, amplitude = 1, total = 0, frequency = 1;
  for (let i = 0; i < octaves; i++) {
    sum += noise3(x * frequency, y * frequency, z * frequency) * amplitude;
    total += amplitude;
    amplitude *= 0.5;
    frequency *= 2;
  }
  return sum / total;
}

/* ------------------------------------------------------------- world data */

/* One RGBA texture holding three fields rather than three textures:
 *   R  land mask, 0 ocean to 255 land
 *   G  the order robots reach each point in
 *   B  the order people reclaim each point in
 * Both orders are geodesic distance from a starting point, warped by noise so
 * the fronts crawl unevenly instead of expanding as clean circles. */
function buildWorldTexture() {
  const data = new Uint8Array(MAP_WIDTH * MAP_HEIGHT * 4);

  // Where each side starts from, on opposite faces of the globe.
  const robotSeed = new THREE.Vector3(0.75, 0.42, 0.5).normalize();
  const humanSeed = new THREE.Vector3(-0.7, -0.25, -0.65).normalize();

  const front = (dot, warp) => {
    const distance = Math.acos(THREE.MathUtils.clamp(dot, -1, 1)) / Math.PI;
    // Floor of 0.08 so nothing is already claimed at progress 0 and the loop
    // restarts without a patch popping in.
    const warped = THREE.MathUtils.clamp(distance * 0.82 + (warp - 0.5) * 0.5, 0, 1);
    return Math.round((0.08 + warped * 0.92) * 255);
  };

  for (let y = 0; y < MAP_HEIGHT; y++) {
    const phi = ((y + 0.5) / MAP_HEIGHT) * Math.PI;
    const sinPhi = Math.sin(phi), cosPhi = Math.cos(phi);

    for (let x = 0; x < MAP_WIDTH; x++) {
      const theta = ((x + 0.5) / MAP_WIDTH) * Math.PI * 2;
      const nx = sinPhi * Math.cos(theta);
      const ny = cosPhi;
      const nz = sinPhi * Math.sin(theta);

      // Three octaves at a low frequency: enough to break up the outline,
      // not so much that the coast turns fiddly. The logo's continents are
      // simple rounded blobs and these should read the same way.
      // Stored as the raw height — the shader cuts the coastline out of it,
      // so the edge stays sharp however large the globe is drawn.
      const height = fbm(nx * 1.55 + 12.3, ny * 1.55 + 4.1, nz * 1.55 + 30.7, 3);

      const i = (y * MAP_WIDTH + x) * 4;
      data[i] = Math.round(THREE.MathUtils.clamp(height, 0, 1) * 255);
      data[i + 1] = front(nx * robotSeed.x + ny * robotSeed.y + nz * robotSeed.z,
                          fbm(nx * 2.6 + 61.2, ny * 2.6 + 8.9, nz * 2.6 + 17.4, 3));
      data[i + 2] = front(nx * humanSeed.x + ny * humanSeed.y + nz * humanSeed.z,
                          fbm(nx * 2.6 + 3.7, ny * 2.6 + 44.5, nz * 2.6 + 91.1, 3));
      data[i + 3] = 255;
    }
  }

  const texture = new THREE.DataTexture(data, MAP_WIDTH, MAP_HEIGHT, THREE.RGBAFormat);
  texture.wrapS = THREE.RepeatWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  return texture;
}

/* ----------------------------------------------------------------- shader */

const GLOBE_VERTEX = /* glsl */`
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

/* Deliberately unlit: no lambert term, no rim, no gradient. The logo is flat
 * vector art, so the sphere reads as a disc of solid colour and only the
 * continents sliding across it give away that it is turning.
 *
 * Colours are the logo's, written straight out with no colour-space
 * conversion, so what lands on screen is the hex value as authored. */
const GLOBE_FRAGMENT = /* glsl */`
  uniform sampler2D uWorld;
  uniform float uRobot;
  uniform float uHuman;

  varying vec2 vUv;

  const vec3 OCEAN      = vec3(0.184, 0.545, 0.769);
  const vec3 OCEAN_HELD = vec3(0.259, 0.373, 0.478);
  const vec3 LAND       = vec3(0.416, 0.729, 0.353);
  const vec3 LAND_EDGE  = vec3(0.306, 0.596, 0.259);
  const vec3 ROBOT      = vec3(1.000, 0.478, 0.239);
  const vec3 ROBOT_EDGE = vec3(0.878, 0.357, 0.106);

  // Chosen against the noise's actual distribution: land covers a little
  // under 40% of the sphere, so the continents stay separate shapes.
  const float SEA_LEVEL = 0.53;
  // How far behind each front its darker band reaches, in progress units.
  const float BAND = 0.05;

  /* A step softened by exactly one screen pixel. Flat art wants a hard vector
   * edge, but a hard edge crawls and aliases as the globe turns; deriving the
   * width from the value's own screen-space gradient keeps the coastline
   * looking cut rather than blurred, at any size. */
  float cut(float value, float level) {
    float width = clamp(fwidth(value), 0.0008, 0.05);
    return smoothstep(level - width, level + width, value);
  }

  void main() {
    vec3 world = texture2D(uWorld, vUv).rgb;
    float land = cut(world.r, SEA_LEVEL);

    float taken     = cut(uRobot - world.g, 0.0);
    float reclaimed = cut(uHuman - world.b, 0.0);
    float robot = clamp(taken - reclaimed, 0.0, 1.0);

    // Ground the fronts have just crossed, as a flat band of a deeper shade
    // rather than a glow. Faded out as each side finishes so no band is left
    // sitting on the world when the loop wraps.
    float advancing = (taken - cut(uRobot - world.g, BAND))
                    * (1.0 - smoothstep(0.9, 1.0, uRobot)) * (1.0 - reclaimed);
    float pushing   = (reclaimed - cut(uHuman - world.b, BAND))
                    * (1.0 - smoothstep(0.9, 1.0, uHuman));

    vec3 ground = mix(LAND, ROBOT, robot);
    ground = mix(ground, ROBOT_EDGE, advancing);
    ground = mix(ground, LAND_EDGE, pushing);

    // Oceans only cool off under machine control, they never flip to orange.
    vec3 sea = mix(OCEAN, OCEAN_HELD, robot * 0.55);

    gl_FragColor = vec4(mix(sea, ground, land), 1.0);
  }
`;

/* ------------------------------------------------------------------ scene */

/* The logo's mark: an orange head with two square eyes and a stub of antenna.
 * Cut from flat planes, not boxes — these are billboarded at the camera every
 * frame, so they stay face-on silhouettes like the logo however far round the
 * globe they have travelled. */
function buildRobot() {
  const robot = new THREE.Group();

  const orange = new THREE.MeshBasicMaterial({ color: 0xff7a3d, side: THREE.DoubleSide });
  const dark = new THREE.MeshBasicMaterial({ color: 0x0d1117, side: THREE.DoubleSide });

  // Every layer is nudged a little further towards the camera than the one it
  // sits on, so they stack by depth test instead of z-fighting.
  const layer = (geometry, material, x, y, z) => {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    robot.add(mesh);
    return mesh;
  };

  const antenna = new THREE.PlaneGeometry(0.014, 0.06);
  layer(new THREE.PlaneGeometry(0.034, 0.075), dark, 0, 0.088, 0);
  layer(antenna, orange, 0, 0.088, 0.002);

  // A dark keyline in the page's own background colour. Without it the head
  // disappears whenever it crosses a continent the machines already hold,
  // which is the same orange.
  layer(new THREE.PlaneGeometry(0.192, 0.152), dark, 0, 0, 0.004);
  layer(new THREE.PlaneGeometry(0.17, 0.13), orange, 0, 0, 0.006);

  const eye = new THREE.PlaneGeometry(0.035, 0.035);
  for (const x of [-0.038, 0.038]) layer(eye, dark, x, 0.005, 0.008);

  return robot;
}

/* A dashed ring standing in for the net the machines throw round the world.
 * Drawn as flat arcs facing the camera rather than a wireframe sphere: a
 * wireframe reads as a 3D cage and pulls the whole thing back out of 2D. */
function buildOrbitRing(material) {
  const ring = new THREE.Group();
  const DASHES = 16;
  const step = (Math.PI * 2) / DASHES;
  for (let i = 0; i < DASHES; i++) {
    ring.add(new THREE.Mesh(
      new THREE.RingGeometry(1.3, 1.316, 10, 1, i * step, step * 0.6),
      material
    ));
  }
  return ring;
}

class HeroGlobe {
  constructor(container, { animate = true } = {}) {
    this.container = container;
    this.animating = animate;
    this.elapsed = 0;
    this.running = false;

    const width = container.clientWidth || 360;
    const height = container.clientHeight || width;

    this.scene = new THREE.Scene();
    // Framed so the widest orbit below still clears the edge of the canvas:
    // at this distance the visible half-height is about 1.5 world units.
    this.camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 20);
    this.camera.position.set(0, 0, 4.35);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(width, height);
    this.renderer.setClearAlpha(0);
    container.appendChild(this.renderer.domElement);

    this.uniforms = {
      uWorld: { value: buildWorldTexture() },
      uRobot: { value: 0 },
      uHuman: { value: 0 },
    };

    // Tilted the way the logo's world sits, then spun about that same axis.
    this.world = new THREE.Group();
    this.world.rotation.z = THREE.MathUtils.degToRad(-16);
    this.scene.add(this.world);

    this.globe = new THREE.Mesh(
      new THREE.SphereGeometry(1, 96, 64),
      new THREE.ShaderMaterial({
        uniforms: this.uniforms,
        vertexShader: GLOBE_VERTEX,
        fragmentShader: GLOBE_FRAGMENT,
      })
    );
    this.world.add(this.globe);

    // Invisible until the machines hold enough of the world, and gone again
    // once people finish taking it back.
    this.ringMaterial = new THREE.MeshBasicMaterial({
      color: 0xff7a3d,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    });
    this.ring = buildOrbitRing(this.ringMaterial);
    this.scene.add(this.ring);

    this.robots = [];
    for (let i = 0; i < 5; i++) {
      const robot = buildRobot();
      robot.userData = {
        radius: 1.26 + (i % 3) * 0.06,
        speed: 0.42 + i * 0.07,
        phase: (i / 5) * Math.PI * 2,
        tilt: THREE.MathUtils.degToRad(-32 + i * 17),
        // Each machine shows up a fifth of the way further into the takeover.
        appearsAt: 0.1 + i * 0.16,
      };
      robot.scale.setScalar(0);
      this.scene.add(robot);
      this.robots.push(robot);
    }

    this._onResize = this._onResize.bind(this);
    this._observer = new ResizeObserver(this._onResize);
    this._observer.observe(container);

    this._tick = this._tick.bind(this);
    this._last = 0;
    this._update(0);
    this.renderer.render(this.scene, this.camera);
  }

  /* Where the loop is: how far the machines have spread, and how far people
   * have pushed back over that. Holding both at 1 leaves the world exactly as
   * it looks holding both at 0, which is what lets the cycle wrap without a
   * visible cut. */
  _progress(time) {
    const t = time % CYCLE;
    if (t < TAKEOVER) return [ease(t / TAKEOVER), 0];
    if (t < TAKEOVER + HOLD_ROBOT) return [1, 0];
    if (t < TAKEOVER + HOLD_ROBOT + RECLAIM) {
      return [1, ease((t - TAKEOVER - HOLD_ROBOT) / RECLAIM)];
    }
    return [1, 1];
  }

  _update(time) {
    const [robot, human] = this.animating ? this._progress(time) : [0, 0];
    this.uniforms.uRobot.value = robot;
    this.uniforms.uHuman.value = human;

    const dominance = THREE.MathUtils.clamp(robot - human, 0, 1);
    this.ringMaterial.opacity = dominance * 0.55;
    this.ring.quaternion.copy(this.camera.quaternion);
    this.ring.rotateZ(time * 0.22);

    this.world.rotation.y = time * 0.12;

    for (const robotMesh of this.robots) {
      const { radius, speed, phase, tilt, appearsAt } = robotMesh.userData;
      const scale = THREE.MathUtils.smoothstep(dominance, appearsAt, appearsAt + 0.14);
      robotMesh.scale.setScalar(scale);
      if (scale === 0) continue;

      const angle = phase + time * speed;
      robotMesh.position.set(
        Math.cos(angle) * radius,
        Math.sin(angle) * radius * Math.sin(tilt),
        Math.sin(angle) * radius * Math.cos(tilt)
      );
      // Face-on to the camera at all times, so each one stays a flat mark
      // instead of turning edge-on as it swings round the far side.
      robotMesh.quaternion.copy(this.camera.quaternion);
    }
  }

  _tick(now) {
    this._frame = requestAnimationFrame(this._tick);
    // Clamped so a backgrounded tab does not resume with a jump.
    this.elapsed += Math.min((now - this._last) / 1000, 0.05);
    this._last = now;
    this._update(this.elapsed);
    this.renderer.render(this.scene, this.camera);
  }

  _onResize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    if (!this.running) this.renderer.render(this.scene, this.camera);
  }

  start() {
    if (this.running || !this.animating) return;
    this.running = true;
    this._last = performance.now();
    this._frame = requestAnimationFrame(this._tick);
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this._frame);
  }

  destroy() {
    this.stop();
    this._observer.disconnect();
    this.scene.traverse((object) => {
      object.geometry?.dispose();
      for (const material of [object.material].flat().filter(Boolean)) material.dispose();
    });
    this.uniforms.uWorld.value.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

/* ------------------------------------------------------------------ mount */

export function mountHeroGlobe(container) {
  if (!container || !webglAvailable() || !window.ResizeObserver) return;

  const wide = window.matchMedia(`(min-width: ${MIN_WIDTH}px)`);
  const still = window.matchMedia('(prefers-reduced-motion: reduce)');
  let globe = null;
  let visible = true;

  // Nothing here is worth stealing frames from a scrolled-past section or a
  // tab nobody is looking at.
  const sync = () => {
    if (!globe) return;
    if (visible && !document.hidden) globe.start();
    else globe.stop();
  };

  const apply = () => {
    if (wide.matches && !globe) {
      globe = new HeroGlobe(container, { animate: !still.matches });
      sync();
    } else if (!wide.matches && globe) {
      globe.destroy();
      globe = null;
    }
  };

  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    sync();
  }).observe(container);

  document.addEventListener('visibilitychange', sync);
  wide.addEventListener('change', apply);
  still.addEventListener('change', () => {
    // Rebuild rather than toggle: the still frame is the pre-takeover world.
    if (globe) { globe.destroy(); globe = null; }
    apply();
  });

  apply();
}
