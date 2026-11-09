import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FormModalBuilder, z } from '../components/FormModalBuilder';
import type { FormField } from '../components/FormModalBuilder';

/** Render the modal with the given fields and click submit, returning the submit spy. */
async function submitWith(fields: FormField[], fill?: (c: HTMLElement) => Promise<void> | void) {
  const onSubmit = vi.fn();
  const { container } = render(
    <FormModalBuilder title="T" fields={fields} isOpen onClose={vi.fn()} onSubmit={onSubmit} />
  );
  if (fill) await fill(container);
  await userEvent.click(screen.getByRole('button', { name: /Submit/i }));
  return { onSubmit, container };
}

afterEach(cleanup);

describe('FormModalBuilder validation messages (zod 4)', () => {
  it('re-exports the zod 4 API', () => {
    expect(typeof z.treeifyError).toBe('function');
    expect(typeof z.flattenError).toBe('function');
  });

  it('reports invalid URL with the custom message', async () => {
    const { onSubmit } = await submitWith(
      [{ name: 'site', type: 'url', label: 'Site', required: true }],
      async (c) => {
        await userEvent.type(c.querySelector('#site') as HTMLInputElement, 'not a url');
      }
    );
    await waitFor(() => expect(screen.getByText('Site must be a valid URL')).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('accepts a valid URL and email', async () => {
    const { onSubmit } = await submitWith(
      [
        { name: 'site', type: 'url', label: 'Site', required: true },
        { name: 'mail', type: 'email', label: 'Mail', required: true },
      ],
      async (c) => {
        await userEvent.type(c.querySelector('#site') as HTMLInputElement, 'https://example.com');
        await userEvent.type(c.querySelector('#mail') as HTMLInputElement, 'a@example.com');
      }
    );
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it('enforces number min and max with custom messages', async () => {
    const field: FormField = { name: 'qty', type: 'number', label: 'Qty', min: 2, max: 5 };
    const low = await submitWith([field], (c) => {
      fireEvent.change(c.querySelector('#qty') as HTMLInputElement, { target: { value: '1' } });
    });
    await waitFor(() => expect(screen.getByText('Qty must be at least 2')).toBeInTheDocument());
    expect(low.onSubmit).not.toHaveBeenCalled();
  });

  it('enforces number max with a custom message', async () => {
    const field: FormField = { name: 'qty', type: 'number', label: 'Qty', min: 2, max: 5 };
    const high = await submitWith([field], (c) => {
      fireEvent.change(c.querySelector('#qty') as HTMLInputElement, { target: { value: '9' } });
    });
    await waitFor(() => expect(screen.getByText('Qty must be at most 5')).toBeInTheDocument());
    expect(high.onSubmit).not.toHaveBeenCalled();
  });

  it('shows the custom message for a required select left empty', async () => {
    const { onSubmit } = await submitWith([
      {
        name: 'color',
        type: 'select',
        label: 'Color',
        required: true,
        options: [
          { value: 'r', label: 'Red' },
          { value: 'g', label: 'Green' },
        ],
      },
    ]);
    await waitFor(() =>
      expect(screen.getByText('Color must be one of the available options')).toBeInTheDocument()
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows the custom message for an unchecked required checkbox', async () => {
    const { onSubmit } = await submitWith([
      { name: 'tos', type: 'checkbox', label: 'Terms', required: true },
    ]);
    await waitFor(() => expect(screen.getByText('Terms must be checked')).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('requires at least one selection for checkbox_multi', async () => {
    const { onSubmit } = await submitWith([
      {
        name: 'tags',
        type: 'checkbox_multi',
        label: 'Tags',
        required: true,
        options: [{ value: 'a', label: 'A' }],
      },
    ]);
    await waitFor(() =>
      expect(screen.getByText('Tags requires at least one selection')).toBeInTheDocument()
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('requires a non-empty value for required text', async () => {
    const { onSubmit } = await submitWith([
      { name: 'nick', type: 'text', label: 'Nick', required: true },
    ]);
    await waitFor(() => expect(screen.getByText('Nick is required')).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('allows empty optional email, url and number fields', async () => {
    const { onSubmit } = await submitWith([
      { name: 'mail', type: 'email', label: 'Mail' },
      { name: 'site', type: 'url', label: 'Site' },
      { name: 'qty', type: 'number', label: 'Qty' },
    ]);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it('applies a text pattern with its custom message', async () => {
    const { onSubmit } = await submitWith(
      [{ name: 'code', type: 'text', label: 'Code', pattern: '^[A-Z]+$' }],
      async (c) => {
        await userEvent.type(c.querySelector('#code') as HTMLInputElement, 'abc');
      }
    );
    await waitFor(() => expect(screen.getByText('Code format is invalid')).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('honours a custom zod 4 schema on a field', async () => {
    const { onSubmit } = await submitWith(
      [
        {
          name: 'handle',
          type: 'text',
          label: 'Handle',
          required: true,
          schema: z.string().min(4, { error: 'Handle too short' }),
        },
      ],
      async (c) => {
        await userEvent.type(c.querySelector('#handle') as HTMLInputElement, 'ab');
      }
    );
    await waitFor(() => expect(screen.getByText('Handle too short')).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
