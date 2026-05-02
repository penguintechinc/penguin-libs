/**
 * React Login Package
 *
 * Focused package containing LoginPageBuilder and related utilities.
 */

export { LoginPageBuilder } from './LoginPageBuilder';

export type {
  LoginPageBuilderProps,
  LoginApiConfig,
  LoginPayload,
  LoginResponse,
  BrandingConfig,
  CaptchaConfig,
  MFAConfig,
  PasskeyConfig,
  GDPRConfig,
  SocialLoginConfig,
  BuiltInOAuth2Provider,
  CustomOAuth2Provider,
  OIDCProvider,
  SAMLProvider,
  LoginColorConfig,
  CookieConsentState,
  UseCaptchaReturn,
  MFAModalProps,
  MFAInputProps,
  CaptchaWidgetProps,
  SocialLoginButtonsProps,
  CookieConsentProps,
  FooterProps,
} from './types';

export { ELDER_LOGIN_THEME, mergeWithElderTheme } from './themes/elderTheme';
export type { ThemeMode } from './types';

export { useCaptcha } from './hooks/useCaptcha';
export { useCookieConsent } from './hooks/useCookieConsent';

export {
  buildOAuth2Url,
  buildCustomOAuth2Url,
  buildOIDCUrl,
  generateState,
  validateState,
  getProviderLabel,
  getProviderColors,
} from './utils/oauth';

export {
  buildSAMLRequest,
  buildSAMLRedirectUrl,
  buildSAMLPostForm,
  initiateSAMLLogin,
  initiateSAMLPostLogin,
  validateRelayState,
  getStoredRequestId,
  clearSAMLSession,
} from './utils/saml';

export { MFAModal } from './components/MFAModal';
export { MFAInput } from './components/MFAInput';
export { CaptchaWidget } from './components/CaptchaWidget';
export { SocialLoginButtons, LoginDivider } from './components/SocialLoginButtons';
export { CookieConsent } from './components/CookieConsent';
export { Footer } from './components/Footer';
export { PasskeyButton } from './components/PasskeyButton';

export {
  GoogleIcon,
  GitHubIcon,
  MicrosoftIcon,
  AppleIcon,
  TwitchIcon,
  DiscordIcon,
  SSOIcon,
  EnterpriseIcon,
} from './components/icons';

export type { ThemeMode as LoginThemeMode } from './theme';
export { resolveTheme as resolveLoginTheme } from './theme';
