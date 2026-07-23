import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const encoderModule = await import(pathToFileURL(process.argv[2]).href);
const { MeshoptEncoder } = encoderModule;
await MeshoptEncoder.ready;

const input = fs.readFileSync(0);
if (input.toString('ascii', 0, 4) !== 'glTF') throw new Error('Invalid GLB input');
const jsonLength = input.readUInt32LE(12);
const jsonStart = 20;
const document = JSON.parse(input.toString('utf8', jsonStart, jsonStart + jsonLength).trim());
const binaryHeader = jsonStart + jsonLength;
const binaryLength = input.readUInt32LE(binaryHeader);
const binaryStart = binaryHeader + 8;
const sourceBinary = input.subarray(binaryStart, binaryStart + binaryLength);

const accessorByView = new Map();
for (const accessor of document.accessors) accessorByView.set(accessor.bufferView, accessor);
const chunks = [];
let outputLength = 0;
for (let index = 0; index < document.bufferViews.length; index += 1) {
  const view = document.bufferViews[index];
  const accessor = accessorByView.get(index);
  if (!accessor) throw new Error(`Missing accessor for buffer view ${index}`);
  const componentSize = accessor.componentType === 5125 || accessor.componentType === 5126 ? 4 : 2;
  const stride = view.byteStride ?? componentSize;
  const mode = view.target === 34963 ? 'TRIANGLES' : 'ATTRIBUTES';
  const source = sourceBinary.subarray(view.byteOffset ?? 0, (view.byteOffset ?? 0) + view.byteLength);
  const compressed = MeshoptEncoder.encodeGltfBuffer(source, accessor.count, stride, mode);
  const padding = (4 - (outputLength % 4)) % 4;
  if (padding) {
    chunks.push(Buffer.alloc(padding));
    outputLength += padding;
  }
  const compressedOffset = outputLength;
  chunks.push(Buffer.from(compressed));
  outputLength += compressed.length;
  const uncompressedLength = view.byteLength;
  document.bufferViews[index] = {
    buffer: 0,
    byteOffset: 0,
    byteLength: uncompressedLength,
    ...(view.byteStride ? { byteStride: view.byteStride } : {}),
    ...(view.target ? { target: view.target } : {}),
    extensions: {
      EXT_meshopt_compression: {
        buffer: 0,
        byteOffset: compressedOffset,
        byteLength: compressed.length,
        byteStride: stride,
        count: accessor.count,
        mode,
        filter: 'NONE',
      },
    },
  };
}

const outputBinary = Buffer.concat(chunks);
document.buffers[0].byteLength = outputBinary.length;
document.extensionsUsed = ['EXT_meshopt_compression'];
document.extensionsRequired = ['EXT_meshopt_compression'];
let outputJson = Buffer.from(JSON.stringify(document));
outputJson = Buffer.concat([outputJson, Buffer.alloc((4 - (outputJson.length % 4)) % 4, 0x20)]);
const paddedBinary = Buffer.concat([
  outputBinary,
  Buffer.alloc((4 - (outputBinary.length % 4)) % 4),
]);
const totalLength = 12 + 8 + outputJson.length + 8 + paddedBinary.length;
const header = Buffer.alloc(12);
header.write('glTF', 0, 'ascii');
header.writeUInt32LE(2, 4);
header.writeUInt32LE(totalLength, 8);
const jsonHeader = Buffer.alloc(8);
jsonHeader.writeUInt32LE(outputJson.length, 0);
jsonHeader.writeUInt32LE(0x4e4f534a, 4);
const binaryChunkHeader = Buffer.alloc(8);
binaryChunkHeader.writeUInt32LE(paddedBinary.length, 0);
binaryChunkHeader.writeUInt32LE(0x004e4942, 4);
process.stdout.write(Buffer.concat([header, jsonHeader, outputJson, binaryChunkHeader, paddedBinary]));
