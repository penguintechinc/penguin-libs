/**
 * Modal Component
 *
 * Reusable modal wrapper with overlay, close button, and escape key handling.
 * Used by FormBuilder in modal mode.
 */

import React, { useEffect } from 'react';
import { ModalProps } from './types';
import { resolveTheme } from '../../theme';
import { THEME_PRESETS } from './themes';

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  children,
  className = '',
  closeOnOverlayClick = true,
  showCloseButton = true,
  themeMode = 'dark',
  colors,
}) => {
  const theme = resolveTheme(THEME_PRESETS, themeMode, colors);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (closeOnOverlayClick && e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div
      className={`fixed inset-0 ${theme.overlayBackground} flex items-center justify-center z-50 p-0 sm:p-4`}
      onClick={handleOverlayClick}
    >
      <div className={`relative z-10 ${theme.modalBackground} w-full h-full sm:h-auto sm:max-w-2xl sm:max-h-[90vh] sm:rounded-lg overflow-y-auto p-6 ${className}`}>
        {(title || showCloseButton) && (
          <div className="flex justify-between items-center mb-4">
            {title && <h2 className={`text-xl font-bold ${theme.titleText}`}>{title}</h2>}
            {showCloseButton && (
              <button
                type="button"
                onClick={onClose}
                className={`${theme.closeButtonText} ${theme.closeButtonHover} transition-colors`}
                aria-label="Close modal"
              >
                <svg
                  className="w-6 h-6"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  );
};
