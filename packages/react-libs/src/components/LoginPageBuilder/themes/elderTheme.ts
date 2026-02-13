import type { LoginColorConfig } from '../types';
import type { ThemeMode } from '../../../theme';
import { resolveTheme } from '../../../theme';

/**
 * Dark theme - Elder-style with gold/amber accents on dark slate.
 */
export const DARK_THEME: LoginColorConfig = {
  // Page colors - dark-950 background
  pageBackground: 'bg-slate-950',
  cardBackground: 'bg-slate-800',
  cardBorder: 'border-slate-700',

  // Text colors - gold/amber for primary, slate for secondary
  titleText: 'text-amber-400',
  subtitleText: 'text-slate-400',
  labelText: 'text-amber-300',
  inputText: 'text-slate-100',
  placeholderText: 'placeholder-slate-500',
  errorText: 'text-red-400',
  linkText: 'text-amber-400',
  linkHoverText: 'hover:text-amber-300',

  // Input colors - dark inputs with gold focus
  inputBackground: 'bg-slate-900',
  inputBorder: 'border-slate-600',
  inputFocusBorder: 'focus:border-amber-500',
  inputFocusRing: 'focus:ring-amber-500',

  // Button colors - gold primary, slate secondary
  primaryButton: 'bg-amber-500',
  primaryButtonHover: 'hover:bg-amber-600',
  primaryButtonText: 'text-slate-900',
  secondaryButton: 'bg-slate-700',
  secondaryButtonHover: 'hover:bg-slate-600',
  secondaryButtonText: 'text-slate-100',
  secondaryButtonBorder: 'border-slate-600',

  // Social button colors
  socialButtonBackground: 'bg-slate-700',
  socialButtonBorder: 'border-slate-600',
  socialButtonText: 'text-slate-100',
  socialButtonHover: 'hover:bg-slate-600',

  // Divider
  dividerColor: 'border-slate-600',
  dividerText: 'text-slate-500',

  // Footer
  footerText: 'text-slate-500',
  footerLinkText: 'text-amber-400',

  // GDPR banner
  bannerBackground: 'bg-slate-800',
  bannerText: 'text-slate-300',
  bannerBorder: 'border-slate-700',
};

/**
 * Light theme - white/gray background with blue accents.
 */
export const LIGHT_THEME: LoginColorConfig = {
  // Page colors
  pageBackground: 'bg-gray-50',
  cardBackground: 'bg-white',
  cardBorder: 'border-gray-200',

  // Text colors
  titleText: 'text-gray-900',
  subtitleText: 'text-gray-500',
  labelText: 'text-gray-700',
  inputText: 'text-gray-900',
  placeholderText: 'placeholder-gray-400',
  errorText: 'text-red-600',
  linkText: 'text-blue-600',
  linkHoverText: 'hover:text-blue-500',

  // Input colors
  inputBackground: 'bg-white',
  inputBorder: 'border-gray-300',
  inputFocusBorder: 'focus:border-blue-500',
  inputFocusRing: 'focus:ring-blue-500',

  // Button colors
  primaryButton: 'bg-blue-600',
  primaryButtonHover: 'hover:bg-blue-700',
  primaryButtonText: 'text-white',
  secondaryButton: 'bg-white',
  secondaryButtonHover: 'hover:bg-gray-50',
  secondaryButtonText: 'text-gray-700',
  secondaryButtonBorder: 'border-gray-300',

  // Social button colors
  socialButtonBackground: 'bg-white',
  socialButtonBorder: 'border-gray-300',
  socialButtonText: 'text-gray-700',
  socialButtonHover: 'hover:bg-gray-50',

  // Divider
  dividerColor: 'border-gray-300',
  dividerText: 'text-gray-400',

  // Footer
  footerText: 'text-gray-400',
  footerLinkText: 'text-blue-600',

  // GDPR banner
  bannerBackground: 'bg-white',
  bannerText: 'text-gray-700',
  bannerBorder: 'border-gray-200',
};

/** @deprecated Use themeMode='dark' instead */
export const ELDER_LOGIN_THEME = DARK_THEME;

const THEME_PRESETS: Record<ThemeMode, LoginColorConfig> = {
  dark: DARK_THEME,
  light: LIGHT_THEME,
};

/**
 * Resolve login theme from mode + optional overrides.
 */
export function resolveLoginTheme(
  mode: ThemeMode = 'dark',
  overrides?: Partial<LoginColorConfig>,
): LoginColorConfig {
  return resolveTheme(THEME_PRESETS, mode, overrides);
}

/**
 * @deprecated Use resolveLoginTheme instead
 */
export function mergeWithElderTheme(
  partial?: Partial<LoginColorConfig>
): LoginColorConfig {
  return resolveLoginTheme('dark', partial);
}
