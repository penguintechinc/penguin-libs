import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFormBuilder } from '../src/useFormBuilder';
import type { FieldConfig } from '../src/types';

describe('useFormBuilder', () => {
  const createField = (
    overrides?: Partial<FieldConfig>
  ): FieldConfig => ({
    name: 'email',
    label: 'Email',
    type: 'email',
    defaultValue: '',
    ...overrides,
  });

  describe('initialization', () => {
    it('initializes with empty values when no initialData provided', () => {
      const fields = [createField(), createField({ name: 'name', label: 'Name' })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.values).toEqual({ email: '', name: '' });
      expect(result.current.errors).toEqual({});
      expect(result.current.touched).toEqual({});
      expect(result.current.isSubmitting).toBe(false);
      expect(result.current.isDirty).toBe(false);
      expect(result.current.isValid).toBe(true);
    });

    it('initializes with provided initialData', () => {
      const fields = [
        createField(),
        createField({ name: 'name', label: 'Name' }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          initialData: { email: 'test@example.com', name: 'John' },
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.values).toEqual({
        email: 'test@example.com',
        name: 'John',
      });
    });

    it('uses field defaultValue when initialData not provided', () => {
      const fields = [
        createField({ defaultValue: 'default@example.com' }),
        createField({ name: 'name', label: 'Name', defaultValue: 'Default Name' }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.values).toEqual({
        email: 'default@example.com',
        name: 'Default Name',
      });
    });

    it('initialData takes precedence over field defaultValue', () => {
      const fields = [
        createField({ defaultValue: 'default@example.com' }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          initialData: { email: 'override@example.com' },
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.values.email).toBe('override@example.com');
    });
  });

  describe('setValue / handleChange', () => {
    it('updates field value with setFieldValue', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'new@example.com');
      });

      expect(result.current.values.email).toBe('new@example.com');
    });

    it('updates field value with handleChange', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.handleChange('email', 'new@example.com');
      });

      expect(result.current.values.email).toBe('new@example.com');
    });

    it('marks form as dirty after setValue', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.isDirty).toBe(false);

      act(() => {
        result.current.setFieldValue('email', 'new@example.com');
      });

      expect(result.current.isDirty).toBe(true);
    });
  });

  describe('error handling', () => {
    it('setError sets error for a field', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldError('email', 'Invalid email');
      });

      expect(result.current.errors.email).toBe('Invalid email');
      expect(result.current.isValid).toBe(false);
    });

    it('clearing error field removes it from errors', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldError('email', 'Invalid email');
      });
      expect(result.current.errors.email).toBe('Invalid email');

      act(() => {
        result.current.setFieldError('email', '');
      });
      expect(result.current.errors.email).toBe('');
    });
  });

  describe('validation', () => {
    it('validates required field on submit', async () => {
      const fields = [createField({ required: true })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.email).toBeTruthy();
      expect(onSubmit).not.toHaveBeenCalled();
    });

    it('validates email format', async () => {
      const fields = [createField({ type: 'email' })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'invalid-email');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.email).toBe('Invalid email address');
    });

    it('accepts valid email addresses', async () => {
      const fields = [createField({ type: 'email', required: false })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'valid@example.com');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.email).toBeUndefined();
      expect(onSubmit).toHaveBeenCalledWith({ email: 'valid@example.com' });
    });

    it('validates URL type fields', async () => {
      const fields = [createField({ type: 'url', required: false })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'not-a-url');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.email).toBe('Invalid URL');
    });

    it('accepts valid URLs', async () => {
      const fields = [createField({ type: 'url', name: 'website', label: 'Website', required: false })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      act(() => {
        result.current.setFieldValue('website', 'https://example.com');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.website).toBeUndefined();
      expect(onSubmit).toHaveBeenCalled();
    });

    it('validates minLength constraint', async () => {
      const fields = [
        createField({ name: 'password', label: 'Password', type: 'text', minLength: 8, required: false }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('password', 'short');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.password).toContain('at least 8');
    });

    it('validates maxLength constraint', async () => {
      const fields = [
        createField({ name: 'code', label: 'Code', type: 'text', maxLength: 5, required: false }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('code', 'toolongcode');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.code).toContain('at most 5');
    });

    it('validates min numeric constraint', async () => {
      const fields = [
        createField({ name: 'age', label: 'Age', type: 'number', min: 18, required: false }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('age', 15);
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.age).toContain('at least 18');
    });

    it('validates max numeric constraint', async () => {
      const fields = [
        createField({ name: 'age', label: 'Age', type: 'number', max: 100, required: false }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('age', 150);
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.age).toContain('at most 100');
    });

    it('validates pattern constraint', async () => {
      const fields = [
        createField({ name: 'phone', label: 'Phone', type: 'text', pattern: '^\\d{10}$', required: false }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('phone', '123456');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.phone).toBe('Invalid format');
    });

    it('uses custom validate function if provided', async () => {
      const customValidator = (value: string) => {
        return value.includes('special') ? null : 'Must contain "special"';
      };
      const fields = [
        createField({
          validate: customValidator,
          required: false,
        }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'nope');
      });

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.errors.email).toBe('Must contain "special"');
    });

    it('validateOnChange validates while typing', () => {
      const fields = [createField({ required: true })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
          validateOnChange: true,
        })
      );

      act(() => {
        result.current.handleChange('email', '');
      });

      expect(result.current.errors.email).toBeTruthy();

      act(() => {
        result.current.handleChange('email', 'valid@example.com');
      });

      expect(result.current.errors.email).toBeUndefined();
    });

    it('validateOnBlur validates on blur by default', () => {
      const fields = [createField({ required: true })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
          validateOnBlur: true,
        })
      );

      expect(result.current.errors.email).toBeUndefined();

      act(() => {
        result.current.handleBlur('email');
      });

      expect(result.current.errors.email).toBeTruthy();
    });
  });

  describe('form submission', () => {
    it('calls onSubmit with values when form is valid', async () => {
      const fields = [createField({ required: false })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          initialData: { email: 'test@example.com' },
          onSubmit,
        })
      );

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(onSubmit).toHaveBeenCalledWith({ email: 'test@example.com' });
    });

    it('does not call onSubmit when form has validation errors', async () => {
      const fields = [createField({ required: true })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(onSubmit).not.toHaveBeenCalled();
    });

    it('sets isSubmitting flag during submission', async () => {
      const fields = [createField({ required: false })];
      let resolveSubmit: () => void;
      const submitPromise = new Promise<void>((resolve) => {
        resolveSubmit = resolve;
      });
      const onSubmit = vi.fn(() => submitPromise);
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      const submitPromiseResult = act(async () => {
        await result.current.handleSubmit();
      });

      resolveSubmit!();
      await submitPromiseResult;

      expect(result.current.isSubmitting).toBe(false);
    });

    it('marks all fields as touched on submit', async () => {
      const fields = [
        createField(),
        createField({ name: 'name', label: 'Name' }),
      ];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.touched).toEqual({ email: true, name: true });
    });

    it('handles async onSubmit functions', async () => {
      const fields = [createField({ required: false })];
      const onSubmit = vi.fn(
        () =>
          new Promise((resolve) => {
            setTimeout(resolve, 10);
          })
      );
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(onSubmit).toHaveBeenCalled();
    });

    it('prevents default form submission when e is provided', async () => {
      const fields = [createField({ required: false })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      const mockEvent = {
        preventDefault: vi.fn(),
      } as any;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
    });
  });

  describe('touched fields tracking', () => {
    it('marks field as touched on blur', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.touched.email).toBeUndefined();

      act(() => {
        result.current.handleBlur('email');
      });

      expect(result.current.touched.email).toBe(true);
    });

    it('tracks multiple touched fields', () => {
      const fields = [
        createField(),
        createField({ name: 'name', label: 'Name' }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.handleBlur('email');
      });

      expect(result.current.touched.email).toBe(true);
      expect(result.current.touched.name).toBeUndefined();

      act(() => {
        result.current.handleBlur('name');
      });

      expect(result.current.touched).toEqual({ email: true, name: true });
    });
  });

  describe('resetForm', () => {
    it('resets values to initial state', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          initialData: { email: 'initial@example.com' },
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'changed@example.com');
      });

      expect(result.current.values.email).toBe('changed@example.com');

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.values.email).toBe('initial@example.com');
    });

    it('clears all errors on reset', () => {
      const fields = [createField({ required: true })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldError('email', 'Error message');
      });

      expect(result.current.errors.email).toBeTruthy();

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.errors).toEqual({});
    });

    it('clears all touched fields on reset', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.handleBlur('email');
      });

      expect(result.current.touched.email).toBe(true);

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.touched).toEqual({});
    });

    it('marks form as not dirty after reset', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'changed@example.com');
      });

      expect(result.current.isDirty).toBe(true);

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.isDirty).toBe(false);
    });
  });

  describe('computed properties', () => {
    it('isDirty reflects if form has been modified', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          initialData: { email: 'initial@example.com' },
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.isDirty).toBe(false);

      act(() => {
        result.current.setFieldValue('email', 'changed@example.com');
      });

      expect(result.current.isDirty).toBe(true);
    });

    it('isDirty is false when form is reset to initial state', () => {
      const fields = [createField()];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          initialData: { email: 'initial@example.com' },
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setFieldValue('email', 'changed@example.com');
      });

      expect(result.current.isDirty).toBe(true);

      act(() => {
        result.current.setFieldValue('email', 'initial@example.com');
      });

      expect(result.current.isDirty).toBe(false);
    });

    it('isValid reflects validation state', async () => {
      const fields = [createField({ required: true })];
      const onSubmit = vi.fn();
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit,
        })
      );

      // Before validation, isValid is true (no errors yet)
      expect(result.current.isValid).toBe(true);

      // Trigger validation by submitting with empty value
      await act(async () => {
        await result.current.handleSubmit();
      });

      expect(result.current.isValid).toBe(false);

      // Fill the required field
      act(() => {
        result.current.setFieldValue('email', 'valid@example.com');
      });

      // Still has errors from previous validation
      expect(result.current.errors.email).toBeTruthy();
      expect(result.current.isValid).toBe(false);

      // Reset and fill properly
      act(() => {
        result.current.resetForm();
        result.current.setFieldValue('email', 'valid@example.com');
      });

      expect(result.current.isValid).toBe(true);
    });

    it('isValid becomes false when error is set', () => {
      const fields = [createField({ required: false })];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      expect(result.current.isValid).toBe(true);

      act(() => {
        result.current.setFieldError('email', 'Custom error');
      });

      expect(result.current.isValid).toBe(false);
    });
  });

  describe('setValues', () => {
    it('sets multiple field values at once', () => {
      const fields = [
        createField(),
        createField({ name: 'name', label: 'Name' }),
      ];
      const { result } = renderHook(() =>
        useFormBuilder({
          fields,
          onSubmit: vi.fn(),
        })
      );

      act(() => {
        result.current.setValues({
          email: 'new@example.com',
          name: 'John Doe',
        });
      });

      expect(result.current.values).toEqual({
        email: 'new@example.com',
        name: 'John Doe',
      });
    });
  });
});
