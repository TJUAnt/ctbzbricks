import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import terrainConfig from '../terrainConfig.json';

describe('terrain camera orientation', () => {
  function createTestCamera() {
    const camera = new THREE.PerspectiveCamera(
      terrainConfig.scene.fieldOfView,
      terrainConfig.testCamera.aspect,
      terrainConfig.scene.nearPlane,
      terrainConfig.scene.farPlane,
    );
    camera.position.set(
      terrainConfig.scene.cameraPosition[0],
      terrainConfig.scene.cameraPosition[1],
      terrainConfig.scene.cameraPosition[2],
    );
    camera.lookAt(
      new THREE.Vector3(
        terrainConfig.scene.cameraTarget[0],
        terrainConfig.scene.cameraTarget[1],
        terrainConfig.scene.cameraTarget[2],
      ),
    );
    camera.updateMatrixWorld();
    return camera;
  }

  it('projects east to the right side of west in the default view', () => {
    const camera = createTestCamera();
    const west = new THREE.Vector3(
      terrainConfig.testCamera.westPoint[0],
      terrainConfig.testCamera.westPoint[1],
      terrainConfig.testCamera.westPoint[2],
    ).project(camera);
    const east = new THREE.Vector3(
      terrainConfig.testCamera.eastPoint[0],
      terrainConfig.testCamera.eastPoint[1],
      terrainConfig.testCamera.eastPoint[2],
    ).project(camera);

    expect(east.x).toBeGreaterThan(west.x);
  });

  it('projects north above south in the default view', () => {
    const camera = createTestCamera();
    const north = new THREE.Vector3(
      terrainConfig.testCamera.northPoint[0],
      terrainConfig.testCamera.northPoint[1],
      terrainConfig.testCamera.northPoint[2],
    ).project(camera);
    const south = new THREE.Vector3(
      terrainConfig.testCamera.southPoint[0],
      terrainConfig.testCamera.southPoint[1],
      terrainConfig.testCamera.southPoint[2],
    ).project(camera);

    expect(north.y).toBeGreaterThan(south.y);
  });
});
