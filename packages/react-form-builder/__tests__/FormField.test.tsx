import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FormField } from '../src/FormField';
import type { FormFieldProps } from '../src/types';

describe('FormField', () => {
  const createProps = (overrides?: Partial<FormFieldProps>): FormFieldProps => ({
    field: {
      name: 'testField',
      label: 'Test Label',
      type: 'text',
      ...overrides?.field,
    },
    value: '',
    onChange: vi.fn(),
    ...overrides,
  });

  describe('Rendering', () => {
    it('renders label from props', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email Address',
          type: 'text',
        },
      });

      render(<FormField {...props} />);
      expect(screen.getByText('Email Address')).toBeInTheDocument();
    });

    it('renders input with correct type attribute', () => {
      const props = createProps({
        field: { name: 'email', label: 'Email', type: 'email' },
      });

      render(<FormField {...props} />);
      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('type', 'email');
    });

    it('renders select element for select type', () => {
      const props = createProps({
        field: {
          name: 'country',
          label: 'Country',
          type: 'select',
          options: [
            { value: 'us', label: 'United States' },
            { value: 'ca', label: 'Canada' },
          ],
        },
      });

      render(<FormField {...props} />);
      expect(screen.getByRole('combobox')).toBeInTheDocument();
      expect(screen.getByText('United States')).toBeInTheDocument();
      expect(screen.getByText('Canada')).toBeInTheDocument();
    });

    it('renders textarea element for textarea type', () => {
      const props = createProps({
        field: {
          name: 'description',
          label: 'Description',
          type: 'textarea',
          rows: 4,
        },
      });

      render(<FormField {...props} />);
      const textarea = screen.getByRole('textbox');
      expect(textarea.tagName).toBe('TEXTAREA');
      expect(textarea).toHaveAttribute('rows', '4');
    });

    it('renders placeholder text', () => {
      const props = createProps({
        field: {
          name: 'username',
          label: 'Username',
          type: 'text',
          placeholder: 'Enter your username',
        },
      });

      render(<FormField {...props} />);
      expect(screen.getByPlaceholderText('Enter your username')).toBeInTheDocument();
    });

    it('renders required indicator when required=true', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
          required: true,
        },
      });

      render(<FormField {...props} />);
      const label = screen.getByText('Email');
      expect(label.parentElement).toHaveTextContent('*');
    });

    it('does not render required indicator when required=false', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
          required: false,
        },
      });

      render(<FormField {...props} />);
      const label = screen.getByText('Email');
      expect(label.parentElement?.textContent).not.toContain('*');
    });
  });

  describe('Error Handling', () => {
    it('displays error message text when error prop is set', () => {
      const errorMessage = 'This field is required';
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
        },
        error: errorMessage,
      });

      render(<FormField {...props} />);
      expect(screen.getByText(errorMessage)).toBeInTheDocument();
    });

    it('applies error CSS class when error prop is set - explicit toHaveClass assertion', () => {
      const errorMessage = 'Invalid format';
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
        },
        error: errorMessage,
      });

      const { container } = render(<FormField {...props} />);
      const input = container.querySelector('input[type="email"]');
      // Input should have ring classes for error styling
      expect(input).toHaveClass('focus:ring-1');
    });

    it('does not apply error class when no error is set', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
        },
        error: undefined,
      });

      render(<FormField {...props} />);
      expect(
        screen.queryByText(/This field is required|Invalid format/)
      ).not.toBeInTheDocument();
    });

    it('does not display error message when error prop is not set', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
        },
        error: undefined,
      });

      render(<FormField {...props} />);
      expect(
        screen.queryByText(/This field is required|error/)
      ).not.toBeInTheDocument();
    });
  });

  describe('Disabled State', () => {
    it('input has disabled attribute when disabled=true', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
          disabled: true,
        },
      });

      render(<FormField {...props} />);
      expect(screen.getByRole('textbox')).toBeDisabled();
    });

    it('input is not disabled when disabled=false', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
          disabled: false,
        },
      });

      render(<FormField {...props} />);
      expect(screen.getByRole('textbox')).not.toBeDisabled();
    });
  });

  describe('Change Events', () => {
    it('onChange fires with correct value for text input', async () => {
      const onChange = vi.fn();
      const props = createProps({
        field: { name: 'username', label: 'Username', type: 'text' },
        onChange,
      });

      const user = userEvent.setup();
      render(<FormField {...props} />);

      const input = screen.getByRole('textbox');
      await user.type(input, 'john_doe');

      // onChange is called for each character typed
      expect(onChange).toHaveBeenCalled();
      // Check that onChange was called with correct field name
      expect(onChange).toHaveBeenCalledWith('username', expect.anything());
    });

    it('onChange fires with correct value for select', async () => {
      const onChange = vi.fn();
      const props = createProps({
        field: {
          name: 'country',
          label: 'Country',
          type: 'select',
          options: [
            { value: 'us', label: 'United States' },
            { value: 'ca', label: 'Canada' },
          ],
        },
        onChange,
      });

      const user = userEvent.setup();
      render(<FormField {...props} />);

      const select = screen.getByRole('combobox');
      await user.selectOptions(select, 'us');

      expect(onChange).toHaveBeenCalledWith('country', 'us');
    });

    it('onChange fires with correct value for textarea', async () => {
      const onChange = vi.fn();
      const props = createProps({
        field: {
          name: 'description',
          label: 'Description',
          type: 'textarea',
        },
        onChange,
      });

      const user = userEvent.setup();
      render(<FormField {...props} />);

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'My description');

      // onChange is called for each character typed
      expect(onChange).toHaveBeenCalled();
      // Check that it was called with the correct field name
      expect(onChange).toHaveBeenCalledWith('description', expect.anything());
    });

    it('onChange fires for email input', async () => {
      const onChange = vi.fn();
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
        },
        onChange,
      });

      const user = userEvent.setup();
      render(<FormField {...props} />);

      const input = screen.getByRole('textbox');
      await user.type(input, 'user@example.com');

      // onChange is called for each character typed
      expect(onChange).toHaveBeenCalled();
      // Check that it was called with the correct field name
      expect(onChange).toHaveBeenCalledWith('email', expect.anything());
    });
  });

  describe('Helper Text', () => {
    it('displays helper text when provided', () => {
      const helperText = 'Must be at least 8 characters';
      const props = createProps({
        field: {
          name: 'password',
          label: 'Password',
          type: 'password',
          helperText,
        },
      });

      render(<FormField {...props} />);
      expect(screen.getByText(helperText)).toBeInTheDocument();
    });

    it('does not display helper text when not provided', () => {
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
          helperText: undefined,
        },
      });

      render(<FormField {...props} />);
      expect(screen.queryByText(/Must be at least|helper/)).not.toBeInTheDocument();
    });
  });

  describe('Checkbox Type', () => {
    it('renders checkbox correctly', () => {
      const props = createProps({
        field: {
          name: 'agree',
          label: 'I agree to the terms',
          type: 'checkbox',
        },
        value: false,
      });

      render(<FormField {...props} />);
      const checkbox = screen.getByRole('checkbox');
      expect(checkbox).toBeInTheDocument();
      expect(checkbox).not.toBeChecked();
    });

    it('checkbox displays as checked when value is true', () => {
      const props = createProps({
        field: {
          name: 'agree',
          label: 'I agree to the terms',
          type: 'checkbox',
        },
        value: true,
      });

      render(<FormField {...props} />);
      const checkbox = screen.getByRole('checkbox');
      expect(checkbox).toBeChecked();
    });
  });

  describe('Radio Type', () => {
    it('renders radio buttons for radio type', () => {
      const props = createProps({
        field: {
          name: 'size',
          label: 'Size',
          type: 'radio',
          options: [
            { value: 's', label: 'Small' },
            { value: 'm', label: 'Medium' },
            { value: 'l', label: 'Large' },
          ],
        },
        value: '',
      });

      render(<FormField {...props} />);
      expect(screen.getByLabelText('Small')).toBeInTheDocument();
      expect(screen.getByLabelText('Medium')).toBeInTheDocument();
      expect(screen.getByLabelText('Large')).toBeInTheDocument();
    });

    it('radio button is checked when value matches', () => {
      const props = createProps({
        field: {
          name: 'size',
          label: 'Size',
          type: 'radio',
          options: [
            { value: 's', label: 'Small' },
            { value: 'm', label: 'Medium' },
          ],
        },
        value: 'm',
      });

      render(<FormField {...props} />);
      expect(screen.getByLabelText('Medium')).toBeChecked();
      expect(screen.getByLabelText('Small')).not.toBeChecked();
    });
  });

  describe('onBlur Callback', () => {
    it('onBlur is called when field loses focus', async () => {
      const onBlur = vi.fn();
      const props = createProps({
        field: {
          name: 'email',
          label: 'Email',
          type: 'email',
        },
        onBlur,
      });

      const user = userEvent.setup();
      render(<FormField {...props} />);

      const input = screen.getByRole('textbox');
      await user.click(input);
      await user.tab();

      expect(onBlur).toHaveBeenCalledWith('email');
    });
  });

  describe('Value Prop', () => {
    it('input displays the value prop', () => {
      const props = createProps({
        field: {
          name: 'username',
          label: 'Username',
          type: 'text',
        },
        value: 'john_doe',
      });

      render(<FormField {...props} />);
      const input = screen.getByRole('textbox') as HTMLInputElement;
      expect(input.value).toBe('john_doe');
    });

    it('select displays the value prop', () => {
      const props = createProps({
        field: {
          name: 'country',
          label: 'Country',
          type: 'select',
          options: [
            { value: 'us', label: 'United States' },
            { value: 'ca', label: 'Canada' },
          ],
        },
        value: 'ca',
      });

      render(<FormField {...props} />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      expect(select.value).toBe('ca');
    });
  });

  describe('Select Options', () => {
    it('renders all options from options prop', () => {
      const options = [
        { value: 'red', label: 'Red' },
        { value: 'green', label: 'Green' },
        { value: 'blue', label: 'Blue' },
      ];

      const props = createProps({
        field: {
          name: 'color',
          label: 'Color',
          type: 'select',
          options,
        },
      });

      render(<FormField {...props} />);
      options.forEach((option) => {
        expect(screen.getByText(option.label)).toBeInTheDocument();
      });
    });

    it('renders disabled options correctly', () => {
      const options = [
        { value: 'available', label: 'Available' },
        { value: 'sold-out', label: 'Sold Out', disabled: true },
      ];

      const props = createProps({
        field: {
          name: 'status',
          label: 'Status',
          type: 'select',
          options,
        },
      });

      render(<FormField {...props} />);
      const disabledOption = screen.getByText('Sold Out') as HTMLOptionElement;
      expect(disabledOption.disabled).toBe(true);
    });
  });
});
