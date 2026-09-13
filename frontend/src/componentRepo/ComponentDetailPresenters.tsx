import React from 'react';
import { Boxes } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { ComponentConnectorResponse } from './componentRepoApi';

export type PartSummary = {
  key: string;
  partRef: string;
  name: string;
  quantity: number;
  partLibraryVersionId: string | null;
  geometryStatus: 'ready' | 'failed' | 'missing';
};

export type ConnectorPartGroup = {
  partInstanceId: string;
  partRef: string;
  connectors: ComponentConnectorResponse[];
};

const connectorStateOrder: ComponentConnectorResponse['state'][] = [
  'external',
  'internal',
  'blocked',
  'unsupported',
  'unresolved',
];
const connectorStateRank = new Map(
  connectorStateOrder.map((state, index) => [state, index]),
);

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
      <PartCardImage src={null} />
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

/** 按零件实例汇总并稳定排序连接点，供详情页列表和三维选中状态共用。 */
export function groupConnectorsByPart(
  connectors: ComponentConnectorResponse[],
): ConnectorPartGroup[] {
  const groups = new Map<string, ConnectorPartGroup>();
  for (const connector of connectors) {
    const group = groups.get(connector.partInstanceId) ?? {
      partInstanceId: connector.partInstanceId,
      partRef: connector.partRef,
      connectors: [],
    };
    group.connectors.push(connector);
    groups.set(connector.partInstanceId, group);
  }
  return [...groups.values()]
    .filter((group) => group.connectors.length > 0)
    .map((group) => ({
      ...group,
      connectors: [...group.connectors].sort(
        (left, right) => (
          (connectorStateRank.get(left.state) ?? Number.MAX_SAFE_INTEGER)
          - (connectorStateRank.get(right.state) ?? Number.MAX_SAFE_INTEGER)
        ) || left.connectorId.localeCompare(right.connectorId),
      ),
    }));
}

function PartCardImage({ src }: { src: string | null }) {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [src]);
  return (
    <span className="component-detail-part-card-image">
      {src && !failed ? (
        <img alt="" decoding="async" loading="lazy" onError={() => setFailed(true)} src={src} />
      ) : <Boxes aria-hidden="true" />}
    </span>
  );
}
