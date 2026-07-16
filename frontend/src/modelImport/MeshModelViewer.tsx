import React from 'react';
import { Box, Palette } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import appConfig from '../app/appConfig.json';
import type { ModelAsset } from '../assets/modelAssetApi';
import { meshModelFileUrl } from './meshModelApi';

type MeshColor = {
  hex: string;
  materialName: string;
  faceCount: number;
  coverageRatio: number;
};

type MeshColorSummary = {
  colors: MeshColor[];
};

export function MeshModelViewer({ modelAsset }: { modelAsset: ModelAsset }) {
  return (
    <section className="model-viewer-layout">
      <div className="model-viewer-canvas">
        <MeshScene modelAsset={modelAsset} />
      </div>
      <aside className="model-viewer-panel">
        <MeshColorPanel modelAsset={modelAsset} />
      </aside>
    </section>
  );
}

function MeshScene({ modelAsset }: { modelAsset: ModelAsset }) {
  const mountRef = React.useRef<HTMLDivElement | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const mount = mountRef.current;
    if (!mount) {
      return undefined;
    }
    setError(null);
    let active = true;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(appConfig.meshViewer.backgroundColor);
    const camera = new THREE.PerspectiveCamera(
      appConfig.meshViewer.fieldOfView,
      mount.clientWidth / mount.clientHeight,
      appConfig.meshViewer.nearPlane,
      appConfig.meshViewer.farPlane,
    );
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(
      mount.clientWidth || appConfig.meshViewer.resizeWidthFallback,
      mount.clientHeight || appConfig.meshViewer.resizeHeightFallback,
    );
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(
      new THREE.AmbientLight(
        appConfig.meshViewer.ambientLightColor,
        appConfig.meshViewer.ambientLightIntensity,
      ),
    );
    const directionalLight = new THREE.DirectionalLight(
      appConfig.meshViewer.directionalLightColor,
      appConfig.meshViewer.directionalLightIntensity,
    );
    setVector3(directionalLight.position, appConfig.meshViewer.directionalLightPosition);
    scene.add(directionalLight);

    const loader = new GLTFLoader();
    const modelUrl = meshModelFileUrl(
      appConfig.meshModelFileApiUrl,
      appConfig.meshRoutePlaceholders.modelId,
      modelAsset.id,
    );
    const disposableMaterials: THREE.Material[] = [];
    loader.load(
      modelUrl,
      (gltf) => {
        if (!active) {
          return;
        }
        scene.add(gltf.scene);
        gltf.scene.scale.setScalar(appConfig.meshViewer.defaultMeshScale);
        centerSceneObject(gltf.scene, camera, controls);
        gltf.scene.traverse((object) => {
          if (object instanceof THREE.Mesh) {
            object.geometry.computeVertexNormals();
            if (Array.isArray(object.material)) {
              disposableMaterials.push(...object.material);
            } else {
              disposableMaterials.push(object.material);
            }
          }
        });
      },
      undefined,
      (loadError) => {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : appConfig.texts.loadFailed);
        }
      },
    );

    const resizeObserver = new ResizeObserver(() => {
      camera.aspect =
        (mount.clientWidth || appConfig.meshViewer.resizeWidthFallback) /
        (mount.clientHeight || appConfig.meshViewer.resizeHeightFallback);
      camera.updateProjectionMatrix();
      renderer.setSize(
        mount.clientWidth || appConfig.meshViewer.resizeWidthFallback,
        mount.clientHeight || appConfig.meshViewer.resizeHeightFallback,
      );
    });
    resizeObserver.observe(mount);

    let animationFrame = 0;
    const animate = () => {
      animationFrame = window.requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      active = false;
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
        }
      });
      disposableMaterials.forEach((material) => material.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [modelAsset.id]);

  return (
    <>
      <div className="mesh-viewer-canvas" ref={mountRef} />
      {error ? <div className="asset-error mesh-viewer-error">{error}</div> : null}
    </>
  );
}

function MeshColorPanel({ modelAsset }: { modelAsset: ModelAsset }) {
  const summary = meshColorSummary(modelAsset);
  return (
    <div className="mesh-viewer-panel">
      <div className="mesh-import-title">
        <Palette aria-hidden="true" />
        <span>{appConfig.texts.meshColorSummary}</span>
      </div>
      <div className="terrain-metric">
        <div className="terrain-metric-icon">
          <Box aria-hidden="true" />
        </div>
        <div>
          <span>{appConfig.texts.meshFile}</span>
          <strong>{modelAsset.sourceName}</strong>
        </div>
      </div>
      {summary && summary.colors.length > 0 ? (
        <div className="mesh-color-list">
          {summary.colors.map((color) => (
            <div className="mesh-color-row" key={`${color.materialName}-${color.hex}`}>
              <span style={{ backgroundColor: color.hex }} />
              <div>
                <strong>{color.materialName}</strong>
                <em>
                  {color.hex} / {appConfig.texts.meshFaceCount} {color.faceCount} /{' '}
                  {Math.round(
                    color.coverageRatio * appConfig.meshViewer.coveragePercentMultiplier,
                  )}
                  %
                </em>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="asset-empty">{appConfig.texts.meshNoColors}</div>
      )}
    </div>
  );
}

function centerSceneObject(
  object: THREE.Object3D,
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
): void {
  const box = new THREE.Box3().setFromObject(object);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  object.position.sub(center);
  const distance = Math.max(
    size.x,
    size.y,
    size.z,
    appConfig.meshViewer.minimumCameraDistance,
  ) * appConfig.meshViewer.cameraDistanceMultiplier;
  camera.position.set(distance, distance, distance);
  controls.target.set(0, 0, 0);
  camera.lookAt(controls.target);
  controls.update();
}

function meshColorSummary(modelAsset: ModelAsset): MeshColorSummary | null {
  const summary = modelAsset.metadata?.colorSummary;
  if (!summary || typeof summary !== 'object' || !('colors' in summary)) {
    return null;
  }
  return summary as MeshColorSummary;
}

function setVector3(vector: THREE.Vector3, values: number[]): void {
  vector.set(values[0], values[1], values[2]);
}
