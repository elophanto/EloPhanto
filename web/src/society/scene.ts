import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

export interface SceneAgent {
  id: string;
  name: string;
  department: string;
  status: string;
  kind?: string;
  tool?: string;
}

type Callbacks = {
  onSelectAgent?: (id: string) => void;
  onSelectDepartment?: (id: string) => void;
};

type Department = {
  id: string;
  name: string;
  color: number;
  x: number;
  z: number;
  rotation: number;
  label: THREE.Vector3;
  entrance: THREE.Vector3;
  button: HTMLButtonElement;
  count: HTMLSpanElement;
  group: THREE.Group;
};

type Citizen = {
  data: SceneAgent;
  group: THREE.Group;
  body: THREE.Group;
  head: THREE.Group;
  leftArm: THREE.Group;
  rightArm: THREE.Group;
  leftLeg: THREE.Group;
  rightLeg: THREE.Group;
  halo: THREE.Mesh;
  indicator: THREE.Mesh;
  destination: THREE.Vector3;
  waypoints: THREE.Vector3[];
  phase: number;
  marker: HTMLButtonElement;
  markerText: HTMLSpanElement;
  markerStatus: HTMLSpanElement;
  walking: boolean;
  visitQueue: string[];
  visitDwell: number;
};

const C = {
  background: 0xf1f1e9,
  grass: 0x8ca56e,
  grassLight: 0x9bb477,
  grassDark: 0x617e48,
  foliage: 0x64884e,
  foliageLight: 0x87a95e,
  foliageDark: 0x466e46,
  ivory: 0xefe5cb,
  stone: 0xe7dcc3,
  stoneEdge: 0xc6b697,
  path: 0xe5d9be,
  pathLine: 0xd5cbb8,
  wood: 0xad7958,
  woodLight: 0xcc9a70,
  dark: 0x354b4a,
  window: 0x769ba1,
  windowLight: 0xb5d0c7,
  teal: 0x437d70,
  terracotta: 0xc36b4c,
  yellow: 0xd0a24c,
  blue: 0x55869d,
  pink: 0xbb8783,
  purple: 0x7f80a6,
  metal: 0x627370,
  water: 0x82bdba,
};

const DEPARTMENTS = [
  { id: "research", name: "Research", color: C.blue, x: -8.3, z: -5.1 },
  {
    id: "headquarters",
    name: "Headquarters",
    color: C.terracotta,
    x: 0,
    z: -8.0,
  },
  { id: "engineering", name: "Engineering", color: C.teal, x: 8.3, z: -5.1 },
  {
    id: "communications",
    name: "Communications",
    color: C.yellow,
    x: -8.4,
    z: 5.0,
  },
  { id: "operations", name: "Operations", color: C.purple, x: 0, z: 8.5 },
  { id: "knowledge", name: "Knowledge", color: C.pink, x: 8.4, z: 5.0 },
] as const;

const hash = (value: string) => {
  let result = 0;
  for (let i = 0; i < value.length; i++)
    result = ((result << 5) - result + value.charCodeAt(i)) | 0;
  return Math.abs(result);
};

/** A self-contained observer scene: it never shares a browser, browser profile, or agent lifecycle. */
export function createSocietyScene(
  container: HTMLElement,
  callbacks: Callbacks = {},
) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(C.background);
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.07;
  renderer.domElement.setAttribute(
    "aria-label",
    "Interactive isometric Agent Society campus. Drag to orbit, scroll to zoom; use department and resident buttons to explore.",
  );
  renderer.domElement.setAttribute("role", "img");
  renderer.domElement.style.cssText =
    "display:block;width:100%;height:100%;outline:none;touch-action:none;";
  container.appendChild(renderer.domElement);

  const overlay = document.createElement("div");
  overlay.className = "society-scene-labels";
  overlay.style.cssText =
    "position:absolute;inset:0;pointer-events:none;overflow:hidden;";
  container.appendChild(overlay);
  const camera = new THREE.OrthographicCamera(-23, 23, 18, -18, 0.1, 120);
  const initialCamera = new THREE.Vector3(29, 30, 34);
  const initialTarget = new THREE.Vector3(0, 0, 0);
  camera.position.copy(initialCamera);
  camera.lookAt(initialTarget);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(initialTarget);
  controls.enableDamping = true;
  controls.dampingFactor = 0.065;
  controls.minPolarAngle = Math.PI / 4.4;
  controls.maxPolarAngle = Math.PI / 3.0;
  controls.minAzimuthAngle = -Math.PI / 4;
  controls.maxAzimuthAngle = Math.PI * 0.7;
  controls.minZoom = 0.72;
  controls.maxZoom = 2.6;
  controls.maxDistance = 80;
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.rotateSpeed = 0.42;
  controls.zoomSpeed = 0.65;
  controls.mouseButtons = {
    LEFT: THREE.MOUSE.ROTATE,
    MIDDLE: THREE.MOUSE.DOLLY,
    RIGHT: THREE.MOUSE.PAN,
  };

  const reducedMotionQuery = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  );
  let reducedMotion = reducedMotionQuery.matches;
  const onReducedMotion = () => {
    reducedMotion = reducedMotionQuery.matches;
  };
  reducedMotionQuery.addEventListener("change", onReducedMotion);
  let width = 1;
  let height = 1;
  let paused = false;
  let night = false;
  let labelsVisible = true;
  let selectedAgent: string | null = null;
  let hoveredAgent: string | null = null;
  let focusedDepartment: string | null = null;
  let disposed = false;
  let frame = 0;
  let elapsed = 0;
  let lastTime = performance.now();
  let targetFocus: THREE.Vector3 | null = null;
  let targetZoom: number | null = null;
  const resources = new Set<
    THREE.BufferGeometry | THREE.Material | THREE.Texture
  >();
  const materials = new Map<string, THREE.MeshStandardMaterial>();
  const geometries = new Map<string, THREE.BufferGeometry>();
  const nightMaterials: THREE.MeshStandardMaterial[] = [];
  const lampLights: THREE.PointLight[] = [];
  const pickables: THREE.Object3D[] = [];
  const citizens = new Map<string, Citizen>();
  const departments = new Map<string, Department>();
  const animatedFlags: THREE.Mesh[] = [];
  const animatedLeaves: THREE.Group[] = [];
  const waterRings: THREE.Mesh[] = [];
  const roofMaterials = new Map<number, THREE.MeshStandardMaterial>();
  const contactMaterials = new Map<number, THREE.MeshBasicMaterial>();
  let sharedWindowMaterial: THREE.MeshStandardMaterial | null = null;
  let sharedLampMaterial: THREE.MeshStandardMaterial | null = null;
  let sharedSelectionMaterial: THREE.MeshBasicMaterial | null = null;
  let sharedCharacterHitMaterial: THREE.MeshBasicMaterial | null = null;
  let needsRender = true;
  let lastRender = 0;
  let frameDuration = 0;
  const onControlsChange = () => {
    needsRender = true;
  };
  const onControlsStart = () => {
    targetFocus = null;
    targetZoom = null;
  };
  controls.addEventListener("change", onControlsChange);
  controls.addEventListener("start", onControlsStart);

  function material(color: number, roughness = 0.88, metalness = 0) {
    const key = `${color}-${roughness}-${metalness}`;
    if (!materials.has(key)) {
      const value = new THREE.MeshStandardMaterial({
        color,
        roughness,
        metalness,
      });
      materials.set(key, value);
      resources.add(value);
    }
    return materials.get(key)!;
  }

  function roofMaterial(color: number) {
    if (roofMaterials.has(color)) return roofMaterials.get(color)!;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 512;
    const ctx = canvas.getContext("2d")!;
    const base = new THREE.Color(color);
    ctx.fillStyle = `#${base.getHexString()}`;
    ctx.fillRect(0, 0, 512, 512);
    for (let row = 0; row < 12; row++) {
      for (let col = -1; col < 9; col++) {
        const x = col * 64 + (row % 2) * 32;
        const y = row * 43;
        const shade = base
          .clone()
          .multiplyScalar(0.94 + ((row * 31 + col * 13 + 7) % 11) * 0.012);
        ctx.fillStyle = `#${shade.getHexString()}`;
        ctx.fillRect(x + 1, y + 1, 62, 41);
        ctx.fillStyle = "rgba(65,39,31,.14)";
        ctx.fillRect(x, y + 40, 64, 2);
        ctx.fillStyle = "rgba(255,239,207,.1)";
        ctx.fillRect(x + 1, y + 1, 62, 1);
      }
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 8);
    resources.add(texture);
    const mat = new THREE.MeshStandardMaterial({
      map: texture,
      roughness: 0.95,
    });
    resources.add(mat);
    roofMaterials.set(color, mat);
    return mat;
  }

  function geometry(key: string, factory: () => THREE.BufferGeometry) {
    if (!geometries.has(key)) {
      const value = factory();
      geometries.set(key, value);
      resources.add(value);
    }
    return geometries.get(key)!;
  }

  function mesh(
    parent: THREE.Object3D,
    geo: THREE.BufferGeometry,
    mat: THREE.Material,
    x: number,
    y: number,
    z: number,
    cast = true,
  ) {
    const result = new THREE.Mesh(geo, mat);
    result.position.set(x, y, z);
    result.castShadow = cast;
    result.receiveShadow = true;
    parent.add(result);
    return result;
  }

  function box(
    parent: THREE.Object3D,
    w: number,
    h: number,
    d: number,
    x: number,
    y: number,
    z: number,
    color: number,
    radius = 0.04,
    cast = true,
  ) {
    const geo = geometry(`b-${w}-${h}-${d}-${radius}`, () =>
      radius > 0
        ? new RoundedBoxGeometry(
            w,
            h,
            d,
            2,
            Math.min(radius, w / 3, h / 3, d / 3),
          )
        : new THREE.BoxGeometry(w, h, d),
    );
    return mesh(parent, geo, material(color), x, y, z, cast);
  }

  function cylinder(
    parent: THREE.Object3D,
    r1: number,
    r2: number,
    h: number,
    x: number,
    y: number,
    z: number,
    color: number,
    segments = 16,
    cast = true,
  ) {
    return mesh(
      parent,
      geometry(
        `c-${r1}-${r2}-${h}-${segments}`,
        () => new THREE.CylinderGeometry(r1, r2, h, segments),
      ),
      material(color),
      x,
      y,
      z,
      cast,
    );
  }

  function sphere(
    parent: THREE.Object3D,
    radius: number,
    x: number,
    y: number,
    z: number,
    color: number,
    detail = 1,
  ) {
    return mesh(
      parent,
      geometry(
        `s-${radius}-${detail}`,
        () => new THREE.IcosahedronGeometry(radius, detail),
      ),
      material(color),
      x,
      y,
      z,
    );
  }

  function rod(
    parent: THREE.Object3D,
    a: THREE.Vector3,
    b: THREE.Vector3,
    radius: number,
    color: number,
  ) {
    const midpoint = a.clone().add(b).multiplyScalar(0.5);
    const object = cylinder(
      parent,
      radius,
      radius,
      a.distanceTo(b),
      midpoint.x,
      midpoint.y,
      midpoint.z,
      color,
      8,
    );
    object.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      b.clone().sub(a).normalize(),
    );
    return object;
  }

  function ring(
    parent: THREE.Object3D,
    inner: number,
    outer: number,
    x: number,
    y: number,
    z: number,
    color: number,
  ) {
    const value = mesh(
      parent,
      geometry(
        `r-${inner}-${outer}`,
        () => new THREE.RingGeometry(inner, outer, 64),
      ),
      material(color),
      x,
      y,
      z,
      false,
    );
    value.rotation.x = -Math.PI / 2;
    return value;
  }

  function softShadow(
    parent: THREE.Object3D,
    x: number,
    z: number,
    w: number,
    d: number,
    opacity = 0.2,
  ) {
    const key = "contact-shadow";
    let texture = scene.userData[key] as THREE.CanvasTexture | undefined;
    if (!texture) {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 64;
      const ctx = canvas.getContext("2d")!;
      const gradient = ctx.createRadialGradient(32, 32, 2, 32, 32, 32);
      gradient.addColorStop(0, "rgba(54,64,42,0.6)");
      gradient.addColorStop(0.4, "rgba(54,64,42,0.4)");
      gradient.addColorStop(1, "rgba(54,64,42,0)");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 64, 64);
      texture = new THREE.CanvasTexture(canvas);
      resources.add(texture);
      scene.userData[key] = texture;
    }
    let mat = contactMaterials.get(opacity);
    if (!mat) {
      mat = new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        opacity,
        depthWrite: false,
      });
      resources.add(mat);
      contactMaterials.set(opacity, mat);
    }
    const object = mesh(
      parent,
      geometry("shadow-plane", () => new THREE.PlaneGeometry(1, 1)),
      mat,
      x,
      0.055,
      z,
      false,
    );
    object.rotation.x = -Math.PI / 2;
    object.scale.set(w, d, 1);
    return object;
  }

  function textSign(
    parent: THREE.Object3D,
    text: string,
    w: number,
    h: number,
    x: number,
    y: number,
    z: number,
    color = "#f8f1db",
    ink = "#36514b",
  ) {
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = Math.max(64, Math.round((512 * h) / w));
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = ink;
    ctx.font = `600 ${Math.round(canvas.height * 0.42)}px "Arial", sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, canvas.width / 2, canvas.height * 0.54);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 8);
    resources.add(texture);
    const mat = new THREE.MeshStandardMaterial({
      map: texture,
      roughness: 0.8,
    });
    resources.add(mat);
    return mesh(
      parent,
      geometry(`sign-${w}-${h}`, () => new THREE.PlaneGeometry(w, h)),
      mat,
      x,
      y,
      z,
      false,
    );
  }

  function windowPane(
    parent: THREE.Object3D,
    x: number,
    y: number,
    z: number,
    w: number,
    h: number,
  ) {
    box(parent, w + 0.13, h + 0.13, 0.1, x, y, z, C.ivory, 0.035);
    if (!sharedWindowMaterial) {
      sharedWindowMaterial = new THREE.MeshStandardMaterial({
        color: C.window,
        roughness: 0.38,
        metalness: 0.1,
        emissive: 0xffc980,
        emissiveIntensity: 0,
      });
      nightMaterials.push(sharedWindowMaterial);
      resources.add(sharedWindowMaterial);
    }
    const paneMat = sharedWindowMaterial;
    const pane = mesh(
      parent,
      geometry(`pane-${w}-${h}`, () => new THREE.BoxGeometry(w, h, 0.04)),
      paneMat,
      x,
      y,
      z + 0.061,
    );
    box(parent, 0.045, h, 0.045, x, y, z + 0.09, C.ivory, 0.008);
    box(parent, w, 0.04, 0.045, x, y + h * 0.1, z + 0.09, C.ivory, 0.008);
    box(
      parent,
      w + 0.28,
      0.09,
      0.27,
      x,
      y - h / 2 - 0.1,
      z + 0.05,
      C.stone,
      0.025,
    );
    return pane;
  }

  function planter(
    parent: THREE.Object3D,
    x: number,
    z: number,
    color = C.terracotta,
    scale = 1,
    y = 0,
  ) {
    cylinder(
      parent,
      0.26 * scale,
      0.19 * scale,
      0.42 * scale,
      x,
      y + 0.21 * scale,
      z,
      color,
      12,
    );
    cylinder(
      parent,
      0.27 * scale,
      0.27 * scale,
      0.08 * scale,
      x,
      y + 0.41 * scale,
      z,
      color,
      12,
    );
    cylinder(
      parent,
      0.22 * scale,
      0.22 * scale,
      0.02,
      x,
      y + 0.455 * scale,
      z,
      C.wood,
      12,
      false,
    );
    for (let i = 0; i < 5; i++) {
      const angle = (i * Math.PI * 2) / 5;
      const leaf = sphere(
        parent,
        0.16 * scale,
        x + Math.cos(angle) * 0.12 * scale,
        y + 0.58 * scale,
        z + Math.sin(angle) * 0.12 * scale,
        i % 2 ? C.foliage : C.foliageLight,
        0,
      );
      leaf.scale.set(0.75, 1.9, 0.7);
      leaf.rotation.z = -Math.cos(angle) * 0.45;
      leaf.rotation.x = Math.sin(angle) * 0.45;
    }
  }

  function tree(x: number, z: number, scale = 1, type = 0) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);
    group.scale.setScalar(scale);
    scene.add(group);
    softShadow(group, 0.25, 0.2, 2.8, 2.8, 0.28);
    cylinder(group, 0.12, 0.17, 1.45, 0, 0.7, 0, C.wood, 7);
    const leaves = new THREE.Group();
    leaves.position.y = 1.55;
    group.add(leaves);
    if (type === 1) {
      for (let i = 0; i < 3; i++)
        cylinder(
          leaves,
          0.05,
          0.74 - i * 0.16,
          1.2 - i * 0.13,
          0,
          i * 0.48,
          0,
          [C.foliageDark, C.foliage, C.foliageLight][i]!,
          7,
        );
    } else {
      sphere(leaves, 0.82, 0, 0.5, 0, C.foliage, 1).scale.set(1, 1.1, 0.9);
      sphere(leaves, 0.62, -0.45, 0.3, 0.25, C.foliageDark, 1);
      sphere(leaves, 0.62, 0.37, 0.75, 0.09, C.foliageLight, 1);
      sphere(leaves, 0.57, 0.35, 0.25, -0.3, C.foliage, 1);
      rod(
        group,
        new THREE.Vector3(0, 0.9, 0),
        new THREE.Vector3(-0.5, 1.8, 0.2),
        0.07,
        C.wood,
      );
    }
    leaves.userData.phase = x * 3.7 + z;
    animatedLeaves.push(leaves);
    return group;
  }

  function shrub(
    parent: THREE.Object3D,
    x: number,
    z: number,
    scale = 1,
    y = 0.34,
  ) {
    const value = sphere(parent, 0.45, x, y, z, C.foliageDark, 1);
    value.scale.set(scale, 0.7 * scale, 0.75 * scale);
    sphere(
      parent,
      0.32 * scale,
      x - 0.23 * scale,
      y + 0.08,
      z + 0.04,
      C.foliage,
      1,
    );
  }

  function flowers(
    parent: THREE.Object3D,
    x: number,
    z: number,
    color = C.yellow,
  ) {
    for (let i = 0; i < 4; i++) {
      const px = x + ((i % 2) - 0.5) * 0.22;
      const pz = z + (Math.floor(i / 2) - 0.5) * 0.2;
      cylinder(
        parent,
        0.015,
        0.02,
        0.27,
        px,
        0.15,
        pz,
        C.foliageDark,
        5,
        false,
      );
      sphere(parent, 0.065, px, 0.31 + i * 0.015, pz, color, 0);
    }
  }

  function bench(parent: THREE.Object3D, x: number, z: number, rotation = 0) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);
    group.rotation.y = rotation;
    parent.add(group);
    for (const px of [-0.49, 0.49]) {
      box(group, 0.07, 0.45, 0.43, px, 0.24, 0, C.metal, 0.01);
      box(group, 0.07, 0.61, 0.07, px, 0.54, -0.19, C.metal, 0.01);
    }
    for (let i = 0; i < 3; i++)
      box(
        group,
        1.3,
        0.07,
        0.11,
        0,
        0.48,
        -0.14 + i * 0.14,
        C.woodLight,
        0.025,
      );
    for (let i = 0; i < 2; i++)
      box(group, 1.3, 0.13, 0.055, 0, 0.69 + i * 0.17, -0.2, C.woodLight, 0.02);
    return group;
  }

  function lamp(x: number, z: number) {
    cylinder(scene, 0.15, 0.21, 0.15, x, 0.075, z, C.metal, 8);
    cylinder(scene, 0.043, 0.07, 1.85, x, 0.95, z, C.metal, 8);
    cylinder(scene, 0.21, 0.28, 0.12, x, 2.07, z, C.dark, 8);
    if (!sharedLampMaterial) {
      sharedLampMaterial = new THREE.MeshStandardMaterial({
        color: 0xffedbb,
        emissive: 0xffc573,
        emissiveIntensity: 0.25,
        roughness: 0.5,
      });
      resources.add(sharedLampMaterial);
      nightMaterials.push(sharedLampMaterial);
    }
    const lightMat = sharedLampMaterial;
    mesh(
      scene,
      geometry("lantern", () => new THREE.CylinderGeometry(0.13, 0.1, 0.26, 8)),
      lightMat,
      x,
      1.9,
      z,
    );
    // Two courtyard lights provide the night glow; the other lanterns share an emissive material.
    if (lampLights.length < 2) {
      const light = new THREE.PointLight(0xffca82, 0, 6.5, 2);
      light.position.set(x, 1.82, z);
      scene.add(light);
      lampLights.push(light);
    }
  }

  const hemisphere = new THREE.HemisphereLight(0xf8f4de, 0xa0ae85, 1.5);
  scene.add(hemisphere);
  const sun = new THREE.DirectionalLight(0xffebcd, 2.6);
  sun.position.set(-13, 24, 8);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -23;
  sun.shadow.camera.right = 23;
  sun.shadow.camera.top = 23;
  sun.shadow.camera.bottom = -23;
  sun.shadow.camera.near = 0.1;
  sun.shadow.camera.far = 65;
  sun.shadow.normalBias = 0.04;
  sun.shadow.bias = -0.0003;
  sun.shadow.radius = 4;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xd9e8ed, 0.7);
  fill.position.set(14, 10, -16);
  scene.add(fill);

  // The beveled plinth and irregular planted edge make the scene feel like a physical model.
  const backdropShadow = new THREE.ShadowMaterial({
    color: 0x495342,
    opacity: 0.18,
  });
  resources.add(backdropShadow);
  const backdrop = mesh(
    scene,
    geometry("backdrop", () => new THREE.PlaneGeometry(180, 180)),
    backdropShadow,
    0,
    -1.46,
    0,
    false,
  );
  backdrop.rotation.x = -Math.PI / 2;
  box(scene, 31.3, 0.2, 24.8, 0, -1.12, 0, C.wood, 0.55);
  box(scene, 31.6, 0.91, 25.1, 0, -0.7, 0, C.stoneEdge, 0.7);
  box(scene, 31.7, 0.2, 25.2, 0, -0.17, 0, C.stone, 0.5);
  box(scene, 31.15, 0.16, 24.65, 0, -0.025, 0, C.grass, 0.48);
  box(scene, 29.8, 0.025, 23.3, 0, 0.07, 0, C.grassLight, 0.4, false);
  for (let i = 0; i < 18; i++)
    box(
      scene,
      1.53,
      0.31,
      0.035,
      -13.62 + i * 1.6,
      -0.63,
      12.553,
      i % 3 ? C.stoneEdge : C.stone,
      0.024,
      false,
    );
  for (let i = 0; i < 14; i++)
    box(
      scene,
      0.035,
      0.31,
      1.51,
      15.803,
      -0.63,
      -10.42 + i * 1.6,
      i % 4 ? C.stoneEdge : C.stone,
      0.024,
      false,
    );
  for (const z of [-10.8, 10.8])
    box(scene, 27.9, 0.02, 0.47, 0, 0.09, z, C.path, 0.15, false);
  for (const x of [-13.75, 13.75])
    box(scene, 0.47, 0.02, 21.6, x, 0.09, 0, C.path, 0.15, false);

  // Broad radial walkways connect every department to a paved circular town square.
  cylinder(scene, 5.15, 5.15, 0.035, 0, 0.09, 0, C.pathLine, 96, false);
  cylinder(scene, 4.98, 4.98, 0.045, 0, 0.11, 0, C.path, 96, false);
  ring(scene, 3.38, 3.42, 0, 0.141, 0, C.pathLine);
  ring(scene, 4.49, 4.52, 0, 0.142, 0, C.pathLine);
  for (let i = 0; i < 24; i++) {
    const angle = (i * Math.PI) / 12;
    const mark = box(
      scene,
      0.025,
      0.012,
      1.48,
      Math.sin(angle) * 4.2,
      0.143,
      Math.cos(angle) * 4.2,
      C.pathLine,
      0,
      false,
    );
    mark.rotation.y = angle;
  }

  function departmentBase(spec: (typeof DEPARTMENTS)[number]) {
    const group = new THREE.Group();
    const angle = Math.atan2(-spec.x, -spec.z);
    group.position.set(spec.x, 0, spec.z);
    group.rotation.y = angle;
    scene.add(group);
    group.userData.department = spec.id;
    const distance = Math.hypot(spec.x, spec.z);
    const path = box(
      scene,
      1.35,
      0.03,
      distance - 3.1,
      ((spec.x / distance) * (distance + 3.1)) / 2,
      0.095,
      ((spec.z / distance) * (distance + 3.1)) / 2,
      C.path,
      0.11,
      false,
    );
    path.rotation.y = Math.atan2(spec.x, spec.z);
    box(group, 5.5, 0.12, 4.5, 0, 0.115, 0, C.pathLine, 0.22);
    box(group, 5.34, 0.1, 4.35, 0, 0.21, 0, C.path, 0.18);
    softShadow(group, 0.3, 0.2, 6.2, 5.2, 0.48);
    // The front terrace has low steps and a visible welcome mat.
    box(group, 1.65, 0.1, 0.46, 0, 0.13, 2.35, C.stone, 0.025);
    box(group, 1.38, 0.06, 0.45, 0, 0.22, 2.15, spec.color, 0.025);
    planter(group, -2.3, 1.78, C.ivory, 0.92, 0.25);
    planter(group, 2.3, 1.78, C.ivory, 0.92, 0.25);
    const worldPoint = (x: number, y: number, z: number) =>
      new THREE.Vector3(x, y, z)
        .applyAxisAngle(new THREE.Vector3(0, 1, 0), angle)
        .add(group.position);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "society-department-label";
    button.setAttribute("aria-label", `Explore ${spec.name} department`);
    button.style.cssText =
      "position:absolute;left:0;top:0;display:flex;align-items:center;gap:6px;min-height:27px;padding:5px 8px;border:1px solid rgba(255,255,255,.88);border-radius:7px;background:rgba(253,252,245,.94);box-shadow:0 3px 10px rgba(52,67,43,.09);color:#37473e;font-weight:600;line-height:1.2;font-family:inherit;font-size:10px;white-space:nowrap;pointer-events:auto;cursor:pointer;will-change:transform;";
    const dot = document.createElement("span");
    dot.style.cssText = `width:6px;height:6px;flex:none;border-radius:2px;background:#${spec.color.toString(16)};`;
    const name = document.createElement("span");
    name.textContent = spec.name;
    const count = document.createElement("span");
    count.style.cssText =
      "display:none;font-size:10px;color:#7b887b;border-left:1px solid #e4e5da;padding-left:6px;";
    button.append(dot, name, count);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      callbacks.onSelectDepartment?.(spec.id);
    });
    overlay.appendChild(button);
    const department: Department = {
      ...spec,
      rotation: angle,
      group,
      label: worldPoint(0, 3.95, 0),
      entrance: worldPoint(0, 0.13, 3.15),
      button,
      count,
    };
    departments.set(spec.id, department);
    return group;
  }

  function basicBuilding(
    parent: THREE.Group,
    color: number,
    h = 2.15,
    w = 4.25,
    d = 3.15,
  ) {
    const plaster = new THREE.Color(color)
      .lerp(new THREE.Color(C.ivory), 0.68)
      .getHex();
    box(parent, w, h, d, 0, 0.28 + h / 2, 0, plaster, 0.09);
    box(parent, w + 0.1, 0.21, d + 0.1, 0, 0.4, 0, C.stone, 0.06);
    box(parent, w + 0.24, 0.18, d + 0.25, 0, h + 0.29, 0, color, 0.06);
    box(parent, 0.72, 1.24, 0.09, 0, 0.91, d / 2 + 0.025, C.wood, 0.035);
    box(parent, 0.49, 0.73, 0.035, 0, 1.08, d / 2 + 0.09, C.window, 0.02);
    sphere(parent, 0.04, 0.25, 0.85, d / 2 + 0.12, C.yellow, 1);
    for (const x of [-1.31, 1.31])
      windowPane(parent, x, 1.35, d / 2 + 0.04, 0.73, 0.92);
    const sideWindows = new THREE.Group();
    sideWindows.position.x = w / 2 + 0.04;
    sideWindows.rotation.y = Math.PI / 2;
    parent.add(sideWindows);
    for (const x of [-0.78, 0.78])
      windowPane(sideWindows, x, 1.36, 0, 0.68, 0.9);
    // Every elevation is finished: the free camera never finds a blank cardboard back.
    const rear = new THREE.Group();
    rear.position.z = -d / 2 - 0.04;
    rear.rotation.y = Math.PI;
    parent.add(rear);
    box(rear, w - 0.16, 0.43, 0.07, 0, 0.69, 0, color, 0.015);
    for (const x of [-1.32, 0, 1.32]) {
      windowPane(rear, x, 1.35, 0.055, 0.69, Math.min(h * 0.46, 0.87));
      box(rear, 0.81, 0.2, 0.31, x, 0.85, 0.15, C.woodLight, 0.04);
      for (let i = 0; i < 3; i++)
        sphere(
          rear,
          0.14,
          x - 0.22 + i * 0.22,
          1.02,
          0.18,
          i % 2 ? C.foliageDark : C.foliage,
          0,
        );
    }
    const otherSide = new THREE.Group();
    otherSide.position.x = -w / 2 - 0.04;
    otherSide.rotation.y = -Math.PI / 2;
    parent.add(otherSide);
    for (const x of [-0.78, 0.78])
      windowPane(otherSide, x, 1.3, 0, 0.65, Math.min(h * 0.47, 0.88));
  }

  function gabledRoof(
    parent: THREE.Object3D,
    w: number,
    d: number,
    y: number,
    rise: number,
    color: number,
  ) {
    const slope = Math.atan2(rise, w / 2);
    const length = Math.hypot(w / 2, rise);
    for (const side of [-1, 1]) {
      const panel = box(
        parent,
        length,
        0.15,
        d,
        (side * w) / 4,
        y + rise / 2,
        0,
        color,
        0.03,
      );
      panel.material = roofMaterial(color);
      panel.rotation.z = -side * slope;
      for (let j = 0; j < 6; j++) {
        const strip = box(
          parent,
          length,
          0.025,
          0.035,
          (side * w) / 4,
          y + rise / 2 + 0.08,
          -d / 2 + 0.2 + (j * (d - 0.4)) / 5,
          color,
          0.01,
        );
        strip.rotation.z = -side * slope;
      }
    }
    box(parent, 0.16, 0.15, d + 0.05, 0, y + rise + 0.015, 0, color, 0.055);
  }

  function desk(
    parent: THREE.Object3D,
    x: number,
    z: number,
    rotation = 0,
    y = 0.28,
  ) {
    const group = new THREE.Group();
    group.position.set(x, y, z);
    group.rotation.y = rotation;
    parent.add(group);
    box(group, 1.0, 0.09, 0.6, 0, 0.65, 0, C.woodLight, 0.04);
    for (const px of [-0.4, 0.4])
      for (const pz of [-0.22, 0.22])
        box(group, 0.05, 0.62, 0.05, px, 0.31, pz, C.ivory, 0.01);
    box(group, 0.44, 0.31, 0.055, 0, 0.99, -0.12, C.dark, 0.025);
    box(group, 0.38, 0.245, 0.018, 0, 1.0, -0.081, C.windowLight, 0.01);
    box(group, 0.035, 0.14, 0.035, 0, 0.78, -0.12, C.metal, 0.006);
    box(group, 0.22, 0.025, 0.14, 0, 0.713, -0.12, C.metal, 0.012);
    box(group, 0.32, 0.025, 0.13, 0, 0.715, 0.13, C.ivory, 0.015);
    cylinder(group, 0.055, 0.045, 0.1, 0.35, 0.75, 0.05, C.terracotta, 10);
    // A swivel chair gives the glass-sided studios a human scale.
    box(group, 0.37, 0.08, 0.35, 0, 0.41, 0.62, C.teal, 0.06);
    box(group, 0.37, 0.37, 0.07, 0, 0.62, 0.77, C.teal, 0.05);
    cylinder(group, 0.035, 0.035, 0.35, 0, 0.19, 0.62, C.metal, 8);
    box(group, 0.45, 0.045, 0.045, 0, 0.04, 0.62, C.metal, 0.01);
    box(group, 0.045, 0.045, 0.45, 0, 0.04, 0.62, C.metal, 0.01);
  }

  // Headquarters: a terracotta pavilion with a clock tower and a proper front porch.
  {
    const group = departmentBase(DEPARTMENTS[1]);
    basicBuilding(group, C.terracotta, 2.15);
    gabledRoof(group, 4.8, 3.7, 2.5, 0.93, C.terracotta);
    box(group, 1.04, 2.9, 1.02, 0, 4.05, -0.05, C.ivory, 0.07);
    box(group, 1.18, 0.14, 1.15, 0, 4.26, -0.05, C.terracotta, 0.04);
    box(group, 1.15, 0.14, 1.15, 0, 5.47, -0.05, C.stone, 0.04);
    gabledRoof(group, 1.45, 1.5, 5.56, 0.57, C.teal);
    windowPane(group, 0, 3.82, 0.49, 0.33, 0.62);
    const towerSide = new THREE.Group();
    towerSide.position.set(0.535, 0, -0.05);
    towerSide.rotation.y = Math.PI / 2;
    group.add(towerSide);
    windowPane(towerSide, 0, 3.82, 0, 0.33, 0.62);
    const clock = cylinder(group, 0.34, 0.34, 0.06, 0, 4.95, 0.49, C.ivory, 32);
    clock.rotation.x = Math.PI / 2;
    const clockFrame = mesh(
      group,
      geometry(
        "clock-frame",
        () => new THREE.TorusGeometry(0.344, 0.036, 6, 32),
      ),
      material(C.wood),
      0,
      4.95,
      0.53,
    );
    clockFrame.rotation.z = 0;
    box(group, 0.036, 0.22, 0.02, 0, 5.04, 0.55, C.dark, 0.008);
    const hand = box(
      group,
      0.21,
      0.032,
      0.02,
      0.08,
      4.925,
      0.55,
      C.dark,
      0.008,
    );
    hand.rotation.z = -0.35;
    for (let i = 0; i < 12; i++) {
      const a = (i * Math.PI) / 6;
      const tick = box(
        group,
        0.019,
        0.044,
        0.02,
        Math.sin(a) * 0.278,
        4.95 + Math.cos(a) * 0.278,
        0.555,
        C.wood,
        0.005,
      );
      tick.rotation.z = -a;
    }
    rod(
      group,
      new THREE.Vector3(0, 6.09, 0),
      new THREE.Vector3(0, 6.58, 0),
      0.023,
      C.wood,
    );
    sphere(group, 0.085, 0, 6.35, 0, C.yellow, 1);
    box(group, 0.63, 0.075, 0.035, 0, 6.51, 0, C.yellow, 0.015);
    box(group, 1.8, 0.15, 0.72, 0, 1.83, 1.8, C.terracotta, 0.04);
    for (const x of [-0.75, 0.75])
      cylinder(group, 0.065, 0.08, 1.49, x, 1.03, 2.06, C.ivory, 8);
    textSign(group, "SOCIETY HALL", 1.42, 0.26, 0, 2.17, 1.637);
    departments.get("headquarters")!.label.y = 6.9;
    for (const x of [-2.13, 2.13]) flowers(group, x, 2.75, C.terracotta);
  }

  // Research: a blue observatory, telescope and a sunlit laboratory conservatory.
  {
    const group = departmentBase(DEPARTMENTS[0]);
    basicBuilding(group, C.blue, 2.05);
    box(group, 4.5, 0.14, 3.4, 0, 2.4, 0, C.blue, 0.08);
    cylinder(group, 1.18, 1.24, 0.35, -0.38, 2.64, -0.16, C.ivory, 40);
    const dome = mesh(
      group,
      geometry(
        "observatory-dome",
        () =>
          new THREE.SphereGeometry(1.2, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2),
      ),
      material(C.blue, 0.55),
      -0.38,
      2.78,
      -0.16,
    );
    dome.scale.y = 0.82;
    const band = mesh(
      group,
      geometry(
        "dome-band",
        () => new THREE.TorusGeometry(1.203, 0.038, 6, 48, Math.PI),
      ),
      material(C.ivory),
      -0.38,
      2.77,
      -0.16,
    );
    band.rotation.y = Math.PI / 2;
    band.scale.y = 0.82;
    rod(
      group,
      new THREE.Vector3(-0.2, 3.38, 0.3),
      new THREE.Vector3(0.1, 3.85, 0.85),
      0.17,
      C.ivory,
    );
    const lens = cylinder(group, 0.2, 0.2, 0.15, 0.1, 3.85, 0.85, C.dark, 16);
    lens.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(0.3, 0.47, 0.55).normalize(),
    );
    textSign(group, "DISCOVERY LAB", 1.63, 0.28, 0, 2.02, 1.644);
    cylinder(group, 0.11, 0.16, 0.85, 1.55, 2.9, -0.83, C.stone, 12);
    sphere(group, 0.18, 1.55, 3.39, -0.83, C.yellow, 1);
    // A whiteboard outside the lab, covered in a small constellation diagram.
    box(group, 0.78, 0.69, 0.06, 1.15, 0.94, 2.09, C.ivory, 0.03);
    for (const x of [0.84, 1.46])
      box(group, 0.04, 0.63, 0.04, x, 0.43, 2.08, C.wood, 0.01);
    for (let i = 0; i < 4; i++)
      sphere(
        group,
        0.035,
        0.91 + i * 0.15,
        0.95 + Math.sin(i * 2) * 0.15,
        2.135,
        C.blue,
        1,
      );
    departments.get("research")!.label.y = 4.15;
  }

  // Engineering is a cutaway maker studio: desks, servers, gantry, planted roof and solar array.
  {
    const group = departmentBase(DEPARTMENTS[2]);
    box(group, 4.3, 0.15, 3.25, 0, 0.35, 0, C.stone, 0.06);
    box(group, 4.2, 2.05, 0.19, 0, 1.41, -1.48, C.teal, 0.05);
    box(group, 0.18, 2.05, 3.04, -2.01, 1.41, -0.03, C.ivory, 0.05);
    box(group, 0.18, 0.82, 3.04, 2.01, 0.8, -0.03, C.ivory, 0.05);
    box(group, 4.52, 0.2, 1.54, 0, 2.49, -0.82, C.teal, 0.06);
    for (const x of [-1.9, 1.9])
      box(group, 0.12, 2.02, 0.12, x, 1.4, 1.38, C.teal, 0.025);
    box(group, 4.42, 0.17, 0.17, 0, 2.46, 1.38, C.teal, 0.03);
    for (let i = 0; i < 6; i++)
      box(
        group,
        0.065,
        0.08,
        1.6,
        -1.9 + i * 0.76,
        2.46,
        0.58,
        C.woodLight,
        0.012,
      );
    desk(group, -1.03, -0.52, 0);
    desk(group, 0.32, -0.52, 0);
    box(group, 0.6, 1.5, 0.53, 1.42, 1.14, -1.0, C.dark, 0.055);
    for (let i = 0; i < 6; i++) {
      box(
        group,
        0.48,
        0.15,
        0.035,
        1.42,
        0.57 + i * 0.205,
        -0.718,
        C.metal,
        0.012,
      );
      sphere(
        group,
        0.025,
        1.58,
        0.57 + i * 0.205,
        -0.688,
        i % 3 === 0 ? C.yellow : C.grassLight,
        0,
      );
    }
    for (let i = 0; i < 2; i++) {
      const panel = new THREE.Group();
      panel.position.set(-0.95 + i * 1.72, 2.67, -0.93);
      panel.rotation.x = -0.13;
      group.add(panel);
      box(panel, 1.46, 0.08, 1.0, 0, 0, 0, C.ivory, 0.015);
      box(panel, 1.36, 0.02, 0.9, 0, 0.052, 0, 0x527784, 0.006);
      for (let j = 1; j < 4; j++)
        box(
          panel,
          0.018,
          0.011,
          0.9,
          -0.68 + j * 0.34,
          0.068,
          0,
          0x92b1b5,
          0,
          false,
        );
      box(panel, 1.36, 0.011, 0.016, 0, 0.068, 0, 0x92b1b5, 0, false);
    }
    textSign(group, "THE WORKSHOP", 1.64, 0.27, 0, 2.45, 1.48);
    planter(group, 1.56, 0.87, C.terracotta, 0.76, 0.42);
    // An outdoor diagnostic terminal is visible even from the wide campus view.
    const terminal = new THREE.Group();
    terminal.position.set(-1.27, 0.26, 2.38);
    terminal.rotation.y = 0.2;
    group.add(terminal);
    box(terminal, 0.61, 0.12, 0.52, 0, 0.06, 0, C.stone, 0.04);
    box(terminal, 0.34, 0.83, 0.24, 0, 0.5, 0, C.teal, 0.06);
    const screen = box(terminal, 0.67, 0.45, 0.12, 0, 1.03, 0, C.dark, 0.045);
    screen.rotation.x = -0.14;
    box(terminal, 0.54, 0.32, 0.035, 0, 1.05, 0.079, C.windowLight, 0.025);
    for (let i = 0; i < 3; i++)
      box(
        terminal,
        0.09 + i * 0.06,
        0.025,
        0.017,
        -0.11,
        1.15 - i * 0.09,
        0.102,
        C.teal,
        0.005,
      );
    departments.get("engineering")!.label.y = 3.5;
  }

  // Communications: a mustard radio house, rooftop satellite and a striped cafe awning.
  {
    const group = departmentBase(DEPARTMENTS[3]);
    basicBuilding(group, C.yellow, 1.98);
    box(group, 4.45, 0.22, 3.42, 0, 2.37, 0, C.yellow, 0.09);
    box(group, 4.05, 0.08, 3.02, 0, 2.52, 0, C.stone, 0.04);
    cylinder(group, 0.065, 0.065, 1.6, -1.13, 3.28, -0.2, C.metal, 8);
    for (let i = 0; i < 3; i++)
      box(
        group,
        0.95 - i * 0.22,
        0.035,
        0.035,
        -1.13,
        3.52 + i * 0.22,
        -0.2,
        C.metal,
        0.008,
      );
    sphere(group, 0.07, -1.13, 4.13, -0.2, C.terracotta, 1);
    const dishGroup = new THREE.Group();
    dishGroup.position.set(0.8, 2.92, -0.25);
    dishGroup.rotation.x = -0.65;
    dishGroup.rotation.z = -0.25;
    group.add(dishGroup);
    const dishMat = new THREE.MeshStandardMaterial({
      color: C.ivory,
      roughness: 0.65,
      side: THREE.DoubleSide,
    });
    resources.add(dishMat);
    const dish = mesh(
      dishGroup,
      geometry(
        "satellite",
        () => new THREE.SphereGeometry(0.65, 24, 12, 0, Math.PI * 2, 0, 0.9),
      ),
      dishMat,
      0,
      0,
      0,
    );
    dish.rotation.x = Math.PI;
    rod(
      dishGroup,
      new THREE.Vector3(-0.45, -0.41, 0),
      new THREE.Vector3(0, -0.92, 0),
      0.025,
      C.metal,
    );
    rod(
      dishGroup,
      new THREE.Vector3(0.45, -0.41, 0),
      new THREE.Vector3(0, -0.92, 0),
      0.025,
      C.metal,
    );
    cylinder(group, 0.09, 0.15, 0.5, 0.8, 2.75, -0.25, C.metal, 8);
    for (let i = 0; i < 9; i++) {
      const awning = box(
        group,
        0.43,
        0.065,
        0.83,
        -1.72 + i * 0.43,
        1.97,
        1.87,
        i % 2 ? C.ivory : C.yellow,
        0.018,
      );
      awning.rotation.x = 0.15;
      box(
        group,
        0.43,
        0.14,
        0.04,
        -1.72 + i * 0.43,
        1.81,
        2.28,
        i % 2 ? C.ivory : C.yellow,
        0.017,
      );
    }
    textSign(group, "THE COMMONS", 1.6, 0.25, 0, 2.33, 1.73);
    departments.get("communications")!.label.y = 4.25;
  }

  // Knowledge: a small rose-colored library with arched glazing and a roof garden.
  {
    const group = departmentBase(DEPARTMENTS[5]);
    basicBuilding(group, C.pink, 1.93);
    box(group, 4.5, 0.18, 3.42, 0, 2.31, 0, C.pink, 0.06);
    box(group, 4.08, 0.08, 3.02, 0, 2.43, 0, C.grassDark, 0.03);
    for (const x of [-2.04, 2.04])
      box(group, 0.12, 0.27, 3.07, x, 2.58, 0, C.ivory, 0.025);
    box(group, 4.2, 0.27, 0.12, 0, 2.58, -1.48, C.ivory, 0.025);
    box(group, 4.2, 0.14, 0.12, 0, 2.51, 1.48, C.ivory, 0.025);
    for (let i = 0; i < 4; i++)
      shrub(group, -1.45 + i * 0.88, -0.98, 0.73, 2.75);
    // The roof reading deck has a slatted pergola and stacks of books.
    for (const x of [-1.44, 1.44])
      for (const z of [-0.51, 1.0])
        box(group, 0.085, 0.95, 0.085, x, 2.93, z, C.woodLight, 0.015);
    for (let i = 0; i < 7; i++)
      box(
        group,
        3.25,
        0.08,
        0.12,
        0,
        3.45,
        -0.64 + i * 0.3,
        C.woodLight,
        0.016,
      );
    const roofBench = bench(group, 0.7, 0.22, -Math.PI / 2);
    roofBench.position.y = 2.49;
    box(group, 0.63, 0.08, 0.63, -0.45, 2.97, 0.25, C.ivory, 0.045);
    cylinder(group, 0.055, 0.055, 0.43, -0.45, 2.73, 0.25, C.metal, 8);
    for (let i = 0; i < 3; i++)
      box(
        group,
        0.28,
        0.045,
        0.2,
        -0.45,
        3.04 + i * 0.05,
        0.25,
        [C.blue, C.terracotta, C.yellow][i]!,
        0.005,
      );
    textSign(group, "THE ARCHIVE", 1.5, 0.27, 0, 1.98, 1.646);
    // A freestanding book-return box beside the entrance.
    box(group, 0.39, 0.65, 0.36, -1.86, 0.58, 2.17, C.teal, 0.045);
    box(group, 0.27, 0.07, 0.025, -1.86, 0.73, 2.36, C.dark, 0.005);
    departments.get("knowledge")!.label.y = 3.92;
  }

  // Operations: a low logistics depot with a loading terrace, batteries and freight.
  {
    const group = departmentBase(DEPARTMENTS[4]);
    basicBuilding(group, C.purple, 1.67);
    gabledRoof(group, 4.7, 3.62, 1.98, 0.47, C.purple);
    box(group, 1.38, 1.25, 0.12, 0, 0.97, 1.64, C.metal, 0.025);
    for (let i = 0; i < 8; i++)
      box(
        group,
        1.27,
        0.025,
        0.025,
        0,
        0.45 + i * 0.144,
        1.715,
        C.windowLight,
        0.004,
      );
    textSign(group, "MISSION CONTROL", 2.0, 0.26, 0, 1.81, 1.655);
    for (let i = 0; i < 3; i++) {
      box(
        group,
        0.42,
        0.4,
        0.42,
        1.3 + (i % 2) * 0.47,
        0.49 + Math.floor(i / 2) * 0.4,
        1.99,
        C.woodLight,
        0.025,
      );
      box(
        group,
        0.12,
        0.42,
        0.43,
        1.3 + (i % 2) * 0.47,
        0.49 + Math.floor(i / 2) * 0.4,
        1.99,
        C.stone,
        0.005,
      );
    }
    box(group, 0.61, 0.76, 0.51, -1.48, 0.66, 2.12, C.purple, 0.065);
    box(group, 0.36, 0.2, 0.035, -1.48, 0.79, 2.39, C.dark, 0.015);
    cylinder(group, 0.055, 0.055, 0.72, -1.8, 2.34, -0.58, C.metal, 10);
    cylinder(group, 0.14, 0.2, 0.15, -1.8, 2.75, -0.58, C.ivory, 10);
    // The logistics cart sits on the outer terrace, so the depot has activity on both elevations.
    const cart = new THREE.Group();
    cart.position.set(1.15, 0.27, -2.22);
    cart.rotation.y = 0.16;
    group.add(cart);
    box(cart, 1.12, 0.09, 0.61, 0, 0.24, 0, C.purple, 0.035);
    for (const x of [-0.4, 0.4])
      for (const z of [-0.2, 0.2]) {
        const wheel = cylinder(cart, 0.11, 0.11, 0.07, x, 0.12, z, C.dark, 12);
        wheel.rotation.x = Math.PI / 2;
      }
    for (const z of [-0.25, 0.25])
      box(cart, 0.045, 0.64, 0.045, -0.52, 0.59, z, C.metal, 0.01);
    box(cart, 0.055, 0.055, 0.57, -0.52, 0.91, 0, C.metal, 0.01);
    for (let i = 0; i < 3; i++) {
      box(
        cart,
        0.34,
        0.29,
        0.38,
        -0.18 + (i % 2) * 0.4,
        0.425 + Math.floor(i / 2) * 0.3,
        0,
        C.woodLight,
        0.025,
      );
      box(
        cart,
        0.08,
        0.3,
        0.39,
        -0.18 + (i % 2) * 0.4,
        0.425 + Math.floor(i / 2) * 0.3,
        0,
        C.stone,
        0.005,
      );
    }
    departments.get("operations")!.label.y = 3.15;
  }

  // Fine-grained architecture picking is independent from the character hit targets.
  for (const department of departments.values()) {
    department.group.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        object.userData.department = department.id;
        pickables.push(object);
      }
    });
  }

  // The plaza's fountain is the social heart of the campus.
  cylinder(scene, 2.32, 2.38, 0.14, 0, 0.19, 0, C.stoneEdge, 64);
  cylinder(scene, 2.17, 2.23, 0.15, 0, 0.32, 0, C.ivory, 64);
  cylinder(scene, 1.93, 1.98, 0.1, 0, 0.43, 0, C.water, 64);
  const basinRim = mesh(
    scene,
    geometry("fountain-rim", () => new THREE.TorusGeometry(2.08, 0.16, 8, 64)),
    material(C.stone),
    0,
    0.48,
    0,
  );
  basinRim.rotation.x = Math.PI / 2;
  cylinder(scene, 0.39, 0.62, 0.62, 0, 0.71, 0, C.ivory, 16);
  cylinder(scene, 0.98, 0.69, 0.13, 0, 1.07, 0, C.stone, 40);
  cylinder(scene, 0.85, 0.85, 0.025, 0, 1.145, 0, C.water, 40);
  cylinder(scene, 0.15, 0.25, 0.54, 0, 1.42, 0, C.ivory, 16);
  sphere(scene, 0.19, 0, 1.77, 0, C.water, 2).scale.set(0.8, 1.3, 0.8);
  for (let i = 0; i < 6; i++) {
    const angle = (i * Math.PI) / 3;
    const start = new THREE.Vector3(
      Math.sin(angle) * 0.65,
      1.12,
      Math.cos(angle) * 0.65,
    );
    const middle = new THREE.Vector3(
      Math.sin(angle) * 1.03,
      1.03,
      Math.cos(angle) * 1.03,
    );
    const end = new THREE.Vector3(
      Math.sin(angle) * 1.36,
      0.48,
      Math.cos(angle) * 1.36,
    );
    const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
    const water = new THREE.MeshStandardMaterial({
      color: 0xb8dfd7,
      roughness: 0.25,
      transparent: true,
      opacity: 0.7,
    });
    resources.add(water);
    mesh(
      scene,
      geometry(
        `stream-${i}`,
        () => new THREE.TubeGeometry(curve, 10, 0.024, 5, false),
      ),
      water,
      0,
      0,
      0,
      false,
    );
  }
  for (let i = 0; i < 3; i++) {
    const ripple = ring(
      scene,
      1.32 + i * 0.16,
      1.337 + i * 0.16,
      0,
      0.492 + i * 0.001,
      0,
      0xb2dad1,
    );
    waterRings.push(ripple);
  }

  // Plaza gardens, cafe tables, benches, a wayfinder and hand-planted trees.
  for (let i = 0; i < 6; i++) {
    const angle = ((i + 0.5) * Math.PI) / 3;
    const x = Math.sin(angle) * 5.5;
    const z = Math.cos(angle) * 5.5;
    const bed = box(scene, 1.7, 0.16, 0.94, x, 0.15, z, C.stone, 0.13);
    bed.rotation.y = angle;
    const soil = box(scene, 1.52, 0.025, 0.76, x, 0.24, z, C.grassDark, 0.09);
    soil.rotation.y = angle;
    shrub(
      scene,
      x - Math.cos(angle) * 0.4,
      z + Math.sin(angle) * 0.4,
      0.74,
      0.43,
    );
    shrub(
      scene,
      x + Math.cos(angle) * 0.4,
      z - Math.sin(angle) * 0.4,
      0.74,
      0.43,
    );
    flowers(
      scene,
      x + Math.sin(angle) * 0.35,
      z + Math.cos(angle) * 0.35,
      i % 2 ? C.ivory : C.yellow,
    );
  }
  bench(scene, -2.93, 1.72, -Math.PI / 3);
  bench(scene, 2.93, -1.72, (Math.PI * 2) / 3);
  bench(scene, -2.85, -1.82, (-Math.PI * 2) / 3);
  bench(scene, 2.85, 1.82, Math.PI / 3);
  for (const [x, z] of [
    [-5.8, -0.65],
    [5.8, 0.65],
    [-2.8, -6.0],
    [3.0, 6.0],
    [-11.4, 1.0],
    [11.4, -0.5],
  ] as const)
    lamp(x, z);

  const treePositions: [number, number, number, number][] = [
    [-13.25, -9.55, 1.16, 0],
    [-11.2, -10.45, 0.88, 1],
    [-6.0, -10.55, 0.86, 0],
    [4.3, -10.4, 0.9, 1],
    [11.9, -9.5, 1.14, 0],
    [13.6, -6.95, 0.85, 0],
    [13.6, -1.1, 0.92, 1],
    [13.5, 9.9, 1.05, 0],
    [10.9, 10.5, 0.72, 0],
    [5.6, 10.65, 0.83, 1],
    [-4.7, 10.5, 0.86, 0],
    [-12.5, 10.2, 1.02, 0],
    [-13.9, 6.85, 0.78, 1],
    [-13.4, -2.0, 0.88, 0],
    [-12.9, 0.55, 0.65, 0],
    [12.8, 2.0, 0.76, 0],
    [-5.5, -6.35, 0.6, 0],
    [5.1, -6.7, 0.61, 0],
    [-4.0, 6.85, 0.58, 0],
    [4.5, 6.4, 0.55, 0],
  ];
  for (const [x, z, scale, type] of treePositions) tree(x, z, scale, type);

  // Irregular clusters, flowers, and small stones keep the landscaping from looking procedural.
  for (let i = 0; i < 34; i++) {
    const side = i % 4;
    const t = ((i * 0.61803398875) % 1) * 2 - 1;
    const x = side < 2 ? t * 13.8 : side === 2 ? -14.35 : 14.35;
    const z = side < 2 ? (side === 0 ? -11.35 : 11.35) : t * 10.6;
    const value = sphere(
      scene,
      0.22 + (i % 3) * 0.055,
      x,
      0.12,
      z,
      i % 5 ? C.foliage : C.stoneEdge,
      0,
    );
    value.scale.set(1.5, 0.65, 1);
    if (i % 3 === 0)
      flowers(scene, x + 0.42, z, i % 2 ? C.terracotta : C.ivory);
  }

  // Cafe terrace, with one open paper parasol and miniature crockery.
  {
    const group = new THREE.Group();
    group.position.set(-9.2, 0, 0.4);
    scene.add(group);
    cylinder(group, 1.38, 1.38, 0.04, 0, 0.11, 0, C.path, 32, false);
    cylinder(group, 0.68, 0.68, 0.08, 0, 0.75, 0, C.woodLight, 24);
    cylinder(group, 0.07, 0.08, 0.64, 0, 0.41, 0, C.metal, 8);
    cylinder(group, 0.03, 0.035, 2.2, 0, 1.24, 0, C.woodLight, 8);
    const parasol = cylinder(group, 0.03, 1.19, 0.38, 0, 2.29, 0, C.ivory, 10);
    parasol.rotation.y = 0.2;
    cylinder(group, 1.19, 1.19, 0.045, 0, 2.1, 0, C.terracotta, 10);
    sphere(group, 0.07, 0, 2.5, 0, C.woodLight, 1);
    for (const angle of [0.6, 2.7, 4.8]) {
      const x = Math.sin(angle) * 0.95;
      const z = Math.cos(angle) * 0.95;
      const chair = new THREE.Group();
      chair.position.set(x, 0, z);
      chair.rotation.y = angle;
      group.add(chair);
      box(chair, 0.39, 0.06, 0.4, 0, 0.43, 0, C.terracotta, 0.06);
      box(chair, 0.39, 0.37, 0.055, 0, 0.61, 0.16, C.terracotta, 0.05);
      for (const px of [-0.14, 0.14])
        for (const pz of [-0.14, 0.14])
          cylinder(chair, 0.022, 0.023, 0.38, px, 0.21, pz, C.wood, 6);
    }
    for (const x of [-0.32, 0.34])
      cylinder(group, 0.06, 0.047, 0.1, x, 0.845, 0.12, C.ivory, 10);
  }

  // A tiny duck pond and footbridge occupy the eastern garden.
  {
    const pond = new THREE.Group();
    pond.position.set(10.0, 0, 0.3);
    pond.rotation.y = -0.3;
    scene.add(pond);
    cylinder(pond, 1.4, 1.5, 0.05, 0, 0.11, 0, C.stone, 32, false).scale.z =
      1.55;
    cylinder(pond, 1.26, 1.26, 0.025, 0, 0.145, 0, C.water, 32, false).scale.z =
      1.57;
    for (let i = 0; i < 9; i++)
      box(
        pond,
        1.07,
        0.09,
        0.19,
        0,
        0.29 + Math.sin((i / 8) * Math.PI) * 0.11,
        -0.94 + i * 0.235,
        C.woodLight,
        0.025,
      );
    for (const x of [-0.53, 0.53]) {
      for (const z of [-0.98, 0, 0.98])
        box(pond, 0.055, 0.45, 0.055, x, 0.55, z, C.wood, 0.008);
      rod(
        pond,
        new THREE.Vector3(x, 0.73, -1),
        new THREE.Vector3(x, 0.82, 0),
        0.028,
        C.wood,
      );
      rod(
        pond,
        new THREE.Vector3(x, 0.82, 0),
        new THREE.Vector3(x, 0.73, 1),
        0.028,
        C.wood,
      );
    }
    for (const z of [-1.8, 1.7]) {
      cylinder(pond, 0.19, 0.19, 0.02, 0.43, 0.172, z, C.foliage, 12, false);
      sphere(pond, 0.08, 0.43, 0.21, z, C.pink, 0);
    }
    sphere(pond, 0.13, -0.75, 0.23, -0.75, C.ivory, 1).scale.z = 1.4;
    sphere(pond, 0.075, -0.75, 0.34, -0.63, C.ivory, 1);
    box(pond, 0.07, 0.025, 0.08, -0.75, 0.32, -0.54, C.yellow, 0.01);
  }

  // Flags, bicycles, a noticeboard and edge detailing make the campus feel inhabited.
  {
    const group = new THREE.Group();
    group.position.set(-3.0, 0, -8.3);
    scene.add(group);
    cylinder(group, 0.09, 0.15, 0.13, 0, 0.1, 0, C.stone, 12);
    cylinder(group, 0.025, 0.035, 3.3, 0, 1.7, 0, C.ivory, 8);
    sphere(group, 0.07, 0, 3.4, 0, C.yellow, 1);
    const flagGeo = geometry(
      "flag",
      () => new THREE.PlaneGeometry(0.86, 0.53, 10, 3),
    );
    const flagMat = new THREE.MeshStandardMaterial({
      color: C.terracotta,
      roughness: 0.9,
      side: THREE.DoubleSide,
    });
    resources.add(flagMat);
    const flag = mesh(group, flagGeo, flagMat, 0.43, 3.04, 0);
    animatedFlags.push(flag);
  }
  {
    const group = new THREE.Group();
    group.position.set(-4.1, 0, 2.82);
    group.rotation.y = -0.3;
    scene.add(group);
    for (const x of [-0.39, 0.39])
      box(group, 0.065, 1.17, 0.065, x, 0.63, 0, C.wood, 0.012);
    box(group, 0.99, 0.74, 0.09, 0, 1.09, 0, C.woodLight, 0.05);
    box(group, 0.85, 0.61, 0.025, 0, 1.09, 0.06, C.ivory, 0.025);
    for (let i = 0; i < 3; i++)
      box(
        group,
        0.19,
        0.23,
        0.015,
        -0.26 + i * 0.26,
        1.11 + (i % 2) * 0.07,
        0.08,
        [C.yellow, C.blue, C.pink][i]!,
        0.003,
      );
    gabledRoof(group, 1.17, 0.4, 1.5, 0.14, C.teal);
  }
  {
    const group = new THREE.Group();
    group.position.set(5.9, 0, 8.85);
    group.rotation.y = -0.45;
    scene.add(group);
    for (const x of [-0.48, 0.48]) {
      const wheel = mesh(
        group,
        geometry(
          "bike-wheel",
          () => new THREE.TorusGeometry(0.27, 0.025, 6, 20),
        ),
        material(C.dark),
        x,
        0.34,
        0,
      );
      wheel.rotation.y = Math.PI / 2;
      for (let i = 0; i < 4; i++)
        rod(
          group,
          new THREE.Vector3(x, 0.34, 0),
          new THREE.Vector3(
            x,
            0.34 + Math.cos((i * Math.PI) / 2) * 0.25,
            Math.sin((i * Math.PI) / 2) * 0.25,
          ),
          0.007,
          C.metal,
        );
    }
    rod(
      group,
      new THREE.Vector3(-0.48, 0.34, 0),
      new THREE.Vector3(-0.15, 0.74, 0),
      0.025,
      C.terracotta,
    );
    rod(
      group,
      new THREE.Vector3(-0.48, 0.34, 0),
      new THREE.Vector3(0.08, 0.34, 0),
      0.025,
      C.terracotta,
    );
    rod(
      group,
      new THREE.Vector3(-0.15, 0.74, 0),
      new THREE.Vector3(0.08, 0.34, 0),
      0.025,
      C.terracotta,
    );
    rod(
      group,
      new THREE.Vector3(-0.15, 0.74, 0),
      new THREE.Vector3(0.34, 0.77, 0),
      0.025,
      C.terracotta,
    );
    rod(
      group,
      new THREE.Vector3(0.08, 0.34, 0),
      new THREE.Vector3(0.34, 0.77, 0),
      0.025,
      C.terracotta,
    );
    rod(
      group,
      new THREE.Vector3(0.48, 0.34, 0),
      new THREE.Vector3(0.31, 0.94, 0),
      0.024,
      C.metal,
    );
    box(group, 0.2, 0.045, 0.12, -0.16, 0.81, 0, C.dark, 0.02);
    rod(
      group,
      new THREE.Vector3(0.31, 0.94, -0.14),
      new THREE.Vector3(0.31, 0.94, 0.14),
      0.023,
      C.metal,
    );
  }

  // Bake immobile scenery by material and department. The visual detail is retained while
  // thousands of architectural parts become a few dozen draw calls; picking keeps its IDs.
  {
    scene.updateMatrixWorld(true);
    const movingRoots = new Set<THREE.Object3D>([
      ...animatedLeaves,
      ...animatedFlags,
      ...waterRings,
    ]);
    const batches = new Map<
      string,
      {
        material: THREE.Material;
        geometries: THREE.BufferGeometry[];
        meshes: THREE.Mesh[];
        department?: string;
        cast: boolean;
        receive: boolean;
      }
    >();
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh) || Array.isArray(object.material))
        return;
      for (
        let parent: THREE.Object3D | null = object;
        parent;
        parent = parent.parent
      )
        if (movingRoots.has(parent)) return;
      const department = object.userData.department as string | undefined;
      const key = `${object.material.uuid}-${department || "landscape"}-${object.castShadow}-${object.receiveShadow}`;
      let batch = batches.get(key);
      if (!batch) {
        batch = {
          material: object.material,
          geometries: [],
          meshes: [],
          department,
          cast: object.castShadow,
          receive: object.receiveShadow,
        };
        batches.set(key, batch);
      }
      const baked = object.geometry.index
        ? object.geometry.toNonIndexed()
        : object.geometry.clone();
      baked.applyMatrix4(object.matrixWorld);
      batch.geometries.push(baked);
      batch.meshes.push(object);
    });
    for (const batch of batches.values()) {
      if (batch.meshes.length < 2) {
        for (const geo of batch.geometries) geo.dispose();
        continue;
      }
      const merged = mergeGeometries(batch.geometries, false);
      for (const geo of batch.geometries) geo.dispose();
      if (!merged) continue;
      resources.add(merged);
      const replacement = mesh(
        scene,
        merged,
        batch.material,
        0,
        0,
        0,
        batch.cast,
      );
      replacement.receiveShadow = batch.receive;
      if (batch.department) {
        replacement.userData.department = batch.department;
        pickables.push(replacement);
      }
      for (const original of batch.meshes) {
        original.removeFromParent();
        const index = pickables.indexOf(original);
        if (index >= 0) pickables.splice(index, 1);
      }
    }
    // Dedicated picking volumes keep pointer interaction fast even on the detailed merged scene.
    pickables.length = 0;
    const pickingMaterial = new THREE.MeshBasicMaterial();
    resources.add(pickingMaterial);
    for (const department of departments.values()) {
      const hitHeight = department.id === "headquarters" ? 6.4 : 3.8;
      const hit = mesh(
        scene,
        geometry(
          `department-hit-${hitHeight}`,
          () => new THREE.BoxGeometry(5.1, hitHeight, 4.1),
        ),
        pickingMaterial,
        department.x,
        hitHeight / 2,
        department.z,
        false,
      );
      hit.rotation.y = department.rotation;
      hit.layers.set(1);
      hit.userData.department = department.id;
      pickables.push(hit);
    }
  }

  function makeCitizen(data: SceneAgent): Citizen {
    const group = new THREE.Group();
    group.scale.setScalar(1.3);
    const seed = hash(data.id);
    const colors = [C.terracotta, C.teal, C.blue, C.yellow, C.purple, C.pink];
    const color = colors[seed % colors.length]!;
    scene.add(group);
    const body = new THREE.Group();
    group.add(body);
    // The residents are little field robots: expressive faces, jackets and chunky boots.
    box(body, 0.35, 0.4, 0.26, 0, 0.63, 0, color, 0.095);
    box(body, 0.12, 0.17, 0.027, 0.07, 0.66, 0.143, C.ivory, 0.025);
    box(body, 0.055, 0.045, 0.035, 0.07, 0.7, 0.16, C.yellow, 0.012);
    box(body, 0.055, 0.3, 0.026, -0.04, 0.62, 0.148, C.stone, 0.01);
    const head = new THREE.Group();
    head.position.y = 0.88;
    body.add(head);
    box(head, 0.43, 0.35, 0.37, 0, 0.11, 0, C.ivory, 0.11);
    box(head, 0.325, 0.155, 0.035, 0, 0.1, 0.186, C.dark, 0.055);
    for (const x of [-0.078, 0.078])
      box(head, 0.043, 0.045, 0.02, x, 0.11, 0.21, 0xcde2c2, 0.013);
    box(head, 0.38, 0.06, 0.28, 0, 0.303, -0.018, color, 0.04);
    cylinder(head, 0.014, 0.015, 0.15, -0.12, 0.405, -0.06, C.metal, 6);
    sphere(head, 0.035, -0.12, 0.489, -0.06, C.yellow, 1);
    for (const x of [-0.236, 0.236])
      box(head, 0.06, 0.13, 0.14, x, 0.1, 0, color, 0.025);
    const limb = (x: number, y: number, leg: boolean) => {
      const pivot = new THREE.Group();
      pivot.position.set(x, y, 0);
      body.add(pivot);
      if (leg) {
        box(pivot, 0.12, 0.27, 0.14, 0, -0.115, 0, C.dark, 0.04);
        box(pivot, 0.145, 0.12, 0.23, 0, -0.267, 0.035, C.wood, 0.04);
        box(pivot, 0.151, 0.035, 0.235, 0, -0.32, 0.035, C.stone, 0.01);
      } else {
        box(pivot, 0.125, 0.245, 0.14, 0, -0.07, 0, color, 0.048);
        sphere(pivot, 0.068, 0, -0.205, 0, C.ivory, 1);
      }
      return pivot;
    };
    const leftArm = limb(-0.235, 0.77, false);
    const rightArm = limb(0.235, 0.77, false);
    const leftLeg = limb(-0.1, 0.44, true);
    const rightLeg = limb(0.1, 0.44, true);
    box(body, 0.23, 0.28, 0.13, 0, 0.64, -0.185, C.stone, 0.045);
    box(body, 0.17, 0.065, 0.04, 0, 0.68, -0.267, color, 0.012);
    softShadow(group, 0, 0.04, 0.95, 0.76, 0.65);
    if (!sharedSelectionMaterial) {
      sharedSelectionMaterial = new THREE.MeshBasicMaterial({
        color: 0xf1b96f,
        transparent: true,
        opacity: 0.8,
        depthWrite: false,
      });
      resources.add(sharedSelectionMaterial);
    }
    const haloMat = sharedSelectionMaterial;
    const halo = mesh(
      group,
      geometry("resident-halo", () => new THREE.RingGeometry(0.37, 0.43, 40)),
      haloMat,
      0,
      0.075,
      0,
      false,
    );
    halo.rotation.x = -Math.PI / 2;
    halo.visible = false;
    const indicator = sphere(group, 0.068, 0, 1.62, 0, C.teal, 1);
    if (!sharedCharacterHitMaterial) {
      sharedCharacterHitMaterial = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
        colorWrite: false,
      });
      resources.add(sharedCharacterHitMaterial);
    }
    const targetMaterial = sharedCharacterHitMaterial;
    const target = mesh(
      group,
      geometry(
        "resident-hit",
        () => new THREE.CapsuleGeometry(0.37, 0.7, 3, 6),
      ),
      targetMaterial,
      0,
      0.7,
      0,
      false,
    );
    target.layers.set(1);
    target.userData.agentId = data.id;
    pickables.push(target);
    const marker = document.createElement("button");
    marker.type = "button";
    marker.style.cssText =
      "position:absolute;left:0;top:0;display:flex;align-items:center;gap:6px;min-height:26px;padding:5px 9px;border:1px solid rgba(255,255,255,.85);border-radius:7px;background:rgba(49,66,59,.96);box-shadow:0 3px 10px #26362915;color:#fffdf0;white-space:nowrap;font-family:inherit;font-size:10px;font-weight:600;pointer-events:auto;cursor:pointer;will-change:transform;";
    marker.className = "society-agent-label";
    const markerStatus = document.createElement("span");
    markerStatus.style.cssText =
      "width:5px;height:5px;border-radius:50%;background:#bbd491;flex:none;";
    const markerText = document.createElement("span");
    markerText.textContent = data.name;
    marker.append(markerStatus, markerText);
    marker.setAttribute("aria-label", `Select ${data.name}, ${data.status}`);
    marker.addEventListener("click", (event) => {
      event.stopPropagation();
      callbacks.onSelectAgent?.(data.id);
    });
    overlay.appendChild(marker);
    const citizen: Citizen = {
      data,
      group,
      body,
      head,
      leftArm,
      rightArm,
      leftLeg,
      rightLeg,
      halo,
      indicator,
      destination: new THREE.Vector3(),
      waypoints: [],
      phase: seed % 100,
      marker,
      markerText,
      markerStatus,
      walking: false,
      visitQueue: [],
      visitDwell: 0,
    };
    return citizen;
  }

  function destinationFor(departmentId: string, index: number): THREE.Vector3 {
    const department =
      departments.get(departmentId) || departments.get("headquarters")!;
    const position = department.entrance.clone();
    const offset = ((index % 5) - 2) * 0.59;
    position.x += Math.cos(department.rotation) * offset;
    position.z -= Math.sin(department.rotation) * offset;
    const extra = Math.floor(index / 5) * 0.55;
    position.x -= Math.sin(department.rotation) * extra;
    position.z -= Math.cos(department.rotation) * extra;
    return position;
  }

  function route(
    citizen: Citizen,
    destination: THREE.Vector3,
    rememberDestination = true,
  ) {
    if (rememberDestination) citizen.destination.copy(destination);
    if (reducedMotion || citizen.group.position.distanceTo(destination) < 0.3) {
      citizen.group.position.copy(destination);
      citizen.waypoints = [];
      return;
    }
    const position = citizen.group.position;
    const startAngle = Math.atan2(position.x, position.z);
    const endAngle = Math.atan2(destination.x, destination.z);
    let difference = endAngle - startAngle;
    while (difference > Math.PI) difference -= Math.PI * 2;
    while (difference < -Math.PI) difference += Math.PI * 2;
    const radius = 3.98;
    citizen.waypoints = [];
    // Enter the plaza's outer walking lane, arc around the fountain, then follow the next spoke.
    citizen.waypoints.push(
      new THREE.Vector3(
        Math.sin(startAngle) * radius,
        0.13,
        Math.cos(startAngle) * radius,
      ),
    );
    const steps = Math.max(1, Math.ceil(Math.abs(difference) / 0.24));
    for (let i = 1; i <= steps; i++) {
      const angle = startAngle + (difference * i) / steps;
      citizen.waypoints.push(
        new THREE.Vector3(
          Math.sin(angle) * radius,
          0.13,
          Math.cos(angle) * radius,
        ),
      );
    }
    citizen.waypoints.push(destination.clone());
  }

  function visitDestination(citizen: Citizen, departmentId: string) {
    return citizen.data.department === departmentId
      ? citizen.destination.clone()
      : destinationFor(departmentId, 2);
  }

  function setAgents(agents: SceneAgent[]) {
    needsRender = true;
    const ids = new Set(agents.map((agent) => agent.id));
    for (const [id, citizen] of citizens) {
      if (!ids.has(id)) {
        scene.remove(citizen.group);
        citizen.marker.remove();
        for (let i = pickables.length - 1; i >= 0; i--)
          if (pickables[i]!.userData.agentId === id) pickables.splice(i, 1);
        citizens.delete(id);
      }
    }
    const counts = new Map<string, number>();
    for (const data of agents) {
      const departmentId = departments.has(data.department)
        ? data.department
        : "headquarters";
      const index = counts.get(departmentId) || 0;
      counts.set(departmentId, index + 1);
      const destination = destinationFor(departmentId, index);
      let citizen = citizens.get(data.id);
      if (!citizen) {
        citizen = makeCitizen(data);
        citizen.group.position.copy(destination);
        citizen.destination.copy(destination);
        citizen.group.rotation.y =
          Math.atan2(-destination.x, -destination.z) +
          ((hash(data.id) % 9) - 4) * 0.16;
        citizens.set(data.id, citizen);
      } else if (
        citizen.data.department !== data.department ||
        citizen.destination.distanceTo(destination) > 0.15
      ) {
        if (citizen.visitQueue.length) citizen.destination.copy(destination);
        else route(citizen, destination);
      }
      citizen.data = { ...data };
      citizen.markerText.textContent = data.name;
      citizen.marker.setAttribute(
        "aria-label",
        `Select ${data.name}, ${data.status}`,
      );
      const isError = /error|failed|blocked/.test(data.status);
      const isIdle = /idle|completed|done|waiting|offline/.test(data.status);
      citizen.markerStatus.style.background = isError
        ? "#efa486"
        : isIdle
          ? "#d2d0b8"
          : "#bbd491";
      citizen.indicator.material = material(
        isError ? C.terracotta : isIdle ? C.stoneEdge : C.teal,
      );
    }
    for (const department of departments.values()) {
      const count = counts.get(department.id) || 0;
      department.count.textContent = String(count);
      department.count.style.display = count ? "inline" : "none";
      department.button.setAttribute(
        "aria-label",
        `Explore ${department.name}, ${count} ${count === 1 ? "resident" : "residents"}`,
      );
    }
    renderer.shadowMap.needsUpdate = true;
  }

  const raycaster = new THREE.Raycaster();
  raycaster.layers.enable(1);
  const pointer = new THREE.Vector2();
  const pointerDown = new THREE.Vector2();
  let isPointerDown = false;
  function intersection(event: PointerEvent) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      (-(event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(pickables, false);
    const resident = hits.find((hit) => hit.object.userData.agentId);
    return resident || hits[0];
  }
  function onPointerDown(event: PointerEvent) {
    isPointerDown = true;
    pointerDown.set(event.clientX, event.clientY);
  }
  function onPointerUp(event: PointerEvent) {
    const wasPointerDown = isPointerDown;
    isPointerDown = false;
    if (
      !wasPointerDown ||
      event.button !== 0 ||
      pointerDown.distanceTo(new THREE.Vector2(event.clientX, event.clientY)) >
        5
    )
      return;
    const hit = intersection(event);
    if (hit?.object.userData.agentId)
      callbacks.onSelectAgent?.(hit.object.userData.agentId as string);
    else if (hit?.object.userData.department)
      callbacks.onSelectDepartment?.(hit.object.userData.department as string);
  }
  let lastHover = 0;
  function onPointerMove(event: PointerEvent) {
    if (isPointerDown || performance.now() - lastHover < 60) return;
    lastHover = performance.now();
    const hit = intersection(event);
    hoveredAgent = (hit?.object.userData.agentId as string | undefined) || null;
    needsRender = true;
    renderer.domElement.style.cursor = hit ? "pointer" : "grab";
  }
  function onPointerLeave() {
    hoveredAgent = null;
    isPointerDown = false;
    needsRender = true;
  }
  renderer.domElement.addEventListener("pointerdown", onPointerDown);
  renderer.domElement.addEventListener("pointerup", onPointerUp);
  renderer.domElement.addEventListener("pointermove", onPointerMove);
  renderer.domElement.addEventListener("pointerleave", onPointerLeave);

  function resize() {
    needsRender = true;
    width = Math.max(container.clientWidth, 1);
    height = Math.max(container.clientHeight, 1);
    const aspect = width / height;
    const size = aspect < 1.2 ? 40 / aspect : 32.0;
    camera.left = (-size * aspect) / 2;
    camera.right = (size * aspect) / 2;
    camera.top = size / 2;
    camera.bottom = -size / 2;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  resize();

  function projectLabel(
    element: HTMLElement,
    position: THREE.Vector3,
    visible: boolean,
    offset = 0,
  ) {
    if (!visible) {
      element.style.display = "none";
      return;
    }
    const p = position.clone().project(camera);
    const x = (p.x * 0.5 + 0.5) * width;
    const y = (-p.y * 0.5 + 0.5) * height + offset;
    if (p.z > 1 || x < -70 || x > width + 70 || y < -40 || y > height + 40) {
      element.style.display = "none";
      return;
    }
    element.style.display = "flex";
    element.style.transform = `translate(${Math.round(x)}px,${Math.round(y)}px) translate(-50%,-100%)`;
  }

  function animate(now: number) {
    if (disposed) return;
    frame = requestAnimationFrame(animate);
    let dt = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;
    if (!paused && !reducedMotion) elapsed += dt;
    if (targetFocus) {
      const delta = targetFocus.clone().sub(controls.target);
      const step = reducedMotion
        ? delta
        : delta.multiplyScalar(Math.min(dt * 5, 1));
      controls.target.add(step);
      camera.position.add(step);
      if (controls.target.distanceTo(targetFocus) < 0.005) targetFocus = null;
    }
    if (targetZoom !== null) {
      camera.zoom +=
        (targetZoom - camera.zoom) * (reducedMotion ? 1 : Math.min(dt * 6, 1));
      camera.updateProjectionMatrix();
      needsRender = true;
      if (Math.abs(camera.zoom - targetZoom) < 0.002) targetZoom = null;
    }
    controls.update();
    if ((paused || reducedMotion) && !needsRender && !targetFocus) return;
    // A tiny observer world does not need to consume a full gaming frame budget.
    if (!needsRender && now - lastRender < 1000 / 30) return;
    dt = Math.min((now - lastRender) / 1000, 0.1);
    const renderStart = performance.now();
    if (!paused && !reducedMotion) {
      for (const leaves of animatedLeaves)
        leaves.rotation.z =
          Math.sin(elapsed * 0.7 + (leaves.userData.phase as number)) * 0.012;
      for (const flag of animatedFlags) {
        const positions = flag.geometry.attributes.position!;
        for (let i = 0; i < positions.count; i++) {
          const x = positions.getX(i);
          positions.setZ(
            i,
            Math.sin(elapsed * 2.5 - x * 5) * (x + 0.43) * 0.12,
          );
        }
        positions.needsUpdate = true;
      }
      for (let i = 0; i < waterRings.length; i++) {
        const pulse = 1 + Math.sin(elapsed * 1.1 + i * 1.8) * 0.055;
        waterRings[i]!.scale.set(pulse, pulse, 1);
      }
    }
    let shadowMoving = false;
    for (const citizen of citizens.values()) {
      const active = !/idle|completed|done|waiting|offline|error|failed/.test(
        citizen.data.status,
      );
      citizen.walking = citizen.waypoints.length > 0;
      if (!paused && !reducedMotion) {
        if (!citizen.walking && citizen.visitQueue.length) {
          citizen.visitDwell += dt;
          if (citizen.visitDwell >= 0.7) {
            citizen.visitQueue.shift();
            citizen.visitDwell = 0;
            const next = citizen.visitQueue[0];
            route(
              citizen,
              next ? visitDestination(citizen, next) : citizen.destination,
              false,
            );
            citizen.walking = citizen.waypoints.length > 0;
          }
        }
        if (citizen.walking) {
          const waypoint = citizen.waypoints[0]!;
          const direction = waypoint.clone().sub(citizen.group.position);
          const distance = direction.length();
          const travel = dt * 2.05;
          if (distance < travel) {
            citizen.group.position.copy(waypoint);
            citizen.waypoints.shift();
          } else {
            direction.normalize();
            citizen.group.position.addScaledVector(direction, travel);
            const desired = Math.atan2(direction.x, direction.z);
            let difference = desired - citizen.group.rotation.y;
            while (difference > Math.PI) difference -= Math.PI * 2;
            while (difference < -Math.PI) difference += Math.PI * 2;
            citizen.group.rotation.y += difference * Math.min(dt * 9, 1);
          }
          const gait = Math.sin(elapsed * 12 + citizen.phase);
          citizen.leftLeg.rotation.x = gait * 0.58;
          citizen.rightLeg.rotation.x = -gait * 0.58;
          citizen.leftArm.rotation.x = -gait * 0.43;
          citizen.rightArm.rotation.x = gait * 0.43;
          citizen.body.position.y = Math.abs(gait) * 0.045;
          citizen.body.rotation.z = gait * 0.035;
          shadowMoving = true;
        } else {
          citizen.leftLeg.rotation.x *= 0.82;
          citizen.rightLeg.rotation.x *= 0.82;
          citizen.leftArm.rotation.x = active
            ? -0.3 + Math.sin(elapsed * 2 + citizen.phase) * 0.14
            : Math.sin(elapsed + citizen.phase) * 0.025;
          citizen.rightArm.rotation.x = active
            ? -0.3 + Math.sin(elapsed * 2 + citizen.phase + 1.4) * 0.14
            : 0;
          citizen.body.position.y =
            Math.sin(elapsed * 1.7 + citizen.phase) * 0.012;
          citizen.body.rotation.z *= 0.86;
          citizen.head.rotation.y =
            Math.sin(elapsed * 0.6 + citizen.phase) * 0.16;
        }
        citizen.indicator.position.y =
          1.49 + Math.sin(elapsed * 2.2 + citizen.phase) * 0.045;
      }
      citizen.indicator.visible =
        active || /error|failed|blocked/.test(citizen.data.status);
      citizen.halo.visible =
        selectedAgent === citizen.data.id || hoveredAgent === citizen.data.id;
      projectLabel(
        citizen.marker,
        citizen.group.position.clone().add(new THREE.Vector3(0, 2.1, 0)),
        citizen.halo.visible,
        -2,
      );
      citizen.marker.style.background =
        selectedAgent === citizen.data.id ? "#b77655" : "rgba(49,66,59,.96)";
    }
    // Static campus shadows are cached; moving citizens only require an occasional refresh.
    if (
      shadowMoving &&
      Math.floor(now / 80) !== Math.floor((now - dt * 1000) / 80)
    )
      renderer.shadowMap.needsUpdate = true;
    for (const department of departments.values()) {
      projectLabel(
        department.button,
        department.label,
        labelsVisible &&
          (width >= 600 ||
            camera.zoom > 1.4 ||
            focusedDepartment === department.id),
      );
      department.button.style.boxShadow =
        focusedDepartment === department.id
          ? "0 0 0 2px #b77a55,0 3px 10px #26362915"
          : "0 3px 10px rgba(52,67,43,.09)";
    }
    renderer.render(scene, camera);
    frameDuration = performance.now() - renderStart;
    needsRender = false;
    lastRender = now;
  }
  frame = requestAnimationFrame(animate);

  return {
    setAgents,
    getDiagnostics() {
      return {
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        residents: citizens.size,
        queuedVisits: [...citizens.values()].reduce(
          (sum, citizen) => sum + citizen.visitQueue.length,
          0,
        ),
        frameDurationMs: Math.round(frameDuration * 100) / 100,
        pixelRatio: renderer.getPixelRatio(),
        paused,
        agents: [...citizens.values()].map((citizen) => ({
          id: citizen.data.id,
          department: citizen.data.department,
          position: {
            x: citizen.group.position.x,
            z: citizen.group.position.z,
          },
          destination: { x: citizen.destination.x, z: citizen.destination.z },
          walking: citizen.walking,
          remainingWaypoints: citizen.waypoints.length,
          queuedDepartments: [...citizen.visitQueue],
        })),
      };
    },
    visitDepartment(agentId: string, departmentId: string) {
      const citizen = citizens.get(agentId);
      if (!citizen || !departments.has(departmentId) || reducedMotion) return;
      needsRender = true;
      const queue = citizen.visitQueue;
      if (queue[queue.length - 1] === departmentId) return;
      // Bound visual history during bursts: keep the in-flight visit and the most recent destinations.
      if (queue.length >= 6) queue.splice(1, 1);
      queue.push(departmentId);
      if (queue.length === 1) {
        citizen.visitDwell = 0;
        route(citizen, visitDestination(citizen, departmentId), false);
      }
    },
    setSelectedAgent(id: string | null) {
      selectedAgent = id;
      needsRender = true;
      const citizen = id ? citizens.get(id) : null;
      if (citizen) {
        targetFocus = citizen.group.position
          .clone()
          .add(new THREE.Vector3(0, 0.35, 0));
        targetZoom = Math.max(camera.zoom, 1.62);
      }
    },
    focusDepartment(id: string | null) {
      focusedDepartment = id;
      needsRender = true;
      const department = id ? departments.get(id) : null;
      targetFocus = department
        ? department.group.position.clone().multiplyScalar(0.56)
        : initialTarget.clone();
      if (department && camera.zoom < 1.12) targetZoom = 1.12;
    },
    setPaused(value: boolean) {
      paused = value;
      needsRender = true;
    },
    setNight(value: boolean) {
      if (night === value) return;
      night = value;
      needsRender = true;
      scene.background = new THREE.Color(value ? 0x172b3a : C.background);
      hemisphere.color.set(value ? 0xb1bfd4 : 0xf8f4de);
      hemisphere.groundColor.set(value ? 0x475a65 : 0xa0ae85);
      hemisphere.intensity = value ? 1.35 : 1.5;
      sun.color.set(value ? 0xa7c4ed : 0xffebcd);
      sun.intensity = value ? 1.3 : 2.6;
      fill.intensity = value ? 0.6 : 0.7;
      renderer.toneMappingExposure = value ? 1.07 : 1.07;
      for (const mat of nightMaterials) mat.emissiveIntensity = value ? 1.8 : 0;
      for (const light of lampLights) light.intensity = value ? 5.5 : 0;
      renderer.shadowMap.needsUpdate = true;
    },
    setLabels(value: boolean) {
      labelsVisible = value;
      needsRender = true;
    },
    zoom(delta: number) {
      needsRender = true;
      targetZoom = null;
      camera.zoom = THREE.MathUtils.clamp(
        camera.zoom * Math.exp(delta * 0.15),
        controls.minZoom,
        controls.maxZoom,
      );
      camera.updateProjectionMatrix();
    },
    resetView() {
      needsRender = true;
      focusedDepartment = null;
      targetFocus = null;
      targetZoom = null;
      controls.target.copy(initialTarget);
      camera.position.copy(initialCamera);
      camera.zoom = 1;
      camera.updateProjectionMatrix();
      controls.update();
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      reducedMotionQuery.removeEventListener("change", onReducedMotion);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
      controls.dispose();
      controls.removeEventListener("change", onControlsChange);
      controls.removeEventListener("start", onControlsStart);
      for (const resource of resources) resource.dispose();
      sun.shadow.map?.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      overlay.remove();
      citizens.clear();
    },
  };
}
