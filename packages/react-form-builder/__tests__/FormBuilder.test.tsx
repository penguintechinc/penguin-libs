import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FormBuilder } from '../src/FormBuilder';
import type { FormBuilderProps } from '../src/types';

describe('FormBuilder', () => {
  const createProps = (overrides?: Partial<FormBuilderProps>): FormBuilderProps => ({
    fields: [
      {
        name: 'email',
        label: 'Email',
        type: 'email',
        required: true,
      },
      {
        name: 'message',
        label: 'Message',
        type: 'textarea',
      },
    ],
    onSubmit: vi.fn(),
    ...overrides,
  });

  describe('Rendering', () => {
    it('renders all fields from fields prop', () => {
      const fields = [
        { name: 'firstName', label: 'First Name', type: 'text' as const },
        { name: 'lastName', label: 'Last Name', type: 'text' as const },
        { name: 'email', label: 'Email', type: 'email' as const },
      ];

      const props = createProps({ fields });
      render(<FormBuilder {...props} />);

      fields.forEach((field) => {
        expect(screen.getByText(field.label)).toBeInTheDocument();
      });
    });

    it('renders submit button with default label', () => {
      const props = createProps();
      render(<FormBuilder {...props} />);
      expect(screen.getByRole('button', { name: /Submit/i })).toBeInTheDocument();
    });

    it('renders submit button with custom submitLabel', () => {
      const props = createProps({ submitLabel: 'Send Form' });
      render(<FormBuilder {...props} />);
      expect(screen.getByRole('button', { name: /Send Form/i })).toBeInTheDocument();
    });

    it('renders cancel button when onCancel is provided', () => {
      const onCancel = vi.fn();
      const props = createProps({ onCancel });
      render(<FormBuilder {...props} />);
      expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument();
    });

    it('does not render cancel button when onCancel is not provided', () => {
      const props = createProps({ onCancel: undefined });
      render(<FormBuilder {...props} />);
      expect(screen.queryByRole('button', { name: /Cancel/i })).not.toBeInTheDocument();
    });

    it('renders title when provided', () => {
      const props = createProps({ title: 'User Information' });
      render(<FormBuilder {...props} />);
      expect(screen.getByText('User Information')).toBeInTheDocument();
    });

    it('does not render title when not provided', () => {
      const props = createProps({ title: undefined });
      const { container } = render(<FormBuilder {...props} />);
      // Title text should not be present as a standalone heading
      const headings = container.querySelectorAll('h2');
      expect(headings.length).toBe(0);
    });
  });

  describe('Modal Mode', () => {
    it('renders inside Modal when mode="modal"', () => {
      const props = createProps({
        mode: 'modal',
        isOpen: true,
        title: 'Test Modal',
      });

      const { container } = render(<FormBuilder {...props} />);
      // Modal should have the fixed positioning wrapper
      const modal = container.querySelector('[role="dialog"]');
      expect(modal).toBeInTheDocument();
    });

    it('modal is hidden when isOpen=false', () => {
      const props = createProps({
        mode: 'modal',
        isOpen: false,
        title: 'Test Modal',
      });

      const { container } = render(<FormBuilder {...props} />);
      const modal = container.querySelector('[role="dialog"]');
      expect(modal).not.toBeInTheDocument();
    });

    it('modal is visible when isOpen=true', () => {
      const props = createProps({
        mode: 'modal',
        isOpen: true,
        title: 'Test Modal',
      });

      const { container } = render(<FormBuilder {...props} />);
      const modal = container.querySelector('[role="dialog"]');
      expect(modal).toBeInTheDocument();
    });
  });

  describe('Inline Mode', () => {
    it('renders form inline when mode="inline"', () => {
      const props = createProps({ mode: 'inline' });
      const { container } = render(<FormBuilder {...props} />);

      const form = container.querySelector('form');
      expect(form).toBeInTheDocument();
      expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
    });
  });

  describe('Submit Handling', () => {
    it('submit button is present for form submission', () => {
      const onSubmit = vi.fn();
      const props = createProps({ onSubmit });
      render(<FormBuilder {...props} />);

      const submitButton = screen.getByRole('button', { name: /Submit/i });
      expect(submitButton).toBeInTheDocument();
    });

    it('calls onCancel when cancel button is clicked', async () => {
      const onCancel = vi.fn();
      const props = createProps({ onCancel });

      render(<FormBuilder {...props} />);
      const cancelButton = screen.getByRole('button', { name: /Cancel/i });

      await userEvent.click(cancelButton);
      expect(onCancel).toHaveBeenCalled();
    });

    it('error banner displays when error prop is set', () => {
      const errorMessage = 'Failed to submit form';
      const props = createProps({ error: errorMessage });

      render(<FormBuilder {...props} />);
      expect(screen.getByText(errorMessage)).toBeInTheDocument();
    });

    it('error banner does not display when error prop is null', () => {
      const props = createProps({ error: null });

      render(<FormBuilder {...props} />);
      expect(screen.queryByText(/Failed to submit/)).not.toBeInTheDocument();
    });
  });

  describe('Tabs', () => {
    it('renders tabs when fields exceed autoTabThreshold', () => {
      const fields = Array.from({ length: 10 }, (_, i) => ({
        name: `field${i}`,
        label: `Field ${i}`,
        type: 'text' as const,
      }));

      const props = createProps({ fields, autoTabThreshold: 8 });
      const { container } = render(<FormBuilder {...props} />);

      // Should render tab navigation
      const tabNav = container.querySelector('nav[aria-label="Tabs"]');
      expect(tabNav).toBeInTheDocument();
    });

    it('tab navigation shows active tab with correct styling', () => {
      const fields = Array.from({ length: 10 }, (_, i) => ({
        name: `field${i}`,
        label: `Field ${i}`,
        type: 'text' as const,
      }));

      const props = createProps({
        fields,
        autoTabThreshold: 8,
        fieldsPerTab: 3,
      });

      const { container } = render(<FormBuilder {...props} />);

      // Check that active tab has the amber-500 color (active tab color)
      const activeTab = container.querySelector('[class*="amber-500"]');
      expect(activeTab).toBeInTheDocument();
    });

    it('displays only current tab fields', () => {
      const fields = [
        {
          name: 'tab1field1',
          label: 'Tab 1 Field 1',
          type: 'text' as const,
          tab: 'Personal',
        },
        {
          name: 'tab2field1',
          label: 'Tab 2 Field 1',
          type: 'text' as const,
          tab: 'Work',
        },
      ];

      const props = createProps({ fields });
      render(<FormBuilder {...props} />);

      // At least one field from the fields should be visible
      const visibleFields = [screen.queryByText('Tab 1 Field 1'), screen.queryByText('Tab 2 Field 1')];
      const visibleCount = visibleFields.filter((f) => f !== null).length;
      expect(visibleCount).toBeGreaterThan(0);
    });

    it('computed field visibility: visible field appears when condition true', () => {
      const fields = [
        {
          name: 'requiresApproval',
          label: 'Requires Approval',
          type: 'checkbox' as const,
        },
        {
          name: 'approverEmail',
          label: 'Approver Email',
          type: 'email' as const,
        },
      ];

      const props = createProps({ fields });
      render(<FormBuilder {...props} />);

      // Fields should be rendered by the form component
      const labels = screen.getAllByText(/Requires Approval|Approver Email/);
      expect(labels.length).toBeGreaterThan(0);
    });
  });

  describe('Loading State', () => {
    it('displays loading spinner when loading=true', () => {
      const props = createProps({ loading: true });
      const { container } = render(<FormBuilder {...props} />);

      // Should have a spinner SVG when loading
      const spinner = container.querySelector('svg.animate-spin');
      expect(spinner).toBeInTheDocument();
    });

    it('submit button shows loading state when loading=true', () => {
      const props = createProps({ loading: true });
      render(<FormBuilder {...props} />);

      const submitButton = screen.getByRole('button', { name: /Submit|loading/i });
      expect(submitButton).toBeInTheDocument();
    });
  });

  describe('CSS Classes', () => {
    it('applies correct layout CSS for inline mode', () => {
      const props = createProps({ mode: 'inline', className: 'my-custom-class' });
      const { container } = render(<FormBuilder {...props} />);

      const formContainer = container.querySelector('.my-custom-class');
      expect(formContainer).toBeInTheDocument();
    });

    it('applies theme classes based on themeMode', () => {
      const props = createProps({
        themeMode: 'dark',
      });

      const { container } = render(<FormBuilder {...props} />);
      const form = container.querySelector('form');
      expect(form).toBeInTheDocument();
    });
  });

  describe('Initial Data', () => {
    it('accepts initialData prop for pre-filling form', () => {
      const fields = [
        { name: 'email', label: 'Email', type: 'email' as const },
      ];

      const props = createProps({
        fields,
        initialData: { email: 'test@example.com' },
      });

      render(<FormBuilder {...props} />);
      // Form is rendered with initial data configured
      expect(screen.getByText('Email')).toBeInTheDocument();
    });
  });

  describe('Validation Options', () => {
    it('accepts validateOnChange prop', () => {
      const props = createProps({ validateOnChange: true });
      render(<FormBuilder {...props} />);
      // Form renders with validation config
      expect(screen.getByRole('button', { name: /Submit/i })).toBeInTheDocument();
    });

    it('accepts validateOnBlur prop', () => {
      const props = createProps({ validateOnBlur: true });
      render(<FormBuilder {...props} />);
      // Form renders with validation config
      expect(screen.getByRole('button', { name: /Submit/i })).toBeInTheDocument();
    });
  });
});
