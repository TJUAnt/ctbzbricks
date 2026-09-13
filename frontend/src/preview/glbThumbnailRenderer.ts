import { MeshoptDecoder } from 'meshoptimizer';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { apiFetch } from '../api/client';
import {
  addStudioLights,
  configureStudioRenderer,
  installStudioEnvironment,
  tuneStudioObject,
} from './studioPreviewRendering';

export type GlbThumbnailModel = {
  artifactId: string;
  format: 'glb' | string;
  compression?: 'meshopt' | string;
  url: string;
  sha256: string;
  byteLength: number;
};

const thumbnailSize = 256;
// 背景色属于缩略图内容的一部分；调整后提升版本，避免继续读取旧浅色 WebP 缓存。
const rendererVersion = 'glb-thumbnail-v2';
const maxSourceBytes = 16 * 1024 * 1024;
const maxMemoryEntries = 128;
const maxPersistentEntries = 2_000;
const maxPersistentBytes = 100 * 1024 * 1024;
const databaseName = 'brickbuilder-glb-thumbnails';
const objectStoreName = 'thumbnails';
const memoryCache = new Map<string, Promise<Blob>>();
let renderTail: Promise<void> = Promise.resolve();
let sharedRenderer: ThumbnailRenderer | null = null;

type CachedThumbnail = {
  key: string;
  blob: Blob;
  byteLength: number;
  lastAccess: number;
};

/**
 * loadGlbThumbnailBlob 将不可变 GLB 产物按需转换成静态缩略图。
 * 下载最多四路并发，真正的 GPU 渲染始终串行复用一个 WebGL 上下文；结果按不可变 Artifact 缓存。
 */
export function loadGlbThumbnailBlob(model: GlbThumbnailModel, signal: AbortSignal): Promise<Blob> {
  const key = cacheKey(model);
  const existing = memoryCache.get(key);
  if (existing) return abortable(existing, signal);

  const pending = loadCachedOrRender(key, model, signal).catch((error) => {
    memoryCache.delete(key);
    throw error;
  });
  memoryCache.set(key, pending);
  trimMemoryCache();
  return abortable(pending, signal);
}

async function loadCachedOrRender(
  key: string,
  model: GlbThumbnailModel,
  signal: AbortSignal,
): Promise<Blob> {
  throwIfAborted(signal);
  const cached = await readPersistentThumbnail(key);
  if (cached) return cached;

  if (model.format !== 'glb' || model.byteLength > maxSourceBytes) {
    throw new Error('unsupported GLB preview model');
  }
  const buffer = await downloadSlots.run(signal, async () => {
    const response = await apiFetch(model.url, { signal }, 'component_repo.preview_unavailable');
    const value = await response.arrayBuffer();
    if (value.byteLength > maxSourceBytes) throw new Error('GLB preview model is too large');
    return value;
  });
  throwIfAborted(signal);
  const blob = await enqueueRender(buffer, signal);
  void writePersistentThumbnail({
    key,
    blob,
    byteLength: blob.size,
    lastAccess: Date.now(),
  });
  return blob;
}

function enqueueRender(buffer: ArrayBuffer, signal: AbortSignal): Promise<Blob> {
  const next = renderTail.catch(() => undefined).then(async () => {
    throwIfAborted(signal);
    sharedRenderer ??= new ThumbnailRenderer();
    return sharedRenderer.render(buffer, signal);
  });
  renderTail = next.then(() => undefined, () => undefined);
  return next;
}

/** ThumbnailRenderer 持有所有列表页共享的 WebGL context，避免每张卡片创建 canvas、控制器和 RAF。 */
class ThumbnailRenderer {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;

  constructor() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(thumbnailSize, thumbnailSize, false);
    configureStudioRenderer(this.renderer);
    this.renderer.setClearColor('#d8dde4', 1);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.01, 2_000);
    installStudioEnvironment(this.renderer, this.scene);
    addStudioLights(this.scene);
  }

  async render(buffer: ArrayBuffer, signal: AbortSignal): Promise<Blob> {
    throwIfAborted(signal);
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    const gltf = await loader.parseAsync(buffer, '');
    const object = gltf.scene;
    try {
      throwIfAborted(signal);
      prepareObject(object);
      centerObject(object);
      fitCamera(this.camera, object);
      this.scene.add(object);
      this.renderer.render(this.scene, this.camera);
      return await canvasToBlob(this.renderer.domElement);
    } finally {
      object.removeFromParent();
      disposeObject(object);
      this.renderer.renderLists.dispose();
    }
  }
}

function prepareObject(root: THREE.Object3D) {
  tuneStudioObject(root);
}

function centerObject(object: THREE.Object3D) {
  const center = new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3());
  object.position.sub(center);
  object.updateMatrixWorld(true);
}

// 相机方向与 Component/Part 详情页保持一致，让缩略图和打开详情后的初始朝向不发生跳变。
function fitCamera(camera: THREE.PerspectiveCamera, object: THREE.Object3D) {
  const size = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 1);
  const distance = radius * 2.25;
  camera.position.set(distance, distance * 0.78, distance);
  camera.near = Math.max(distance / 100, 0.01);
  camera.far = distance * 20;
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
}

function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Points)) return;
    geometries.add(object.geometry);
    const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
    objectMaterials.forEach((material) => materials.add(material));
  });
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('thumbnail encoding failed'));
    }, 'image/webp', 0.82);
  });
}

function cacheKey(model: GlbThumbnailModel): string {
  return `${rendererVersion}/${model.artifactId}/${model.sha256}/${thumbnailSize}/webp`;
}

function trimMemoryCache() {
  while (memoryCache.size > maxMemoryEntries) {
    const oldest = memoryCache.keys().next().value as string | undefined;
    if (!oldest) return;
    memoryCache.delete(oldest);
  }
}

async function readPersistentThumbnail(key: string): Promise<Blob | null> {
  const database = await openThumbnailDatabase();
  if (!database) return null;
  try {
    const cached = await requestValue<CachedThumbnail | undefined>(
      database.transaction(objectStoreName).objectStore(objectStoreName).get(key),
    );
    if (!cached?.blob) return null;
    cached.lastAccess = Date.now();
    const transaction = database.transaction(objectStoreName, 'readwrite');
    transaction.objectStore(objectStoreName).put(cached);
    return cached.blob;
  } catch {
    return null;
  } finally {
    database.close();
  }
}

async function writePersistentThumbnail(value: CachedThumbnail): Promise<void> {
  const database = await openThumbnailDatabase();
  if (!database) return;
  try {
    const transaction = database.transaction(objectStoreName, 'readwrite');
    transaction.objectStore(objectStoreName).put(value);
    await transactionDone(transaction);
    await prunePersistentCache(database);
  } catch {
    // 浏览器禁用或耗尽 IndexedDB 配额时只退化为当前会话内存缓存。
  } finally {
    database.close();
  }
}

async function prunePersistentCache(database: IDBDatabase): Promise<void> {
  const transaction = database.transaction(objectStoreName, 'readwrite');
  const store = transaction.objectStore(objectStoreName);
  const entries = await requestValue<CachedThumbnail[]>(store.getAll());
  let bytes = entries.reduce((sum, entry) => sum + entry.byteLength, 0);
  let count = entries.length;
  entries.sort((left, right) => left.lastAccess - right.lastAccess);
  for (const entry of entries) {
    if (count <= maxPersistentEntries && bytes <= maxPersistentBytes) break;
    store.delete(entry.key);
    count -= 1;
    bytes -= entry.byteLength;
  }
  await transactionDone(transaction);
}

function openThumbnailDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return Promise.resolve(null);
  return new Promise((resolve) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(objectStoreName)) {
        request.result.createObjectStore(objectStoreName, { keyPath: 'key' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener('abort', abort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener('abort', abort);
        reject(error);
      },
    );
  });
}

function throwIfAborted(signal: AbortSignal) {
  if (signal.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError');
}

class Semaphore {
  private active = 0;
  private readonly waiters: Array<() => void> = [];

  constructor(private readonly limit: number) {}

  async run<T>(signal: AbortSignal, operation: () => Promise<T>): Promise<T> {
    await this.acquire(signal);
    try {
      return await operation();
    } finally {
      this.release();
    }
  }

  private async acquire(signal: AbortSignal): Promise<void> {
    throwIfAborted(signal);
    if (this.active < this.limit) {
      this.active += 1;
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const ready = () => {
        signal.removeEventListener('abort', abort);
        this.active += 1;
        resolve();
      };
      const abort = () => {
        const index = this.waiters.indexOf(ready);
        if (index >= 0) this.waiters.splice(index, 1);
        reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      };
      this.waiters.push(ready);
      signal.addEventListener('abort', abort, { once: true });
    });
  }

  private release() {
    this.active -= 1;
    this.waiters.shift()?.();
  }
}

const downloadSlots = new Semaphore(4);
