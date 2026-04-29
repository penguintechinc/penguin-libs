/**
 * React Form Builder Package
 *
 * Focused package containing FormBuilder, FormModalBuilder, and related utilities.
 */

export { FormModalBuilder } from './FormModalBuilder';
export type { FormField, FormTab, FormModalBuilderProps, ColorConfig } from './FormModalBuilder';

export { FormBuilder } from './FormBuilder';
export type { FieldConfig, FormBuilderProps, FormConfig, FieldType, SelectOption, FormBuilderColorConfig } from './types';

export { Modal } from './Modal';
export { FormField as FormFieldComponent } from './FormField';

export type { ThemeMode } from './theme';
export { resolveTheme } from './theme';
