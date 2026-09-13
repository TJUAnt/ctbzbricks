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
): () => void {
  const generator = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const target = generator.fromScene(room, 0.04);
  room.dispose();
  generator.dispose();
  scene.environment = target.texture;
  scene.environmentIntensity = 0.92;
  return () => {
    if (scene.environment === target.texture) scene.environment = null;
    target.dispose();
  };
}

/** addStudioLights 添加稳定的主光、补光和低强度环境光；详情页可选择启用主光阴影。 */
export function addStudioLights(scene: THREE.Scene, castShadow = false) {
  scene.add(new THREE.HemisphereLight('#ffffff', '#74808f', 0.75));
  const keyLight = new THREE.DirectionalLight('#fff7ed', 2.25);
  keyLight.position.set(6, 9, 7);
  keyLight.castShadow = castShadow;
  if (castShadow) keyLight.shadow.mapSize.set(1024, 1024);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight('#b8d3ff', 0.72);
  fillLight.position.set(-5, 3, -4);
  scene.add(fillLight);
}

/** tuneStudioMaterial 应用查看器侧的环境反射强度，并避免透明度与物理透射被重复计算。 */
export function tuneStudioMaterial(material: THREE.Material) {
  material.side = THREE.DoubleSide;
  if (material instanceof THREE.MeshStandardMaterial) {
    const materialClass = typeof material.userData.materialClass === 'string'
      ? material.userData.materialClass
      : 'plastic';
    material.envMapIntensity = materialEnvironmentIntensity[materialClass] ?? 1;
    if (material instanceof THREE.MeshPhysicalMaterial && material.transmission > 0) {
      // GLB 保留 alpha 作为不支持 transmission 的兼容层；Three.js 已支持物理透射，运行时只使用后者。
      material.opacity = 1;
      material.transparent = false;
      material.depthWrite = true;
    }
  }
  material.needsUpdate = true;
}

/** tuneStudioObject 批量准备模型材质与包围盒，不改变 GLB 中的几何、颜色编码和节点结构。 */
export function tuneStudioObject(root: THREE.Object3D) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.computeBoundingBox();
    object.geometry.computeBoundingSphere();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach(tuneStudioMaterial);
  });
}
