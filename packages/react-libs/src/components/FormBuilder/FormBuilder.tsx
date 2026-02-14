/**
 * FormBuilder Component
 *
 * Flexible form builder that supports both modal and inline rendering modes.
 * - mode='modal': Renders form inside a modal dialog
 * - mode='inline': Renders form directly in the page
 *
 * Features:
 * - Dynamic field configuration
 * - Built-in validation
 * - Error handling
 * - Loading states
 * - Tab support for organizing fields
 * - Customizable styling via themeMode + colors
 */

import React, { useMemo, useState } from 'react';
import { FormBuilderProps, FormTab } from './types';
import { Modal } from './Modal';
import { FormField } from './FormField';
import { useFormBuilder } from '../../hooks/useFormBuilder';
import { resolveTheme } from '../../theme';
import { THEME_PRESETS } from './themes';

export const FormBuilder: React.FC<FormBuilderProps> = ({
  mode = 'inline',
  isOpen = true,
  fields,
  title,
  submitLabel = 'Submit',
  cancelLabel = 'Cancel',
  onSubmit,
  onCancel,
  initialData,
  validateOnChange = false,
  validateOnBlur = true,
  loading = false,
  error = null,
  closeOnOverlayClick = true,
  showCloseButton = true,
  className = '',
  themeMode = 'dark',
  colors,
  tabs: manualTabs,
  tabLabels,
  autoTabThreshold = 8,
  fieldsPerTab = 6,
}) => {
  const theme = resolveTheme(THEME_PRESETS, themeMode, colors);
  const [activeTab, setActiveTab] = useState(0);

  const {
    values,
    errors,
    touched,
    isSubmitting,
    handleChange,
    handleBlur,
    handleSubmit,
  } = useFormBuilder({
    fields,
    initialData,
    onSubmit,
    validateOnChange,
    validateOnBlur,
  });

  // Auto-generate tabs if needed
  const tabs = useMemo(() => {
    if (manualTabs && manualTabs.length > 0) {
      return manualTabs;
    }

    // Check if fields have tab assignments
    const hasTabAssignments = fields.some((f) => f.tab);
    if (hasTabAssignments) {
      const tabMap = new Map<string, typeof fields>();
      fields.forEach((field) => {
        const tabName = field.tab || 'General';
        if (!tabMap.has(tabName)) {
          tabMap.set(tabName, []);
        }
        tabMap.get(tabName)!.push(field);
      });

      return Array.from(tabMap.entries()).map(([label, tabFields], index) => ({
        id: `tab-${index}`,
        label,
        fields: tabFields,
      }));
    }

    // Auto-generate tabs if field count exceeds threshold
    if (fields.length > autoTabThreshold) {
      const generatedTabs: FormTab[] = [];
      const numTabs = Math.ceil(fields.length / fieldsPerTab);

      for (let i = 0; i < numTabs; i++) {
        const start = i * fieldsPerTab;
        const end = Math.min(start + fieldsPerTab, fields.length);
        const defaultLabel = i === 0 ? 'General' : `Step ${i + 1}`;
        const label = tabLabels && tabLabels[i] ? tabLabels[i] : defaultLabel;

        generatedTabs.push({
          id: `tab-${i}`,
          label,
          fields: fields.slice(start, end),
        });
      }

      return generatedTabs;
    }

    return null;
  }, [fields, manualTabs, autoTabThreshold, fieldsPerTab, tabLabels]);

  const currentFields = tabs ? tabs[activeTab]?.fields || [] : fields;

  const renderForm = () => (
    <form onSubmit={handleSubmit} className={`space-y-4 ${className}`}>
      {error && (
        <div className={`p-3 ${theme.errorBannerBackground} border ${theme.errorBannerBorder} rounded ${theme.errorText} text-sm`}>
          {error}
        </div>
      )}

      {/* Tab navigation */}
      {tabs && tabs.length > 1 && (
        <div className="border-b border-slate-700 mb-4">
          <nav className="-mb-px flex space-x-4 overflow-x-auto" aria-label="Tabs">
            {tabs.map((tab, index) => {
              const tabHasError = tab.fields.some((field) => touched[field.name] && errors[field.name]);
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(index)}
                  className={`
                    whitespace-nowrap py-2 px-1 border-b-2 font-medium text-sm
                    ${
                      activeTab === index
                        ? 'border-amber-500 text-amber-400'
                        : tabHasError
                        ? 'border-red-500 text-red-400 hover:border-red-400'
                        : 'border-transparent text-slate-400 hover:text-slate-300 hover:border-slate-500'
                    }
                  `}
                >
                  {tab.label}
                  {tabHasError && (
                    <span className="ml-1 inline-flex items-center justify-center w-4 h-4 text-xs font-bold text-white bg-red-500 rounded-full">
                      !
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      )}

      {currentFields.map((field) => (
        <FormField
          key={field.name}
          field={field}
          value={values[field.name]}
          error={touched[field.name] ? errors[field.name] : undefined}
          onChange={handleChange}
          onBlur={handleBlur}
          themeMode={themeMode}
          colors={colors}
        />
      ))}

      <div className="flex justify-end gap-3 pt-2">
        {tabs && tabs.length > 1 ? (
          <>
            {activeTab > 0 && (
              <button
                type="button"
                onClick={() => setActiveTab(activeTab - 1)}
                className={`px-4 py-2 rounded-md border ${theme.secondaryButtonBorder} ${theme.secondaryButton} ${theme.secondaryButtonText} ${theme.secondaryButtonHover} disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                Previous
              </button>
            )}
            {activeTab < tabs.length - 1 ? (
              <button
                type="button"
                onClick={() => setActiveTab(activeTab + 1)}
                className={`px-4 py-2 rounded-md ${theme.primaryButton} ${theme.primaryButtonText} ${theme.primaryButtonHover} disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                Next
              </button>
            ) : (
              <button
                type="submit"
                disabled={isSubmitting || loading}
                className={`px-4 py-2 rounded-md ${theme.primaryButton} ${theme.primaryButtonText} ${theme.primaryButtonHover} disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {isSubmitting || loading ? (
                  <span className="flex items-center gap-2">
                    <svg
                      className="animate-spin h-4 w-4"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    {submitLabel}...
                  </span>
                ) : (
                  submitLabel
                )}
              </button>
            )}
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                disabled={isSubmitting || loading}
                className={`px-4 py-2 rounded-md border ${theme.secondaryButtonBorder} ${theme.secondaryButton} ${theme.secondaryButtonText} ${theme.secondaryButtonHover} disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {cancelLabel}
              </button>
            )}
          </>
        ) : (
          <>
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                disabled={isSubmitting || loading}
                className={`px-4 py-2 rounded-md border ${theme.secondaryButtonBorder} ${theme.secondaryButton} ${theme.secondaryButtonText} ${theme.secondaryButtonHover} disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {cancelLabel}
              </button>
            )}
            <button
              type="submit"
              disabled={isSubmitting || loading}
              className={`px-4 py-2 rounded-md ${theme.primaryButton} ${theme.primaryButtonText} ${theme.primaryButtonHover} disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isSubmitting || loading ? (
                <span className="flex items-center gap-2">
                  <svg
                    className="animate-spin h-4 w-4"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  {submitLabel}...
                </span>
              ) : (
                submitLabel
              )}
            </button>
          </>
        )}
      </div>
    </form>
  );

  if (mode === 'modal') {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onCancel || (() => {})}
        title={title}
        closeOnOverlayClick={closeOnOverlayClick}
        showCloseButton={showCloseButton}
        themeMode={themeMode}
        colors={colors}
      >
        {renderForm()}
      </Modal>
    );
  }

  return (
    <div className={className}>
      {title && <h2 className={`text-xl font-bold ${theme.titleText} mb-4`}>{title}</h2>}
      {renderForm()}
    </div>
  );
};
