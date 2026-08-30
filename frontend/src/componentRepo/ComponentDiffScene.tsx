import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { apiFetch } from '../api/client';
import type {
  ComponentVersionDiffChangeKind,
  ComponentVersionDiffResponse,
  ComponentVersionPreviewModelResponse,
} from './componentRepoApi';

type PreviewModel = NonNullable<ComponentVersionPreviewModelResponse['model']>;

/** ComponentDiffFocus 用两侧原始场景实例路径同步定位用户选中的变化。 */
export type ComponentDiffFocus = {
  afterInstanceId?: string;
  beforeInstanceId?: string;
};

type ComponentDiffSceneProps = {
  afterLabel: string;
  afterModel: PreviewModel;
  beforeLabel: string;
  beforeModel: PreviewModel | null;
  diff: ComponentVersionDiffResponse;
  emptyBeforeLabel: string;
  focus: ComponentDiffFocus | null;
  loadFailedLabel: string;
  registerReset?: (reset: (() => void) | null) => void;
};

type PaneRuntime = {
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  mount: HTMLDivElement;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
};

type PulseMaterial = {
  baseOpacity: number;
  material: THREE.Material;
};

const changeColors: Record<ComponentVersionDiffChangeKind | 'ambiguous', number> = {
  part_added: 0x20c77a,
  part_removed: 0xf04f5f,
  transform_changed: 0xffad32,
  color_changed: 0x8b6cf0,
  part_replaced: 0x21a8d8,
  ambiguous: 0xff7a18,
};

/** ComponentDiffScene 并行渲染基准/当前 GLB，并同步相机与变化高亮。
 * 两个 GLB 保留相同的 LDraw 根转换；模型只执行一次共同居中，不能各自居中后破坏相对位置。
 */
export function ComponentDiffScene({
  afterLabel,
  afterModel,
  beforeLabel,
  beforeModel,
  diff,
  emptyBeforeLabel,
  focus,
  loadFailedLabel,
  registerReset,
}: ComponentDiffSceneProps) {
  const beforeMountRef = React.useRef<HTMLDivElement | null>(null);
  const afterMountRef = React.useRef<HTMLDivElement | null>(null);
  const registerResetRef = React.useRef(registerReset);
  const activeFocusRef = React.useRef(focus);
  const focusHandlerRef = React.useRef<((target: ComponentDiffFocus | null) => void) | null>(null);
  registerResetRef.current = registerReset;
  activeFocusRef.current = focus;
  const [loadFailed, setLoadFailed] = React.useState(false);

  React.useEffect(() => {
    focusHandlerRef.current?.(focus);
  }, [focus]);

  React.useEffect(() => {
    const beforeMount = beforeMountRef.current;
    const afterMount = afterMountRef.current;
    if (!beforeMount || !afterMount) return undefined;

    let disposed = false;
    let animationFrame = 0;
    const abortController = new AbortController();
    const beforePane = createPane(beforeMount, 0xf7f2f3);
    const afterPane = createPane(afterMount, 0xf0f7f4);
    const pulseMaterials: PulseMaterial[] = [];
    const helpers: THREE.BoxHelper[] = [];
    const roots: THREE.Object3D[] = [];
    const floors: THREE.Mesh[] = [];
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setLoadFailed(false);

    const initialize = async () => {
      try {
        const [beforeRoot, afterRoot] = await Promise.all([
          beforeModel ? loadPreviewModel(beforeModel.url, abortController.signal) : Promise.resolve(null),
          loadPreviewModel(afterModel.url, abortController.signal),
        ]);
        if (disposed) {
          if (beforeRoot) disposeObject(beforeRoot);
          disposeObject(afterRoot);
          return;
        }
        if (beforeRoot) {
          roots.push(beforeRoot);
          beforePane.scene.add(beforeRoot);
        }
        roots.push(afterRoot);
        afterPane.scene.add(afterRoot);

        // 两侧使用共同世界 Box 计算同一个中心；这样移动、删除与新增仍处在可直接比较的位置。
        const combinedBox = new THREE.Box3();
        if (beforeRoot) combinedBox.union(new THREE.Box3().setFromObject(beforeRoot));
        combinedBox.union(new THREE.Box3().setFromObject(afterRoot));
        const center = combinedBox.getCenter(new THREE.Vector3());
        beforeRoot?.position.sub(center);
        afterRoot.position.sub(center);
        beforeRoot?.updateMatrixWorld(true);
        afterRoot.updateMatrixWorld(true);
        const centeredBox = combinedBox.clone().translate(center.clone().multiplyScalar(-1));

        const beforeStyles = diffStyles(diff, 'before');
        const afterStyles = diffStyles(diff, 'after');
        if (beforeRoot) {
          styleModel(beforeRoot, beforeStyles, 'before', beforePane.scene, pulseMaterials, helpers, 0.22);
        }
        styleModel(afterRoot, afterStyles, 'after', afterPane.scene, pulseMaterials, helpers, 0.42);

        floors.push(addFloor(beforePane.scene, centeredBox));
        floors.push(addFloor(afterPane.scene, centeredBox));
        fitCameraToBox(beforePane.camera, beforePane.controls, centeredBox);
        copyCamera(beforePane, afterPane);
        const reset = () => {
          fitCameraToBox(beforePane.camera, beforePane.controls, centeredBox);
          copyCamera(beforePane, afterPane);
        };
        focusHandlerRef.current = (target) => {
          if (!target) {
            reset();
            return;
          }
          const focusBox = new THREE.Box3();
          const beforeNode = target.beforeInstanceId && beforeRoot
            ? findInstanceNode(beforeRoot, target.beforeInstanceId)
            : null;
          const afterNode = target.afterInstanceId
            ? findInstanceNode(afterRoot, target.afterInstanceId)
            : null;
          if (beforeNode) focusBox.expandByObject(beforeNode);
          if (afterNode) focusBox.expandByObject(afterNode);
          if (focusBox.isEmpty()) return;
          fitCameraToBox(beforePane.camera, beforePane.controls, focusBox);
          copyCamera(beforePane, afterPane);
        };
        registerResetRef.current?.(reset);
        focusHandlerRef.current(activeFocusRef.current);
      } catch (error) {
        if (!disposed && !(error instanceof DOMException && error.name === 'AbortError')) {
          setLoadFailed(true);
        }
      }
    };
    void initialize();

    let syncing = false;
    const syncFromBefore = () => {
      if (syncing) return;
      syncing = true;
      copyCamera(beforePane, afterPane);
      syncing = false;
    };
    const syncFromAfter = () => {
      if (syncing) return;
      syncing = true;
      copyCamera(afterPane, beforePane);
      syncing = false;
    };
    beforePane.controls.addEventListener('change', syncFromBefore);
    afterPane.controls.addEventListener('change', syncFromAfter);

    const resize = () => {
      resizePane(beforePane);
      resizePane(afterPane);
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(beforeMount);
    resizeObserver.observe(afterMount);
    resize();

    const startedAt = performance.now();
    const animate = (time: number) => {
      animationFrame = window.requestAnimationFrame(animate);
      beforePane.controls.update();
      afterPane.controls.update();
      if (!reduceMotion) {
        const pulse = 0.72 + 0.28 * ((Math.sin((time - startedAt) / 420) + 1) / 2);
        pulseMaterials.forEach(({ baseOpacity, material }) => {
          material.opacity = Math.min(1, baseOpacity * pulse);
          if (material instanceof THREE.MeshStandardMaterial) {
            material.emissiveIntensity = 0.35 + pulse * 0.75;
          }
        });
      }
      beforePane.renderer.render(beforePane.scene, beforePane.camera);
      afterPane.renderer.render(afterPane.scene, afterPane.camera);
    };
    animationFrame = window.requestAnimationFrame(animate);

    return () => {
      disposed = true;
      abortController.abort();
      registerResetRef.current?.(null);
      focusHandlerRef.current = null;
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      beforePane.controls.removeEventListener('change', syncFromBefore);
      afterPane.controls.removeEventListener('change', syncFromAfter);
      roots.forEach(disposeObject);
      helpers.forEach((helper) => {
        helper.removeFromParent();
        helper.geometry.dispose();
        disposeMaterial(helper.material);
      });
      floors.forEach((floor) => {
        floor.removeFromParent();
        floor.geometry.dispose();
        disposeMaterial(floor.material);
      });
      disposePane(beforePane);
      disposePane(afterPane);
    };
  }, [afterModel.artifactId, afterModel.url, beforeModel?.artifactId, beforeModel?.url, diff]);

  return (
    <div className="component-diff-scenes">
      <section className="component-diff-pane">
        <header><span className="component-diff-side-before" />{beforeLabel}</header>
        <div aria-hidden="true" className="component-diff-canvas" ref={beforeMountRef} />
        {!beforeModel ? <div className="component-diff-empty">{emptyBeforeLabel}</div> : null}
      </section>
      <section className="component-diff-pane">
        <header><span className="component-diff-side-after" />{afterLabel}</header>
        <div aria-hidden="true" className="component-diff-canvas" ref={afterMountRef} />
      </section>
      {loadFailed ? <div className="component-diff-load-error">{loadFailedLabel}</div> : null}
    </div>
  );
}

function createPane(mount: HTMLDivElement, background: number): PaneRuntime {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(background);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 300);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  mount.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.rotateSpeed = 0.75;
  controls.zoomSpeed = 0.8;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x718096, 2.2));
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.1);
  keyLight.position.set(6, 9, 7);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0xaccbff, 1.25);
  fillLight.position.set(-5, 3, -4);
  scene.add(fillLight);
  return { camera, controls, mount, renderer, scene };
}

async function loadPreviewModel(url: string, signal: AbortSignal): Promise<THREE.Group> {
  const response = await apiFetch(url, { signal }, 'component_repo.preview_unavailable');
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  const gltf = await loader.parseAsync(await response.arrayBuffer(), '');
  return gltf.scene;
}

function diffStyles(diff: ComponentVersionDiffResponse, side: 'before' | 'after'): Map<string, ComponentVersionDiffChangeKind | 'ambiguous'> {
  const styles = new Map<string, ComponentVersionDiffChangeKind | 'ambiguous'>();
  diff.instanceChanges.forEach((change) => {
    const state = side === 'before' ? change.before : change.after;
    if (state) styles.set(state.instanceId, change.kind);
  });
  diff.ambiguousGroups.forEach((group) => {
    const ids = side === 'before' ? group.beforeInstanceIds : group.afterInstanceIds;
    ids.forEach((id) => styles.set(id, 'ambiguous'));
  });
  return styles;
}

function styleModel(
  root: THREE.Object3D,
  styles: Map<string, ComponentVersionDiffChangeKind | 'ambiguous'>,
  side: 'before' | 'after',
  scene: THREE.Scene,
  pulseMaterials: PulseMaterial[],
  helpers: THREE.BoxHelper[],
  contextOpacity: number,
) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.material = cloneMaterials(object.material);
    forEachMaterial(object.material, (material) => {
      material.transparent = true;
      material.opacity = contextOpacity;
      material.depthWrite = false;
    });
  });
  styles.forEach((kind, instanceID) => {
    const node = findInstanceNode(root, instanceID);
    if (!node) return;
    const color = changeColor(kind, side);
    node.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      forEachMaterial(object.material, (material) => {
        material.opacity = 1;
        material.depthWrite = true;
        setMaterialColor(material, color);
        pulseMaterials.push({ baseOpacity: 1, material });
      });
    });
    const helper = new THREE.BoxHelper(node, color);
    helper.material.transparent = true;
    helper.material.opacity = 1;
    scene.add(helper);
    helpers.push(helper);
    pulseMaterials.push({ baseOpacity: 1, material: helper.material });
  });
}

// GLTFLoader 会为动画路径安全性移除节点名中的 `/.:[]`；Diff 仍返回未改写的场景实例路径。
// 优先读取未来 GLB 可携带的 extras，现有 v4 Artifact 则按 Three 相同规则匹配节点名。
function findInstanceNode(root: THREE.Object3D, instanceID: string): THREE.Object3D | undefined {
  let matched: THREE.Object3D | undefined;
  root.traverse((object) => {
    if (matched) return;
    if (object.userData.componentInstanceId === instanceID) matched = object;
  });
  return matched ?? root.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(instanceID));
}

function changeColor(kind: ComponentVersionDiffChangeKind | 'ambiguous', side: 'before' | 'after'): number {
  if (kind === 'part_replaced') return side === 'before' ? changeColors.part_removed : changeColors.part_added;
  return changeColors[kind];
}

function cloneMaterials(material: THREE.Material | THREE.Material[]): THREE.Material | THREE.Material[] {
  return Array.isArray(material) ? material.map((item) => item.clone()) : material.clone();
}

function forEachMaterial(material: THREE.Material | THREE.Material[], callback: (item: THREE.Material) => void) {
  (Array.isArray(material) ? material : [material]).forEach(callback);
}

function setMaterialColor(material: THREE.Material, color: number) {
  if ('color' in material && material.color instanceof THREE.Color) material.color.setHex(color);
  if (material instanceof THREE.MeshStandardMaterial) {
    material.emissive.setHex(color);
    material.emissiveIntensity = 0.9;
  }
  material.needsUpdate = true;
}

function addFloor(scene: THREE.Scene, box: THREE.Box3): THREE.Mesh {
  const size = box.getSize(new THREE.Vector3());
  const extent = Math.max(20, Math.max(size.x, size.z) * 3);
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(extent, extent),
    new THREE.MeshBasicMaterial({ color: 0xdce4ea, transparent: true, opacity: 0.34 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = box.min.y - 0.04;
  scene.add(floor);
  return floor;
}

function fitCameraToBox(camera: THREE.PerspectiveCamera, controls: OrbitControls, box: THREE.Box3) {
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maximum = Math.max(size.x, size.y, size.z, 1);
  const distance = maximum / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.35;
  camera.position.set(
    center.x + distance * 0.85,
    center.y + distance * 0.65,
    center.z + distance,
  );
  camera.near = Math.max(0.01, distance / 500);
  camera.far = Math.max(300, distance * 20);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function copyCamera(source: PaneRuntime, target: PaneRuntime) {
  target.camera.position.copy(source.camera.position);
  target.camera.quaternion.copy(source.camera.quaternion);
  target.camera.zoom = source.camera.zoom;
  target.camera.updateProjectionMatrix();
  target.controls.target.copy(source.controls.target);
  target.controls.update();
}

function resizePane(pane: PaneRuntime) {
  const width = Math.max(pane.mount.clientWidth, 1);
  const height = Math.max(pane.mount.clientHeight, 1);
  pane.camera.aspect = width / height;
  pane.camera.updateProjectionMatrix();
  pane.renderer.setSize(width, height, false);
}

function disposePane(pane: PaneRuntime) {
  pane.controls.dispose();
  pane.renderer.dispose();
  pane.renderer.domElement.remove();
}

function disposeObject(root: THREE.Object3D) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.dispose();
    forEachMaterial(object.material, disposeMaterial);
  });
  root.removeFromParent();
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  forEachMaterial(material, (item) => item.dispose());
}
