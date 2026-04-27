import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import React from 'react';
import { MFAModal } from './MFAModal';

function renderModal(props?: Partial<React.ComponentProps<typeof MFAModal>>) {
  const defaults = {
    isOpen: true,
    onClose: vi.fn(),
    onSubmit: vi.fn(),
    codeLength: 6,
    allowRememberDevice: false,
    isSubmitting: false,
    error: undefined,
  };
  return render(<MFAModal {...defaults} {...props} />);
}

describe('MFAModal', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  // ---------------------------------------------------------------------------
  // Visibility
  // ---------------------------------------------------------------------------

  it('renders nothing when isOpen=false', () => {
    renderModal({ isOpen: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders the dialog when isOpen=true', () => {
    renderModal();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('shows Two-Factor Authentication heading', () => {
    renderModal();
    expect(screen.getByText('Two-Factor Authentication')).toBeInTheDocument();
  });

  it('renders the correct number of digit inputs based on codeLength', () => {
    renderModal({ codeLength: 6 });
    expect(screen.getAllByRole('textbox')).toHaveLength(6);
  });

  // ---------------------------------------------------------------------------
  // Error display
  // ---------------------------------------------------------------------------

  it('shows error message when error prop is set', () => {
    renderModal({ error: 'Invalid code, please try again' });
    expect(screen.getByText('Invalid code, please try again')).toBeInTheDocument();
  });

  it('does not show error when error is undefined', () => {
    renderModal({ error: undefined });
    expect(screen.queryByText(/invalid/i)).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Remember device checkbox
  // ---------------------------------------------------------------------------

  it('does not show remember device checkbox by default', () => {
    renderModal({ allowRememberDevice: false });
    expect(screen.queryByLabelText(/remember this device/i)).not.toBeInTheDocument();
  });

  it('shows remember device checkbox when allowRememberDevice=true', () => {
    renderModal({ allowRememberDevice: true });
    expect(screen.getByLabelText(/remember this device/i)).toBeInTheDocument();
  });

  it('remember device checkbox is initially unchecked', () => {
    renderModal({ allowRememberDevice: true });
    const checkbox = screen.getByLabelText(/remember this device/i) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it('toggling remember device checkbox works', () => {
    renderModal({ allowRememberDevice: true });
    const checkbox = screen.getByLabelText(/remember this device/i) as HTMLInputElement;
    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Submit button state
  // ---------------------------------------------------------------------------

  it('verify button disabled when code is incomplete', () => {
    renderModal({ codeLength: 6 });
    const btn = screen.getByRole('button', { name: /verify/i });
    expect(btn).toBeDisabled();
  });

  it('shows "Verifying..." spinner when isSubmitting=true', () => {
    renderModal({ isSubmitting: true });
    expect(screen.getByText('Verifying...')).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Close / Cancel behaviour
  // ---------------------------------------------------------------------------

  it('calls onClose when Cancel button is clicked', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose when backdrop is clicked', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    // The backdrop is an aria-hidden div at position fixed
    const backdrop = document.querySelector('.fixed.inset-0.bg-black\\/60') as HTMLElement;
    if (backdrop) fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it('Cancel button is disabled when isSubmitting=true', () => {
    renderModal({ isSubmitting: true });
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  // ---------------------------------------------------------------------------
  // Submit flow
  // ---------------------------------------------------------------------------

  it('calls onSubmit with the code when form submitted with valid length', async () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit, codeLength: 6 });

    // Fill all 6 inputs
    const inputs = screen.getAllByRole('textbox');
    ['1', '2', '3', '4', '5', '6'].forEach((digit, i) => {
      fireEvent.change(inputs[i], { target: { value: digit } });
    });

    // Submit the form
    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('123456', false));
  });

  it('calls onSubmit with rememberDevice=true when checkbox checked', async () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit, codeLength: 6, allowRememberDevice: true });

    const inputs = screen.getAllByRole('textbox');
    ['1', '2', '3', '4', '5', '6'].forEach((d, i) => {
      fireEvent.change(inputs[i], { target: { value: d } });
    });

    fireEvent.click(screen.getByLabelText(/remember this device/i));
    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('123456', true));
  });

  it('does NOT call onSubmit when code is shorter than codeLength', async () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit, codeLength: 6 });

    const inputs = screen.getAllByRole('textbox');
    // Only fill 4 of 6
    ['1', '2', '3', '4'].forEach((d, i) => {
      fireEvent.change(inputs[i], { target: { value: d } });
    });

    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!);
    await waitFor(() => expect(onSubmit).not.toHaveBeenCalled());
  });

  // ---------------------------------------------------------------------------
  // Accessibility
  // ---------------------------------------------------------------------------

  it('modal has role="dialog" and aria-modal="true"', () => {
    renderModal();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('modal has aria-labelledby pointing to the heading', () => {
    renderModal();
    const dialog = screen.getByRole('dialog');
    const labelId = dialog.getAttribute('aria-labelledby');
    expect(labelId).toBeTruthy();
    const heading = document.getElementById(labelId!);
    expect(heading).not.toBeNull();
    expect(heading!.textContent).toContain('Two-Factor Authentication');
  });
});
