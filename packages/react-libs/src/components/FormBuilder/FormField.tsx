/**
 * FormField Component
 *
 * Dynamic form field renderer that supports multiple input types.
 * Handles validation errors, helper text, and field-specific configuration.
 */

import React from 'react';
import { FormFieldProps } from './types';
import { resolveTheme } from '../../theme';
import { THEME_PRESETS } from './themes';

export const FormField: React.FC<FormFieldProps> = ({
  field,
  value,
  error,
  onChange,
  onBlur,
  themeMode = 'dark',
  colors,
}) => {
  const theme = resolveTheme(THEME_PRESETS, themeMode, colors);
  const isDark = themeMode === 'dark';

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const newValue = field.type === 'checkbox'
      ? (e.target as HTMLInputElement).checked
      : field.type === 'number'
      ? e.target.value === '' ? '' : Number(e.target.value)
      : e.target.value;

    onChange(field.name, newValue);

    if (field.onChange) {
      field.onChange(newValue);
    }
  };

  const handleBlur = () => {
    if (onBlur) {
      onBlur(field.name);
    }
  };

  const inputClasses = `mt-1 block w-full rounded-md shadow-sm sm:text-sm border ${theme.fieldBackground} ${theme.fieldBorder} ${theme.fieldText} ${theme.fieldPlaceholder} ${theme.focusBorder} ${theme.focusRing} focus:outline-none focus:ring-1 disabled:opacity-50 disabled:cursor-not-allowed`;

  const renderInput = () => {
    const commonProps = {
      id: field.name,
      name: field.name,
      value: field.type === 'checkbox' ? undefined : (value ?? ''),
      checked: field.type === 'checkbox' ? Boolean(value) : undefined,
      onChange: handleChange,
      onBlur: handleBlur,
      required: field.required,
      disabled: field.disabled,
      autoFocus: field.autoFocus,
      placeholder: field.placeholder,
      min: field.min,
      max: field.max,
      minLength: field.minLength,
      maxLength: field.maxLength,
      pattern: field.pattern,
      step: field.step,
    };

    switch (field.type) {
      case 'textarea':
        return (
          <textarea
            {...commonProps}
            rows={field.rows || 3}
            className={inputClasses}
          />
        );

      case 'select':
        return (
          <select
            {...commonProps}
            className={inputClasses}
            style={isDark ? { colorScheme: 'dark' } : undefined}
          >
            <option value="">Select...</option>
            {field.options?.map((option) => (
              <option
                key={option.value}
                value={option.value}
                disabled={option.disabled}
              >
                {option.label}
              </option>
            ))}
          </select>
        );

      case 'radio':
        return (
          <div className="space-y-2">
            {field.options?.map((option) => (
              <label
                key={option.value}
                className="flex items-center space-x-2 cursor-pointer"
              >
                <input
                  type="radio"
                  name={field.name}
                  value={option.value}
                  checked={value === option.value}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  disabled={option.disabled || field.disabled}
                  required={field.required}
                  className={`h-4 w-4 ${theme.accentColor} ${theme.focusRing} ${theme.fieldBorder} ${theme.fieldBackground}`}
                />
                <span className={theme.optionText}>{option.label}</span>
              </label>
            ))}
          </div>
        );

      case 'checkbox':
        return (
          <label className="flex items-center space-x-2 cursor-pointer">
            <input
              type="checkbox"
              {...commonProps}
              className={`h-4 w-4 ${theme.accentColor} ${theme.focusRing} ${theme.fieldBorder} rounded ${theme.fieldBackground}`}
            />
            <span className={theme.optionText}>{field.label}</span>
          </label>
        );

      default:
        return (
          <input
            type={field.type}
            {...commonProps}
            className={inputClasses}
            {...(['date', 'time', 'datetime-local'].includes(field.type) && isDark ? { style: { colorScheme: 'dark' } } : {})}
          />
        );
    }
  };

  if (field.type === 'checkbox') {
    return (
      <div className={field.className}>
        {renderInput()}
        {field.helperText && (
          <p className={`mt-1 text-sm ${theme.helperText}`}>{field.helperText}</p>
        )}
        {error && (
          <p className={`mt-1 text-sm ${theme.errorText}`}>{error}</p>
        )}
      </div>
    );
  }

  return (
    <div className={field.className}>
      <label htmlFor={field.name} className={`block text-sm font-medium ${theme.labelText} mb-1`}>
        {field.label}
        {field.required && <span className={`${theme.errorText} ml-1`}>*</span>}
      </label>
      {renderInput()}
      {field.helperText && !error && (
        <p className={`mt-1 text-sm ${theme.helperText}`}>{field.helperText}</p>
      )}
      {error && (
        <p className={`mt-1 text-sm ${theme.errorText}`}>{error}</p>
      )}
    </div>
  );
};
