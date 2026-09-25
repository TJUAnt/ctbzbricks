import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { addStudioLights, tuneStudioMaterial, tuneStudioObject } from '../studioPreviewRendering';

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

  it('uses a bounded neutral plastic profile for Part thumbnails', () => {
    const material = new THREE.MeshStandardMaterial({
      color: '#ffffff',
      metalness: 0.8,
      roughness: 0.9,
    });

    tuneStudioMaterial(material, 'part-neutral');

    expect(material.color.equals(new THREE.Color('#7c8ca3'))).toBe(true);
    expect(material.metalness).toBe(0);
    expect(material.roughness).toBeCloseTo(0.56);
    expect(material.envMapIntensity).toBeCloseTo(0.62);
  });

  it('keeps the Part thumbnail light count fixed while reducing fill intensity', () => {
    const scene = new THREE.Scene();

    addStudioLights(scene, false, 'part-neutral');

    const lights = scene.children.filter((child): child is THREE.Light => child instanceof THREE.Light);
    expect(lights).toHaveLength(3);
    expect(lights.map((light) => light.intensity)).toEqual([0.46, 1.55, 0.28]);
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
