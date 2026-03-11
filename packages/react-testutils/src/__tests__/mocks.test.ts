import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mockSessionStorage, mockLocalStorage } from '../mocks.js';
import type { StorageMock } from '../mocks.js';

describe('mockSessionStorage', () => {
  let mock: StorageMock;

  beforeEach(() => {
    mock = mockSessionStorage();
  });

  afterEach(() => {
    mock.restore();
  });

  it('setItem stores a value', () => {
    globalThis.sessionStorage.setItem('key', 'value');
    expect(mock.store['key']).toBe('value');
  });

  it('getItem retrieves a stored value', () => {
    mock.store['myKey'] = 'myValue';
    expect(globalThis.sessionStorage.getItem('myKey')).toBe('myValue');
  });

  it('getItem returns null for missing key', () => {
    expect(globalThis.sessionStorage.getItem('missing')).toBeNull();
  });

  it('removeItem deletes a value', () => {
    globalThis.sessionStorage.setItem('key', 'value');
    globalThis.sessionStorage.removeItem('key');
    expect(globalThis.sessionStorage.getItem('key')).toBeNull();
  });

  it('clear empties the store', () => {
    globalThis.sessionStorage.setItem('a', '1');
    globalThis.sessionStorage.setItem('b', '2');
    globalThis.sessionStorage.clear();
    expect(Object.keys(mock.store).length).toBe(0);
  });
});

describe('mockLocalStorage', () => {
  let mock: StorageMock;

  beforeEach(() => {
    mock = mockLocalStorage();
  });

  afterEach(() => {
    mock.restore();
  });

  it('setItem stores a value', () => {
    globalThis.localStorage.setItem('token', 'abc');
    expect(mock.store['token']).toBe('abc');
  });

  it('getItem retrieves a stored value', () => {
    mock.store['token'] = 'abc';
    expect(globalThis.localStorage.getItem('token')).toBe('abc');
  });

  it('clear empties the store', () => {
    globalThis.localStorage.setItem('x', '1');
    globalThis.localStorage.clear();
    expect(Object.keys(mock.store).length).toBe(0);
  });
});
