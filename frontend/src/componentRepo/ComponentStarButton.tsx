import React from 'react';

import { useAppTranslation } from '../i18n';

type ComponentStarButtonProps = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  'aria-label' | 'aria-pressed' | 'title' | 'type'
> & {
  starred: boolean;
};

/** ComponentStarButton 统一 Star/Unstar 的双语可访问名称，并保留原生按钮的 Enter/Space 键盘语义。 */
export function ComponentStarButton({ starred, children, ...buttonProps }: ComponentStarButtonProps) {
  const tr = useAppTranslation();
  const label = tr(starred ? 'componentRepo:unstarComponent' : 'componentRepo:starComponent');

  return (
    <button
      {...buttonProps}
      aria-label={label}
      aria-pressed={starred}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}
