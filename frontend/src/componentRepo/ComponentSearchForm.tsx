import React from 'react';
import { Search } from 'lucide-react';

import { useAppTranslation } from '../i18n';
import type { ComponentSearchFilters } from './componentRepoApi';

export type ComponentSearchValues = {
  name: string;
  componentId: string;
  widthStud: string;
  depthStud: string;
  heightPlate: string;
};

export const emptyComponentSearchValues: ComponentSearchValues = {
  name: '',
  componentId: '',
  widthStud: '',
  depthStud: '',
  heightPlate: '',
};

/** componentSearchFilters 只转换提交时的结构化机器值；空字段不进入请求。 */
export function componentSearchFilters(values: ComponentSearchValues): ComponentSearchFilters {
  const optionalNumber = (value: string): number | undefined => (
    value.trim() === '' ? undefined : Number(value)
  );
  return {
    name: values.name.trim() || undefined,
    componentId: values.componentId.trim() || undefined,
    widthStud: optionalNumber(values.widthStud),
    depthStud: optionalNumber(values.depthStud),
    heightPlate: optionalNumber(values.heightPlate),
  };
}

export function hasComponentSearchFilters(filters: ComponentSearchFilters): boolean {
  return Boolean(
    filters.name || filters.componentId
    || filters.widthStud !== undefined || filters.depthStud !== undefined || filters.heightPlate !== undefined,
  );
}

/** ComponentSearchForm 为个人仓库、收藏和公共 Feed 提供同一套 Part Search 风格筛选入口。 */
export function ComponentSearchForm({
  loading,
  onChange,
  onSubmit,
  values,
}: {
  loading: boolean;
  onChange: (values: ComponentSearchValues) => void;
  onSubmit: () => void;
  values: ComponentSearchValues;
}) {
  const tr = useAppTranslation();
  const setField = (field: keyof ComponentSearchValues, value: string) => onChange({ ...values, [field]: value });
  return (
    <form
      className="component-search-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="component-search-fields">
        <label className="component-search-field component-search-name">
          <span>{tr('componentRepo:componentNameFilter')}</span>
          <input
            maxLength={200}
            onChange={(event) => setField('name', event.target.value)}
            placeholder={tr('componentRepo:componentNameFilterPlaceholder')}
            type="search"
            value={values.name}
          />
        </label>
        <label className="component-search-field">
          <span>{tr('componentRepo:componentIdFilter')}</span>
          <input
            maxLength={128}
            onChange={(event) => setField('componentId', event.target.value)}
            placeholder={tr('componentRepo:componentIdFilterPlaceholder')}
            type="search"
            value={values.componentId}
          />
        </label>
        <DimensionField label={tr('partSearch:widthStud')} onChange={(value) => setField('widthStud', value)} value={values.widthStud} />
        <DimensionField label={tr('partSearch:depthStud')} onChange={(value) => setField('depthStud', value)} value={values.depthStud} />
        <DimensionField label={tr('partSearch:heightPlate')} onChange={(value) => setField('heightPlate', value)} value={values.heightPlate} />
        <button disabled={loading} type="submit">
          <Search aria-hidden="true" />{tr('componentRepo:applyFilters')}
        </button>
      </div>
      <p>{tr('componentRepo:componentSizeSearchHint')}</p>
    </form>
  );
}

function DimensionField({ label, onChange, value }: { label: string; onChange: (value: string) => void; value: string }) {
  return (
    <label className="component-search-field">
      <span>{label}</span>
      <input min="0.1" onChange={(event) => onChange(event.target.value)} step="0.1" type="number" value={value} />
    </label>
  );
}
