import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { tuneStudioMaterial, tuneStudioObject } from '../studioPreviewRendering';

describe('Studio preview material runtime', () => {
  it('uses physical transmission once for supported GLB materials', () => {
    const material = new THREE.MeshPhysicalMaterial({
      opacity: 0.5,
      transparent: true,
      transmission: 0.72,
    });
    material.userData.materialClass = 'glass';

    tuneStudioMaterial(material);

    expect(material.opacity).toBe(1);
    expect(material.transparent).toBe(false);
    expect(material.depthWrite).toBe(true);
    expect(material.envMapIntensity).toBeCloseTo(1.05);
  });

  it('keeps rubber reflections below chrome reflections', () => {
    const rubber = new THREE.MeshPhysicalMaterial();
    rubber.userData.materialClass = 'rubber';
    const chrome = new THREE.MeshPhysicalMaterial();
    chrome.userData.materialClass = 'chrome';

    tuneStudioMaterial(rubber);
    tuneStudioMaterial(chrome);

    expect(rubber.envMapIntensity).toBeLessThan(chrome.envMapIntensity);
  });

  it('prepares every mesh material and geometry bound', () => {
    const material = new THREE.MeshStandardMaterial();
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const mesh = new THREE.Mesh(geometry, material);
    const root = new THREE.Group();
    root.add(mesh);

    tuneStudioObject(root);

    expect(geometry.boundingBox).not.toBeNull();
    expect(geometry.boundingSphere).not.toBeNull();
    expect(material.side).toBe(THREE.DoubleSide);
  });
});
