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
  loadPartPreview,
  type ComponentPreviewResponse,
  type ReadyPartPreviewResponse,
} from '../componentRepo/componentRepoApi';
import { resolvedLocale, useAppTranslation } from '../i18n';
import { formatNumber } from '../i18n/formatters';

type ResetRegistration = (reset: (() => void) | null) => void;
export type ComponentSceneConnector = {
  id: string;
  position: Record<string, number>;
  accessAxis?: Record<string, number>;
};
type ViewerState =
  | { status: 'loading'; preview: null; error: null }
  | { status: 'ready'; preview: ReadyPartPreviewResponse; error: null }
  | { status: 'error'; preview: null; error: string };

const CREASE_ANGLE_RADIANS = Math.PI / 3;
const EDGE_THRESHOLD_DEGREES = 42;

export function PartViewerPage() {
  const tr = useAppTranslation();
  const locale = resolvedLocale();
  const { partLibraryVersionId, ldrawPartNum } = useParams<{
    partLibraryVersionId: string;
    ldrawPartNum: string;
  }>();
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
    if (!partLibraryVersionId || !ldrawPartNum) {
      setState({
        status: 'error',
        preview: null,
        error: tr('partSearch:viewerInvalidItem'),
      });
      return () => {
        active = false;
      };
    }
    void loadPartPreview(partLibraryVersionId, ldrawPartNum)
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
  }, [ldrawPartNum, partLibraryVersionId, locale, tr]);

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
              {tr('partSearch:viewerPartTitle')}
            </h1>
            <p>
              {tr('partSearch:viewerPartSubtitle')}
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
          {preview ? <ComponentScene preview={{ model: preview.model }} registerReset={registerReset} /> : null}
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
              {preview ? preview.name : tr('partSearch:viewerItemLoading')}
            </strong>
            {preview ? <small>{preview.ldrawPartNum}</small> : null}
            <div className="part-viewer-status-row">
              <span>{tr('partSearch:viewerStatus')}</span>
              <em>
                {preview
                  ? tr('partSearch:viewerReady')
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
                value={preview?.geometry.logicalWidthStud}
              />
              <DimensionRow
                label={tr('partSearch:width')}
                unit={tr('partSearch:stud')}
                value={preview?.geometry.logicalDepthStud}
              />
              <DimensionRow
                label={tr('partSearch:height')}
                unit={tr('partSearch:plateUnit')}
                value={preview?.geometry.logicalHeightPlate}
              />
            </dl>
          </section>

          <section className="part-viewer-card part-viewer-renderer-card">
            <div className="part-viewer-card-title">
              <Layers3 aria-hidden="true" />
              <span>
                {tr('partSearch:viewerPartGeometry')}
              </span>
            </div>
            <strong>{formatNumber(preview?.geometry.faceCount ?? 0)}</strong>
            <p>
              {tr('partSearch:viewerMeshCount')}
            </p>
          </section>

          <section className="part-viewer-card part-viewer-renderer-card">
            <div className="part-viewer-card-title">
              <Sparkles aria-hidden="true" />
              <span>{tr('partSearch:viewerRenderer')}</span>
            </div>
            <strong>{tr('partSearch:viewerRendererValue')}</strong>
            <p>
              {tr('partSearch:viewerPartRendererDescription')}
            </p>
          </section>
        </aside>
      </section>
    </main>
  );
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
  selectedConnector = null,
}: {
  preview: Pick<ComponentPreviewResponse, 'model'>;
  registerReset: ResetRegistration;
  selectedConnector?: ComponentSceneConnector | null;
}) {
  const mountRef = React.useRef<HTMLDivElement | null>(null);
  const connectorRootRef = React.useRef<THREE.Object3D | null>(null);
  const connectorMarkerRef = React.useRef<THREE.Group | null>(null);
  const registerResetRef = React.useRef(registerReset);
  const selectedConnectorRef = React.useRef(selectedConnector);
  registerResetRef.current = registerReset;
  selectedConnectorRef.current = selectedConnector;
  const tr = useAppTranslation();
  const [loadFailed, setLoadFailed] = React.useState(false);

  React.useEffect(() => {
    replaceConnectorMarker(
      connectorRootRef.current,
      connectorMarkerRef,
      selectedConnector,
    );
  }, [selectedConnector]);

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
        connectorRootRef.current = component.getObjectByName('component-root') ?? component;
        replaceConnectorMarker(
          connectorRootRef.current,
          connectorMarkerRef,
          selectedConnectorRef.current,
        );
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
        registerResetRef.current(resetView);
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
      registerResetRef.current(null);
      connectorRootRef.current = null;
      connectorMarkerRef.current = null;
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
  }, [preview.model.artifactId, preview.model.url]);

  return (
    <div aria-hidden="true" className="part-viewer-canvas" ref={mountRef}>
      {loadFailed ? <div className="asset-error">{tr('componentRepo:previewUnavailable')}</div> : null}
    </div>
  );
}

async function loadBinaryPreview(
  url: string,
  signal: AbortSignal,
): Promise<THREE.Group> {
  const response = await apiFetch(url, { signal }, 'component_repo.preview_unavailable');
  const buffer = await response.arrayBuffer();
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  const gltf = await loader.parseAsync(buffer, '');
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

function replaceConnectorMarker(
  parent: THREE.Object3D | null,
  markerRef: React.MutableRefObject<THREE.Group | null>,
  connector: ComponentSceneConnector | null,
) {
  const existing = markerRef.current;
  if (existing) {
    existing.removeFromParent();
    disposeObject(existing);
    markerRef.current = null;
  }
  if (!parent || !connector) return;
  const position = vectorFromRecord(connector.position);
  if (!position) return;

  const marker = new THREE.Group();
  marker.name = `selected-connector-${connector.id}`;
  marker.position.copy(position);

  const sphereMaterial = new THREE.MeshBasicMaterial({
    color: '#ff7a18',
    depthTest: false,
    transparent: true,
    opacity: 0.96,
  });
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(4.2, 20, 14), sphereMaterial);
  sphere.renderOrder = 1000;
  marker.add(sphere);

  const axis = vectorFromRecord(connector.accessAxis);
  if (axis && axis.lengthSq() > 0) {
    const arrow = new THREE.ArrowHelper(axis.normalize(), new THREE.Vector3(), 22, '#ff7a18', 7, 4);
    arrow.renderOrder = 1000;
    arrow.traverse((object) => {
      object.renderOrder = 1000;
      if (object instanceof THREE.Line || object instanceof THREE.Mesh) {
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.forEach((material) => {
          material.depthTest = false;
          material.transparent = true;
        });
      }
    });
    marker.add(arrow);
  }

  parent.add(marker);
  markerRef.current = marker;
}

function vectorFromRecord(value: Record<string, number> | undefined): THREE.Vector3 | null {
  if (!value) return null;
  const x = Number(value.x);
  const y = Number(value.y);
  const z = Number(value.z);
  if (![x, y, z].every(Number.isFinite)) return null;
  return new THREE.Vector3(x, y, z);
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
    if (
      object instanceof THREE.Mesh
      || object instanceof THREE.Line
      || object instanceof THREE.Points
    ) {
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
