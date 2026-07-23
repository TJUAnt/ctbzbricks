import React from 'react';
import { Boxes, Layers3, MousePointer2, RotateCcw, Ruler, Sparkles } from 'lucide-react';
import * as THREE from 'three';
import { MeshoptDecoder } from 'meshoptimizer';
import { useParams } from 'react-router-dom';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { toCreasedNormals } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { apiFetch, errorMessage } from '../api/client';
import {
  loadLibraryItemPreview,
  type ComponentPreviewResponse,
} from '../componentRepo/componentRepoApi';
import { resolvedLocale, useAppTranslation } from '../i18n';
import { formatNumber } from '../i18n/formatters';

type ResetRegistration = (reset: (() => void) | null) => void;
type ViewerState =
  | { status: 'loading'; preview: null; error: null }
  | { status: 'ready'; preview: ComponentPreviewResponse; error: null }
  | { status: 'error'; preview: null; error: string };

const CREASE_ANGLE_RADIANS = Math.PI / 3;
const EDGE_THRESHOLD_DEGREES = 42;

export function PartViewerPage() {
  const tr = useAppTranslation();
  const locale = resolvedLocale();
  const { itemType: rawItemType, itemId } = useParams<{
    itemType: string;
    itemId: string;
  }>();
  const itemType = rawItemType === 'part' || rawItemType === 'component'
    ? rawItemType
    : null;
  const isPart = itemType === 'part';
  const resetViewRef = React.useRef<(() => void) | null>(null);
  const [state, setState] = React.useState<ViewerState>({
    status: 'loading',
    preview: null,
    error: null,
  });
  const registerReset = React.useCallback<ResetRegistration>((reset) => {
    resetViewRef.current = reset;
  }, []);

  React.useEffect(() => {
    let active = true;
    setState({ status: 'loading', preview: null, error: null });
    if (!itemType || !itemId) {
      setState({
        status: 'error',
        preview: null,
        error: tr('partSearch:viewerInvalidItem'),
      });
      return () => {
        active = false;
      };
    }
    void loadLibraryItemPreview(itemType, itemId)
      .then((preview) => {
        if (active) setState({ status: 'ready', preview, error: null });
      })
      .catch((error: unknown) => {
        if (active) {
          setState({
            status: 'error',
            preview: null,
            error: errorMessage(error, 'common.unknown'),
          });
        }
      });
    return () => {
      active = false;
    };
  }, [itemId, itemType, locale, tr]);

  const preview = state.preview;

  return (
    <main className="part-viewer-page">
      <header className="part-viewer-header">
        <div className="part-viewer-heading">
          <span className="part-viewer-heading-icon">
            <Boxes aria-hidden="true" />
          </span>
          <div>
            <span className="part-viewer-eyebrow">{tr('partSearch:viewerLibraryBadge')}</span>
            <h1>
              {tr(isPart ? 'partSearch:viewerPartTitle' : 'partSearch:viewerComponentTitle')}
            </h1>
            <p>
              {tr(isPart ? 'partSearch:viewerPartSubtitle' : 'partSearch:viewerDatabaseSubtitle')}
            </p>
          </div>
        </div>
        <span className={`part-viewer-ready part-viewer-ready-${state.status}`}>
          <span aria-hidden="true" />
          {state.status === 'ready'
            ? tr('partSearch:viewerReady')
            : state.status === 'loading'
              ? tr('partSearch:viewerItemLoading')
              : tr('partSearch:viewerLoadFailed')}
        </span>
      </header>

      <section className="part-viewer-layout">
        <div className="part-viewer-stage">
          {preview ? <ComponentScene preview={preview} registerReset={registerReset} /> : null}
          {state.status === 'loading' ? (
            <div className="part-viewer-stage-state">
              <span className="part-viewer-spinner" aria-hidden="true" />
              <strong>{tr('partSearch:viewerItemLoading')}</strong>
            </div>
          ) : null}
          {state.status === 'error' ? (
            <div className="part-viewer-stage-state part-viewer-stage-error" role="alert">
              <Boxes aria-hidden="true" />
              <strong>{tr('partSearch:viewerLoadFailed')}</strong>
              <p>{state.error}</p>
            </div>
          ) : null}
          {preview ? (
            <>
              <div className="part-viewer-instruction">
                <MousePointer2 aria-hidden="true" />
                <span>{tr('partSearch:viewerInstructions')}</span>
              </div>
              <button
                className="part-viewer-reset"
                onClick={() => resetViewRef.current?.()}
                type="button"
              >
                <RotateCcw aria-hidden="true" />
                {tr('partSearch:viewerReset')}
              </button>
            </>
          ) : null}
        </div>

        <aside className="part-viewer-sidebar">
          <section className="part-viewer-card part-viewer-part-card">
            <div className="part-viewer-card-title">
              <Boxes aria-hidden="true" />
              <span>{tr('partSearch:viewerSelectedItem')}</span>
            </div>
            <strong>
              {preview ? previewName(preview.source.name) : tr('partSearch:viewerItemLoading')}
            </strong>
            {preview ? <small>{preview.source.id}</small> : null}
            <div className="part-viewer-status-row">
              <span>{tr('partSearch:viewerStatus')}</span>
              <em>
                {preview
                  ? itemStatusLabel(preview.source.kind, preview.source.status, tr)
                  : tr('partSearch:viewerItemLoading')}
              </em>
            </div>
          </section>

          <section className="part-viewer-card">
            <div className="part-viewer-card-title">
              <Ruler aria-hidden="true" />
              <span>{tr('partSearch:viewerDimensions')}</span>
            </div>
            <dl className="part-viewer-dimensions">
              <DimensionRow
                label={tr('partSearch:length')}
                unit={tr('partSearch:stud')}
                value={preview?.logicalSize.widthStud}
              />
              <DimensionRow
                label={tr('partSearch:width')}
                unit={tr('partSearch:stud')}
                value={preview?.logicalSize.depthStud}
              />
              <DimensionRow
                label={tr('partSearch:height')}
                unit={tr('partSearch:plateUnit')}
                value={preview?.logicalSize.heightPlate}
              />
            </dl>
          </section>

          <section className="part-viewer-card part-viewer-renderer-card">
            <div className="part-viewer-card-title">
              <Layers3 aria-hidden="true" />
              <span>
                {tr(isPart ? 'partSearch:viewerPartGeometry' : 'partSearch:viewerStructure')}
              </span>
            </div>
            <strong>{formatNumber(preview?.partCount ?? 0)}</strong>
            <p>
              {tr(isPart ? 'partSearch:viewerMeshCount' : 'partSearch:viewerPartCount')}
            </p>
          </section>

          <section className="part-viewer-card part-viewer-renderer-card">
            <div className="part-viewer-card-title">
              <Sparkles aria-hidden="true" />
              <span>{tr('partSearch:viewerRenderer')}</span>
            </div>
            <strong>{tr('partSearch:viewerRendererValue')}</strong>
            <p>
              {tr(
                isPart
                  ? 'partSearch:viewerPartRendererDescription'
                  : 'partSearch:viewerDatabaseRendererDescription',
              )}
            </p>
          </section>
        </aside>
      </section>
    </main>
  );
}

function itemStatusLabel(
  kind: ComponentPreviewResponse['source']['kind'],
  status: string,
  tr: ReturnType<typeof useAppTranslation>,
): string {
  if (kind === 'part') return tr('partSearch:viewerReady');
  if (status === 'uploaded') return tr('componentRepo:uploaded');
  if (status === 'parsing') return tr('componentRepo:parsing');
  if (status === 'parsed' || status === 'pending_review') {
    return tr('componentRepo:pendingReview');
  }
  if (status === 'in_review') return tr('componentRepo:inReview');
  if (status === 'active') return tr('componentRepo:published');
  if (status === 'draft') return tr('componentRepo:draft');
  if (status === 'archived') return tr('componentRepo:archived');
  if (status === 'failed') return tr('componentRepo:failed');
  return tr('partSearch:viewerUnknownStatus');
}

function previewName(name: string): string {
  return name.replace(/\.(io|ldr|mpd)$/i, '');
}

function DimensionRow({
  label,
  unit,
  value,
}: {
  label: string;
  unit: string;
  value: number | undefined;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value === undefined ? '—' : `${formatNumber(value, { maximumFractionDigits: 2 })} ${unit}`}</dd>
    </div>
  );
}

export function ComponentScene({
  preview,
  registerReset,
}: {
  preview: ComponentPreviewResponse;
  registerReset: ResetRegistration;
}) {
  const mountRef = React.useRef<HTMLDivElement | null>(null);
  const tr = useAppTranslation();
  const [loadFailed, setLoadFailed] = React.useState(false);

  React.useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#eef3f8');
    const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 200);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.rotateSpeed = 0.75;
    controls.zoomSpeed = 0.8;

    scene.add(new THREE.HemisphereLight('#ffffff', '#718096', 2.1));
    const keyLight = new THREE.DirectionalLight('#ffffff', 3.2);
    keyLight.position.set(6, 9, 7);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(1024, 1024);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight('#a6c8ff', 1.4);
    fillLight.position.set(-5, 3, -4);
    scene.add(fillLight);

    let component: THREE.Object3D | null = null;
    let floor: THREE.Mesh | null = null;
    let disposed = false;
    const abortController = new AbortController();
    setLoadFailed(false);
    void loadBinaryPreview(preview.model.url, abortController.signal)
      .then((loadedComponent) => {
        if (disposed) {
          disposeObject(loadedComponent);
          return;
        }
        component = prepareLoadedComponent(loadedComponent);
        scene.add(component);
        centerObject(component);
        floor = new THREE.Mesh(
          new THREE.PlaneGeometry(60, 60),
          new THREE.ShadowMaterial({ color: '#405060', opacity: 0.15 }),
        );
        const componentBox = new THREE.Box3().setFromObject(component);
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = componentBox.min.y - 0.08;
        floor.receiveShadow = true;
        scene.add(floor);
        const resetView = () => {
          if (component) fitCameraToObject(camera, controls, component);
        };
        resetView();
        registerReset(resetView);
      })
      .catch((error: unknown) => {
        if (!disposed && !(error instanceof DOMException && error.name === 'AbortError')) {
          setLoadFailed(true);
        }
      });

    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(mount);
    resize();

    let animationFrame = 0;
    const animate = () => {
      animationFrame = window.requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      abortController.abort();
      registerReset(null);
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      if (component) disposeObject(component);
      if (floor) {
        floor.geometry.dispose();
        disposeMaterial(floor.material);
      }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [preview, registerReset]);

  return (
    <div aria-hidden="true" className="part-viewer-canvas" ref={mountRef}>
      {loadFailed ? <div className="asset-error">{tr('componentRepo:previewUnavailable')}</div> : null}
    </div>
  );
}

async function loadBinaryPreview(url: string, signal: AbortSignal): Promise<THREE.Group> {
  const response = await apiFetch(url, { signal }, 'component_repo.preview_unavailable');
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  const gltf = await loader.parseAsync(await response.arrayBuffer(), '');
  return gltf.scene;
}

function prepareLoadedComponent(component: THREE.Object3D): THREE.Object3D {
  const meshes: THREE.Mesh[] = [];
  component.traverse((object) => {
    if (object instanceof THREE.Mesh) meshes.push(object);
  });
  const processed = new Map<THREE.BufferGeometry, THREE.BufferGeometry>();
  meshes.forEach((mesh) => {
    const sourceGeometry = mesh.geometry;
    let geometry = processed.get(sourceGeometry);
    if (!geometry) {
      geometry = toCreasedNormals(sourceGeometry, CREASE_ANGLE_RADIANS);
      geometry.computeBoundingBox();
      geometry.computeBoundingSphere();
      processed.set(sourceGeometry, geometry);
      sourceGeometry.dispose();
    }
    mesh.geometry = geometry;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    materials.forEach((material) => {
      material.side = THREE.DoubleSide;
      material.needsUpdate = true;
    });
    mesh.add(
      new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry, EDGE_THRESHOLD_DEGREES),
        new THREE.LineBasicMaterial({ color: '#24303d', transparent: true, opacity: 0.2 }),
      ),
    );
  });
  return component;
}

function centerObject(object: THREE.Object3D) {
  const box = new THREE.Box3().setFromObject(object);
  const center = box.getCenter(new THREE.Vector3());
  object.position.sub(center);
}

function fitCameraToObject(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  object: THREE.Object3D,
) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 1);
  const distance = radius * 2.25;
  camera.position.set(distance, distance * 0.78, distance);
  camera.near = Math.max(distance / 100, 0.01);
  camera.far = distance * 20;
  camera.updateProjectionMatrix();
  controls.minDistance = radius * 0.8;
  controls.maxDistance = radius * 8;
  controls.target.set(0, 0, 0);
  controls.update();
}

function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
      geometries.add(object.geometry);
      const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
      objectMaterials.forEach((material) => materials.add(material));
    }
  });
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  const materials = Array.isArray(material) ? material : [material];
  materials.forEach((item) => item.dispose());
}
