import { NavLink } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { useAppTranslation } from '../i18n';

/** 连接图片编辑、已保存项目和拼接设计；项目仍沿用原有持久化流程。 */
export function PixelModelNavigation() {
  const tr = useAppTranslation();
  return <nav className="component-library-tabs" aria-label={tr('app:navigation.model2d')}>
    <NavLink className="component-library-tab" to={appConfig.routePaths.pixelArt}>{tr('app:navigation.pixelEdit')}</NavLink>
    <NavLink className="component-library-tab" to={appConfig.routePaths.pixelArtProjects}>{tr('app:navigation.pixelSaved')}</NavLink>
    <NavLink className="component-library-tab" to={appConfig.routePaths.legoDesign}>{tr('app:navigation.pixelDesign')}</NavLink>
  </nav>;
}
