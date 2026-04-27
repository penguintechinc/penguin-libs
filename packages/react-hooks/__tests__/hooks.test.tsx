import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useBreakpoint, useFormBuilder, resolveTheme } from '../src/index';
import type { FieldConfig } from '@penguintechinc/react-form-builder';

// ============================================================================
// useBreakpoint Tests
// ============================================================================

describe('useBreakpoint', () => {
  let innerWidthSpy: any;

  beforeEach(() => {
    // Mock window.innerWidth
    innerWidthSpy = vi.spyOn(window, 'innerWidth', 'get');
  });

  afterEach(() => {
    innerWidthSpy.mockRestore();
  });

  describe('breakpoint detection', () => {
    it('returns xs breakpoint at 320px width (mobile)', () => {
      innerWidthSpy.mockReturnValue(320);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('xs');
      expect(result.current.width).toBe(320);
    });

    it('returns sm breakpoint at 640px width', () => {
      innerWidthSpy.mockReturnValue(640);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('sm');
    });

    it('returns md breakpoint at 768px width (tablet)', () => {
      innerWidthSpy.mockReturnValue(768);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('md');
    });

    it('returns lg breakpoint at 1024px width (desktop)', () => {
      innerWidthSpy.mockReturnValue(1024);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('lg');
    });

    it('returns xl breakpoint at 1280px width', () => {
      innerWidthSpy.mockReturnValue(1280);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('xl');
    });

    it('returns 2xl breakpoint at 1536px width', () => {
      innerWidthSpy.mockReturnValue(1536);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('2xl');
    });
  });

  describe('boolean helpers', () => {
    it('returns correct isMobile flag at 320px', () => {
      innerWidthSpy.mockReturnValue(320);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.isMobile).toBe(true);
      expect(result.current.isTablet).toBe(false);
      expect(result.current.isDesktop).toBe(false);
      expect(result.current.isMobileOrTablet).toBe(true);
    });

    it('returns correct isTablet flag at 768px', () => {
      innerWidthSpy.mockReturnValue(768);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.isMobile).toBe(false);
      expect(result.current.isTablet).toBe(true);
      expect(result.current.isDesktop).toBe(false);
      expect(result.current.isMobileOrTablet).toBe(true);
    });

    it('returns correct isDesktop flag at 1024px', () => {
      innerWidthSpy.mockReturnValue(1024);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.isMobile).toBe(false);
      expect(result.current.isTablet).toBe(false);
      expect(result.current.isDesktop).toBe(true);
      expect(result.current.isMobileOrTablet).toBe(false);
    });
  });

  describe('hook stability', () => {
    it('provides stable hook return values across renders', () => {
      innerWidthSpy.mockReturnValue(1024);
      const { result, rerender } = renderHook(() => useBreakpoint());

      const firstResult = result.current;
      rerender();
      const secondResult = result.current;

      // Should maintain breakpoint classification across re-renders
      expect(secondResult.breakpoint).toBe(firstResult.breakpoint);
      expect(secondResult.isDesktop).toBe(firstResult.isDesktop);
    });

    it('initializes with correct breakpoint for given width', () => {
      // Test multiple width values to verify initialization
      const widthTests = [
        { width: 320, expected: 'xs' },
        { width: 768, expected: 'md' },
        { width: 1024, expected: 'lg' },
      ];

      widthTests.forEach(({ width, expected }) => {
        innerWidthSpy.mockReturnValue(width);
        const { result } = renderHook(() => useBreakpoint());
        expect(result.current.breakpoint).toBe(expected);
        expect(result.current.width).toBe(width);
      });
    });
  });

  describe('SSR safety', () => {
    it('provides width value at time of render', () => {
      // useBreakpoint uses window.innerWidth which is available in jsdom
      innerWidthSpy.mockReturnValue(1024);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.width).toBe(1024);
      expect(result.current.isDesktop).toBe(true);
    });

    it('handles all breakpoint boundaries correctly', () => {
      const tests = [
        { width: 0, expected: 'xs', isMobile: true },
        { width: 320, expected: 'xs', isMobile: true },
        { width: 640, expected: 'sm', isMobile: false },
        { width: 768, expected: 'md', isMobile: false },
        { width: 1024, expected: 'lg', isMobile: false },
        { width: 1280, expected: 'xl', isMobile: false },
        { width: 1536, expected: '2xl', isMobile: false },
      ];

      tests.forEach(({ width, expected, isMobile }) => {
        innerWidthSpy.mockReturnValue(width);
        const { result } = renderHook(() => useBreakpoint());
        expect(result.current.breakpoint).toBe(expected);
        expect(result.current.isMobile).toBe(isMobile);
      });
    });
  });

  describe('edge cases', () => {
    it('handles boundary widths correctly', () => {
      innerWidthSpy.mockReturnValue(639);
      const { result: result1 } = renderHook(() => useBreakpoint());
      expect(result1.current.breakpoint).toBe('xs');

      innerWidthSpy.mockReturnValue(640);
      const { result: result2 } = renderHook(() => useBreakpoint());
      expect(result2.current.breakpoint).toBe('sm');
    });

    it('handles very large widths', () => {
      innerWidthSpy.mockReturnValue(9999);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('2xl');
      expect(result.current.isDesktop).toBe(true);
    });
  });
});

// ============================================================================
// useFormBuilder Tests
// ============================================================================

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

// ============================================================================
// resolveTheme Tests
// ============================================================================

describe('resolveTheme', () => {
  const darkPreset = {
    bg: '#000',
    text: '#fff',
    primary: '#007bff',
  };

  const lightPreset = {
    bg: '#fff',
    text: '#000',
    primary: '#0056b3',
  };

  const presets = {
    dark: darkPreset,
    light: lightPreset,
  };

  it('returns dark theme by default', () => {
    const result = resolveTheme(presets);
    expect(result).toEqual(darkPreset);
  });

  it('returns dark theme when explicitly specified', () => {
    const result = resolveTheme(presets, 'dark');
    expect(result).toEqual(darkPreset);
  });

  it('returns light theme when specified', () => {
    const result = resolveTheme(presets, 'light');
    expect(result).toEqual(lightPreset);
  });

  it('merges overrides with dark theme', () => {
    const overrides = { primary: '#ffff00' };
    const result = resolveTheme(presets, 'dark', overrides);
    expect(result).toEqual({
      bg: '#000',
      text: '#fff',
      primary: '#ffff00',
    });
  });

  it('merges overrides with light theme', () => {
    const overrides = { bg: '#f5f5f5' };
    const result = resolveTheme(presets, 'light', overrides);
    expect(result).toEqual({
      bg: '#f5f5f5',
      text: '#000',
      primary: '#0056b3',
    });
  });

  it('merges multiple overrides', () => {
    const overrides = { bg: '#f0f0f0', text: '#333', primary: '#ff0000' };
    const result = resolveTheme(presets, 'dark', overrides);
    expect(result).toEqual({
      bg: '#f0f0f0',
      text: '#333',
      primary: '#ff0000',
    });
  });

  it('returns base theme when overrides is undefined', () => {
    const result = resolveTheme(presets, 'dark', undefined);
    expect(result).toEqual(darkPreset);
  });

  it('does not mutate the original preset', () => {
    const overrides = { primary: '#ffff00' };
    resolveTheme(presets, 'dark', overrides);
    expect(presets.dark.primary).toBe('#007bff');
  });

  it('works with generic types', () => {
    interface CustomColors {
      background: string;
      foreground: string;
      accent: string;
    }

    const customPresets: Record<'dark' | 'light', CustomColors> = {
      dark: { background: '#1a1a1a', foreground: '#fff', accent: '#00ff00' },
      light: { background: '#fff', foreground: '#000', accent: '#0000ff' },
    };

    const result = resolveTheme(customPresets, 'dark', { accent: '#ff00ff' });
    expect(result.accent).toBe('#ff00ff');
    expect(result.background).toBe('#1a1a1a');
  });
});
