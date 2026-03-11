import { describe, it, expect } from 'vitest';
import { createContext, useContext } from 'react';
import { renderHook } from '@testing-library/react';
import { createContextWrapper } from '../wrappers.js';

const TestContext = createContext<{ value: number }>({ value: 0 });

describe('createContextWrapper', () => {
  it('provides the given value to children', () => {
    const wrapper = createContextWrapper(TestContext, { value: 42 });
    const { result } = renderHook(() => useContext(TestContext), { wrapper });
    expect(result.current.value).toBe(42);
  });

  it('returns a React component', () => {
    const wrapper = createContextWrapper(TestContext, { value: 1 });
    expect(typeof wrapper).toBe('function');
  });

  it('allows different values for different wrapper instances', () => {
    const wrapperA = createContextWrapper(TestContext, { value: 10 });
    const wrapperB = createContextWrapper(TestContext, { value: 20 });

    const { result: resultA } = renderHook(() => useContext(TestContext), { wrapper: wrapperA });
    const { result: resultB } = renderHook(() => useContext(TestContext), { wrapper: wrapperB });

    expect(resultA.current.value).toBe(10);
    expect(resultB.current.value).toBe(20);
  });
});
