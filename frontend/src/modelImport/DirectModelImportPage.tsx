import React from 'react';
import { Palette, Upload } from 'lucide-react';
import appConfig from '../app/appConfig.json';
import type { ModelAsset } from '../assets/modelAssetApi';
import { uploadMeshModel } from './meshModelApi';

type MeshColor = {
  hex: string;
  materialName: string;
  faceCount: number;
  coverageRatio: number;
};

type MeshColorSummary = {
  colors: MeshColor[];
};

export function DirectModelImportPage() {
  const [modelName, setModelName] = React.useState('');
  const [selectedFile, setSelectedFile] = React.useState<File | null>(null);
  const [uploadedAsset, setUploadedAsset] = React.useState<ModelAsset | null>(null);
  const [isUploading, setIsUploading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submitImport = async () => {
    if (!selectedFile || !modelName.trim()) {
      return;
    }
    setIsUploading(true);
    setError(null);
    try {
      setUploadedAsset(
        await uploadMeshModel(appConfig.meshModelsApiUrl, modelName.trim(), selectedFile),
      );
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : appConfig.texts.loadFailed);
    } finally {
      setIsUploading(false);
    }
  };

  const colorSummary = uploadedAsset ? meshColorSummary(uploadedAsset) : null;

  return (
    <section className="mesh-import-page">
      <header className="asset-header">
        <div>
          <h1>{appConfig.texts.directImportTitle}</h1>
          <p>{appConfig.texts.directImportPending}</p>
        </div>
        <Upload aria-hidden="true" />
      </header>

      <div className="mesh-import-layout">
        <form
          className="mesh-import-panel"
          onSubmit={(event) => {
            event.preventDefault();
            void submitImport();
          }}
        >
          <label className="terrain-scale-control">
            <span>{appConfig.texts.meshModelName}</span>
            <input
              onChange={(event) => setModelName(event.target.value)}
              placeholder={appConfig.texts.meshModelNamePlaceholder}
              type="text"
              value={modelName}
            />
          </label>
          <label className="terrain-file-button" htmlFor={appConfig.meshFileInputId}>
            <Upload aria-hidden="true" />
            {selectedFile ? selectedFile.name : appConfig.texts.meshFile}
          </label>
          <input
            accept={appConfig.meshFileAccept}
            className="terrain-file-input"
            id={appConfig.meshFileInputId}
            onChange={(event) => {
              const [file] = Array.from(event.target.files ?? []);
              setSelectedFile(file ?? null);
            }}
            type="file"
          />
          <button
            className="terrain-page-switch"
            disabled={!selectedFile || !modelName.trim() || isUploading}
            type="submit"
          >
            {isUploading ? appConfig.texts.loading : appConfig.texts.meshUpload}
          </button>
          {error ? <div className="asset-error">{error}</div> : null}
        </form>

        <aside className="mesh-import-panel">
          <div className="mesh-import-title">
            <Palette aria-hidden="true" />
            <span>{appConfig.texts.meshColorSummary}</span>
          </div>
          {uploadedAsset ? (
            <div className="terrain-empty">
              {appConfig.texts.meshUploadComplete}: {uploadedAsset.name}
            </div>
          ) : null}
          {colorSummary && colorSummary.colors.length > 0 ? (
            <div className="mesh-color-list">
              {colorSummary.colors.map((color) => (
                <div className="mesh-color-row" key={`${color.materialName}-${color.hex}`}>
                  <span style={{ backgroundColor: color.hex }} />
                  <div>
                    <strong>{color.materialName}</strong>
                    <em>
                      {color.hex} / {appConfig.texts.meshFaceCount} {color.faceCount} /{' '}
                      {Math.round(color.coverageRatio * 100)}%
                    </em>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="asset-empty">{appConfig.texts.meshNoColors}</div>
          )}
        </aside>
      </div>
    </section>
  );
}

function meshColorSummary(modelAsset: ModelAsset): MeshColorSummary | null {
  const summary = modelAsset.metadata?.colorSummary;
  if (!summary || typeof summary !== 'object' || !('colors' in summary)) {
    return null;
  }
  return summary as MeshColorSummary;
}
