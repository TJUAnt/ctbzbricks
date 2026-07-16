import React from 'react';
import { ChevronLeft, ChevronRight, Image as ImageIcon, RefreshCw } from 'lucide-react';
import { loadPixelArtProjects, type PixelArtProjectList } from './pixelArtApi';
import pixelArtConfig from './pixelArtConfig.json';

export function PixelArtProjectsPage() {
  const [page, setPage] = React.useState(pixelArtConfig.workflow.initialStep);
  const [projectList, setProjectList] = React.useState<PixelArtProjectList | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);

  const loadProjects = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setProjectList(await loadPixelArtProjects(page, pixelArtConfig.pageSize));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : pixelArtConfig.texts.loadProjectsFailed);
    } finally {
      setIsLoading(false);
    }
  }, [page]);

  React.useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const totalPages = projectList ? Math.max(pixelArtConfig.workflow.initialStep, Math.ceil(projectList.total / projectList.pageSize)) : pixelArtConfig.workflow.initialStep;

  return (
    <main className="pixel-art-projects-page">
      <header className="asset-header">
        <div>
          <h1>{pixelArtConfig.texts.savedProjects}</h1>
          <p>{pixelArtConfig.texts.savedProjectsSubtitle}</p>
        </div>
        <button className="pixel-art-save pixel-art-secondary" onClick={() => void loadProjects()} type="button">
          <RefreshCw aria-hidden="true" />
          {pixelArtConfig.texts.refresh}
        </button>
      </header>

      {error ? <div className="asset-error">{error}</div> : null}
      {isLoading ? <div className="asset-loading">{pixelArtConfig.texts.generating}</div> : null}
      {projectList && projectList.items.length === pixelArtConfig.emptyFileCount ? (
        <div className="asset-empty">{pixelArtConfig.texts.emptyProjects}</div>
      ) : null}

      <section className="pixel-art-project-grid">
        {projectList?.items.map((project) => (
          <article className="pixel-art-project-card" key={project.modelId}>
            <img alt={project.name} src={project.previewImage} />
            <div>
              <ImageIcon aria-hidden="true" />
              <strong>{project.name}</strong>
            </div>
            <span>{project.source}</span>
            <span>{project.gridWidth} x {project.gridHeight}</span>
            <span>{project.colorCount} colors</span>
            <span>{new Date(project.createdAt).toLocaleString()}</span>
          </article>
        ))}
      </section>

      <div className="asset-pagination">
        <button
          disabled={page <= pixelArtConfig.workflow.initialStep}
          onClick={() => setPage((currentPage) => currentPage - pixelArtConfig.workflow.initialStep)}
          type="button"
        >
          <ChevronLeft aria-hidden="true" />
          {page - pixelArtConfig.workflow.initialStep}
        </button>
        <span>{page} / {totalPages}</span>
        <button
          disabled={page >= totalPages}
          onClick={() => setPage((currentPage) => currentPage + pixelArtConfig.workflow.initialStep)}
          type="button"
        >
          {page + pixelArtConfig.workflow.initialStep}
          <ChevronRight aria-hidden="true" />
        </button>
      </div>
    </main>
  );
}
