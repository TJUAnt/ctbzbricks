import React from 'react';
import { Boxes } from 'lucide-react';
import { Link } from 'react-router-dom';
import { loadGlbThumbnailBlob, type GlbThumbnailModel } from '../preview/glbThumbnailRenderer';

export type PartSummary = {
  key: string;
  partRef: string;
  name: string;
  quantity: number;
  partLibraryVersionId: string | null;
  geometryStatus: 'ready' | 'failed' | 'missing';
  previewModel: GlbThumbnailModel | null;
};


/** 展示版本差异的一项计数，不持有请求或业务状态。 */
export function DiffMetric({ label, value }: { label: string; value: number }) {
  return <article><strong>{value}</strong><span>{label}</span></article>;
}

/** 展示详情摘要的一项指标。 */
export function DetailMetric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return <article><span>{icon}</span><div><strong>{value}</strong><small>{label}</small></div></article>;
}

/** 展示 BOM 中的零件摘要；存在零件库版本时链接到对应零件详情。 */
export function PartSummaryCard({
  part,
  missingGeometryLabel,
}: {
  part: PartSummary;
  missingGeometryLabel: string;
}) {
  const geometryAvailable = part.geometryStatus === 'ready';
  const content = (
    <>
      <PartCardImage model={part.previewModel} />
      <span className="component-detail-part-card-copy">
        <strong>{part.name}</strong>
        <small>{part.partRef}</small>
        {!geometryAvailable ? (
          <span className="component-detail-part-card-availability">{missingGeometryLabel}</span>
        ) : null}
        <em>×{part.quantity}</em>
      </span>
    </>
  );
  if (!part.partLibraryVersionId) {
    return (
      <article className={`component-detail-part-card${geometryAvailable ? '' : ' is-unavailable'}`}>
        {content}
      </article>
    );
  }
  return (
    <Link
      className={`component-detail-part-card${geometryAvailable ? '' : ' is-unavailable'}`}
      to={`/parts/${encodeURIComponent(part.partLibraryVersionId)}/${encodeURIComponent(part.partRef)}`}
    >
      {content}
    </Link>
  );
}

/** PartCardImage 仅在卡片接近视口时读取不可变 GLB，并复用全局缩略图渲染与缓存。 */
function PartCardImage({ model }: { model: GlbThumbnailModel | null }) {
  const mountRef = React.useRef<HTMLSpanElement | null>(null);
  const [visible, setVisible] = React.useState(false);
  const [generatedURL, setGeneratedURL] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !model) return undefined;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '400px' });
    observer.observe(mount);
    return () => observer.disconnect();
  }, [model?.artifactId]);

  React.useEffect(() => {
    setFailed(false);
    setGeneratedURL(null);
    if (!model || !visible) return undefined;
    const controller = new AbortController();
    let objectURL: string | null = null;
    void loadGlbThumbnailBlob(model, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectURL = URL.createObjectURL(blob);
        setGeneratedURL(objectURL);
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectURL) URL.revokeObjectURL(objectURL);
    };
  }, [model?.artifactId, model?.sha256, model?.url, visible]);

  return (
    <span className="component-detail-part-card-image" ref={mountRef}>
      {generatedURL && !failed ? (
        <img alt="" decoding="async" loading="lazy" onError={() => setFailed(true)} src={generatedURL} />
      ) : <Boxes aria-hidden="true" />}
    </span>
  );
}
