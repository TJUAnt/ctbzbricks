import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

const materialEnvironmentIntensity: Record<string, number> = {
  plastic: 1,
  glass: 1.05,
  rubber: 0.42,
  chrome: 1.35,
  pearl: 1.15,
  metal: 1.2,
  matte_metal: 0.92,
  luminous: 0.85,
  glitter: 1.2,
  speckle: 0.8,
};

export type StudioPreviewProfile = 'viewer' | 'part-neutral';

const partNeutralColor = new THREE.Color('#7c8ca3');

const studioLightingProfiles: Record<StudioPreviewProfile, {
  environment: number;
  hemisphere: number;
  key: number;
  fill: number;
}> = {
  viewer: { environment: 0.92, hemisphere: 0.75, key: 2.25, fill: 0.72 },
  'part-neutral': { environment: 0.58, hemisphere: 0.46, key: 1.55, fill: 0.28 },
};

/** configureStudioRenderer 固定颜色空间与色调映射，使列表缩略图和详情查看器使用同一摄影棚输出。 */
export function configureStudioRenderer(renderer: THREE.WebGLRenderer) {
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.05;
}

/** installStudioEnvironment 创建一次预过滤摄影棚环境；返回值负责释放对应 GPU 纹理。 */
export function installStudioEnvironment(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  profile: StudioPreviewProfile = 'viewer',
): () => void {
  const generator = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const target = generator.fromScene(room, 0.04);
  room.dispose();
  generator.dispose();
  scene.environment = target.texture;
  scene.environmentIntensity = studioLightingProfiles[profile].environment;
  return () => {
    if (scene.environment === target.texture) scene.environment = null;
    target.dispose();
  };
}

/** addStudioLights 按查看器或缩略图档位添加固定三点光；详情页可选择启用主光阴影。 */
export function addStudioLights(
  scene: THREE.Scene,
  castShadow = false,
  profile: StudioPreviewProfile = 'viewer',
) {
  const lighting = studioLightingProfiles[profile];
  scene.add(new THREE.HemisphereLight('#ffffff', '#74808f', lighting.hemisphere));
  const keyLight = new THREE.DirectionalLight('#fff7ed', lighting.key);
  keyLight.position.set(6, 9, 7);
  keyLight.castShadow = castShadow;
  if (castShadow) keyLight.shadow.mapSize.set(1024, 1024);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight('#b8d3ff', lighting.fill);
  fillLight.position.set(-5, 3, -4);
  scene.add(fillLight);
}

/** tuneStudioMaterial 应用目标预览档位；Part 中性档位只改常量参数，不增加纹理、网格或额外渲染 pass。 */
export function tuneStudioMaterial(
  material: THREE.Material,
  profile: StudioPreviewProfile = 'viewer',
) {
  material.side = THREE.DoubleSide;
  if (material instanceof THREE.MeshStandardMaterial) {
    const materialClass = typeof material.userData.materialClass === 'string'
      ? material.userData.materialClass
      : 'plastic';
    material.envMapIntensity = materialEnvironmentIntensity[materialClass] ?? 1;
    if (profile === 'part-neutral') {
      // Part 预览表达几何而非零件颜色；中等明度冷灰配合低补光，避免浅背景吞没孔洞和折角。
      material.color.copy(partNeutralColor);
      material.metalness = 0;
      material.roughness = 0.56;
      material.envMapIntensity = 0.62;
    }
    if (material instanceof THREE.MeshPhysicalMaterial && material.transmission > 0) {
      // GLB 保留 alpha 作为不支持 transmission 的兼容层；Three.js 已支持物理透射，运行时只使用后者。
      material.opacity = 1;
      material.transparent = false;
      material.depthWrite = true;
    }
  }
  material.needsUpdate = true;
}

/** tuneStudioObject 批量准备模型材质与包围盒，不改变 GLB 中的几何和节点结构。 */
export function tuneStudioObject(
  root: THREE.Object3D,
  profile: StudioPreviewProfile = 'viewer',
) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.computeBoundingBox();
    object.geometry.computeBoundingSphere();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => tuneStudioMaterial(material, profile));
  });
}
