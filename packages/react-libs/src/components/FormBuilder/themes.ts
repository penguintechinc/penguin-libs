import type { FormBuilderColorConfig } from './types';
import type { ThemeMode } from '../../theme';

/** Dark theme - slate background with gold accents */
const DARK_THEME: FormBuilderColorConfig = {
  formBackground: 'bg-slate-900',
  modalBackground: 'bg-slate-800',
  overlayBackground: 'bg-black/50',

  titleText: 'text-amber-400',
  labelText: 'text-amber-300',
  helperText: 'text-slate-400',
  errorText: 'text-red-400',

  fieldBackground: 'bg-slate-900',
  fieldBorder: 'border-slate-600',
  fieldText: 'text-amber-300',
  fieldPlaceholder: 'placeholder-slate-500',
  focusRing: 'focus:ring-amber-500',
  focusBorder: 'focus:border-amber-500',

  primaryButton: 'bg-amber-500',
  primaryButtonHover: 'hover:bg-amber-600',
  primaryButtonText: 'text-slate-900',
  secondaryButton: 'bg-slate-700',
  secondaryButtonHover: 'hover:bg-slate-600',
  secondaryButtonText: 'text-slate-300',
  secondaryButtonBorder: 'border-slate-600',

  accentColor: 'text-amber-400',

  closeButtonText: 'text-slate-400',
  closeButtonHover: 'hover:text-white',

  errorBannerBackground: 'bg-red-900/20',
  errorBannerBorder: 'border-red-500',

  optionText: 'text-slate-300',
};

/** Light theme - white background with blue accents */
const LIGHT_THEME: FormBuilderColorConfig = {
  formBackground: 'bg-white',
  modalBackground: 'bg-white',
  overlayBackground: 'bg-black/50',

  titleText: 'text-gray-900',
  labelText: 'text-gray-700',
  helperText: 'text-gray-500',
  errorText: 'text-red-600',

  fieldBackground: 'bg-white',
  fieldBorder: 'border-gray-300',
  fieldText: 'text-gray-900',
  fieldPlaceholder: 'placeholder-gray-400',
  focusRing: 'focus:ring-blue-500',
  focusBorder: 'focus:border-blue-500',

  primaryButton: 'bg-blue-600',
  primaryButtonHover: 'hover:bg-blue-700',
  primaryButtonText: 'text-white',
  secondaryButton: 'bg-white',
  secondaryButtonHover: 'hover:bg-gray-50',
  secondaryButtonText: 'text-gray-700',
  secondaryButtonBorder: 'border-gray-300',

  accentColor: 'text-blue-600',

  closeButtonText: 'text-gray-400',
  closeButtonHover: 'hover:text-gray-900',

  errorBannerBackground: 'bg-red-50',
  errorBannerBorder: 'border-red-300',

  optionText: 'text-gray-700',
};

export const THEME_PRESETS: Record<ThemeMode, FormBuilderColorConfig> = {
  dark: DARK_THEME,
  light: LIGHT_THEME,
};
