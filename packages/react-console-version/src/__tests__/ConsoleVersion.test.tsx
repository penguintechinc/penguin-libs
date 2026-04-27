import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import {
  ConsoleVersion,
  AppConsoleVersion,
  parseVersion,
  logVersionToConsole,
  useVersionInfo,
  useApiVersionInfo,
  VersionInfo,
} from '../ConsoleVersion';

// Helper for testing hooks - placed before it's used
function renderHook<T>(
  callback: (props?: any) => T,
  options?: { initialProps?: any }
) {
  let result = { current: null as T | null };

  function TestComponent({ props }: { props?: any }) {
    result.current = callback(props);
    return null;
  }

  const { rerender: rtlRerender } = render(
    <TestComponent props={options?.initialProps} />
  );

  return {
    result,
    rerender: (props?: any) => {
      rtlRerender(<TestComponent props={props} />);
    },
  };
}

describe('parseVersion', () => {
  it('parses full version string with build epoch', () => {
    const version = '1.2.3.1737727200';
    const result = parseVersion(version);
    expect(result.major).toBe(1);
    expect(result.minor).toBe(2);
    expect(result.patch).toBe(3);
    expect(result.buildEpoch).toBe(1737727200);
  });

  it('parses version without build epoch', () => {
    const version = '2.0.1';
    const result = parseVersion(version);
    expect(result.major).toBe(2);
    expect(result.minor).toBe(0);
    expect(result.patch).toBe(1);
    expect(result.buildEpoch).toBe(0);
  });

  it('handles version with v prefix', () => {
    const version = 'v1.2.3.1737727200';
    const result = parseVersion(version);
    expect(result.major).toBe(1);
    expect(result.minor).toBe(2);
    expect(result.patch).toBe(3);
    expect(result.semver).toBe('1.2.3');
  });

  it('generates correct semver string', () => {
    const version = '3.4.5.1737727200';
    const result = parseVersion(version);
    expect(result.semver).toBe('3.4.5');
  });

  it('generates correct full version string', () => {
    const version = '1.0.0.1737727200';
    const result = parseVersion(version);
    expect(result.full).toBe('1.0.0.1737727200');
  });

  it('generates full version without epoch when epoch is 0', () => {
    const version = '1.0.0.0';
    const result = parseVersion(version);
    expect(result.full).toBe('1.0.0');
  });

  it('uses buildEpoch override when provided', () => {
    const version = '1.0.0.100';
    const result = parseVersion(version, 1737727200);
    expect(result.buildEpoch).toBe(1737727200);
  });

  it('generates correct buildDate from epoch', () => {
    const version = '1.0.0.1737727200';
    const result = parseVersion(version);
    expect(result.buildDate).toContain('2025');
    expect(result.buildDate).toContain('UTC');
  });

  it('returns "Unknown" for buildDate when epoch is 0', () => {
    const version = '1.0.0.0';
    const result = parseVersion(version);
    expect(result.buildDate).toBe('Unknown');
  });

  it('handles missing version parts with defaults', () => {
    const version = '1';
    const result = parseVersion(version);
    expect(result.major).toBe(1);
    expect(result.minor).toBe(0);
    expect(result.patch).toBe(0);
  });

  it('handles empty version string', () => {
    const version = '';
    const result = parseVersion(version);
    expect(result.major).toBe(0);
    expect(result.minor).toBe(0);
    expect(result.patch).toBe(0);
    expect(result.semver).toBe('0.0.0');
  });
});

describe('logVersionToConsole', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('logs version to console', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo);

    expect(consoleSpy).toHaveBeenCalled();
    const callsWithVersion = consoleSpy.mock.calls.filter(
      (call) => call[0] && call[0].toString().includes('Version:')
    );
    expect(callsWithVersion.length).toBeGreaterThan(0);
    consoleSpy.mockRestore();
  });

  it('logs banner when showBanner is true', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, { showBanner: true });

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('skips banner when showBanner is false', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, { showBanner: false });

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('uses elder banner style by default', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, { bannerStyle: 'elder' });

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('uses box banner style when specified', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, { bannerStyle: 'box' });

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('includes environment in log when provided', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, { environment: 'production' });

    expect(consoleSpy).toHaveBeenCalled();
    const callsWithEnv = consoleSpy.mock.calls.filter(
      (call) => call[0] && call[0].toString().includes('Environment:')
    );
    expect(callsWithEnv.length).toBeGreaterThan(0);
    consoleSpy.mockRestore();
  });

  it('includes metadata in log when provided', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, {
      metadata: { 'API URL': 'https://api.example.com' },
    });

    expect(consoleSpy).toHaveBeenCalled();
    const callsWithMetadata = consoleSpy.mock.calls.filter(
      (call) => call[0] && call[0].toString().includes('API URL:')
    );
    expect(callsWithMetadata.length).toBeGreaterThan(0);
    consoleSpy.mockRestore();
  });

  it('uses custom emoji when provided', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    logVersionToConsole('TestApp', versionInfo, { emoji: '🎉', bannerStyle: 'elder' });

    expect(consoleSpy).toHaveBeenCalled();
    const callsWithEmoji = consoleSpy.mock.calls.filter(
      (call) => call[0] && call[0].toString().includes('🎉')
    );
    expect(callsWithEmoji.length).toBeGreaterThan(0);
    consoleSpy.mockRestore();
  });

  it('applies custom style config', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const versionInfo: VersionInfo = {
      full: '1.0.0.1737727200',
      major: 1,
      minor: 0,
      patch: 0,
      buildEpoch: 1737727200,
      buildDate: '2025-01-24 12:00:00 UTC',
      semver: '1.0.0',
    };

    const styleConfig = {
      primaryColor: '#ff0000',
      secondaryColor: '#00ff00',
    };

    logVersionToConsole('TestApp', versionInfo, { styleConfig });

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

describe('ConsoleVersion Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders without crashing', () => {
    const { container } = render(
      <ConsoleVersion appName="TestApp" version="1.0.0.1737727200" />
    );
    expect(container).toBeInTheDocument();
  });

  it('logs version to console on mount', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion appName="TestApp" version="1.0.0.1737727200" />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('does not log when logOnMount is false', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        logOnMount={false}
      />
    );
    expect(consoleSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('renders children when provided', () => {
    const { container } = render(
      <ConsoleVersion appName="TestApp" version="1.0.0.1737727200">
        <div data-testid="child">Child Content</div>
      </ConsoleVersion>
    );
    expect(container.querySelector('[data-testid="child"]')).toBeInTheDocument();
  });

  it('renders null when no children and not in a container', () => {
    const { container } = render(
      <ConsoleVersion appName="TestApp" version="1.0.0.1737727200" />
    );
    expect(container.firstChild).toBeFalsy();
  });

  it('calls onLog callback with version info', () => {
    const onLog = vi.fn();
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        onLog={onLog}
      />
    );
    expect(onLog).toHaveBeenCalled();
    expect(onLog.mock.calls[0][0].semver).toBe('1.0.0');
  });

  it('passes environment to console log', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        environment="staging"
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('uses custom style config', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        styleConfig={{ primaryColor: '#ff0000' }}
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('respects banner style prop', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        bannerStyle="box"
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('uses custom emoji', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        emoji="🎉"
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('includes metadata in console output', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.1737727200"
        metadata={{ 'API URL': 'https://api.example.com' }}
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('handles version string without build epoch', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <ConsoleVersion appName="TestApp" version="1.0.0" />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('re-logs when version prop changes', () => {
    const onLog = vi.fn();
    const { rerender } = render(
      <ConsoleVersion appName="TestApp" version="1.0.0.1737727200" onLog={onLog} />
    );
    expect(onLog).toHaveBeenCalledTimes(1);
    rerender(
      <ConsoleVersion appName="TestApp" version="2.0.0.1737727200" onLog={onLog} />
    );
    expect(onLog).toHaveBeenCalledTimes(2);
    expect(onLog.mock.calls[1][0].semver).toBe('2.0.0');
  });

  it('uses buildEpoch override when provided', () => {
    const onLog = vi.fn();
    render(
      <ConsoleVersion
        appName="TestApp"
        version="1.0.0.999"
        buildEpoch={1737727200}
        onLog={onLog}
      />
    );
    expect(onLog).toHaveBeenCalled();
    expect(onLog.mock.calls[0][0].buildEpoch).toBe(1737727200);
  });
});

describe('useVersionInfo Hook', () => {
  it('returns parsed version info', () => {
    const { result } = renderHook(() =>
      useVersionInfo('1.2.3.1737727200')
    );
    expect(result.current.major).toBe(1);
    expect(result.current.minor).toBe(2);
    expect(result.current.patch).toBe(3);
    expect(result.current.semver).toBe('1.2.3');
  });

  it('memoizes result when version does not change', () => {
    const { result, rerender } = renderHook(
      ({ version }) => useVersionInfo(version),
      { initialProps: { version: '1.0.0.1737727200' } }
    );
    const firstResult = result.current;
    rerender({ version: '1.0.0.1737727200' });
    expect(result.current).toBe(firstResult);
  });

  it('updates result when version changes', () => {
    const { result, rerender } = renderHook(
      ({ version }) => useVersionInfo(version),
      { initialProps: { version: '1.0.0.1737727200' } }
    );
    rerender({ version: '2.0.0.1737727200' });
    expect(result.current.major).toBe(2);
  });

  it('uses buildEpoch override', () => {
    const { result } = renderHook(() =>
      useVersionInfo('1.0.0.999', 1737727200)
    );
    expect(result.current.buildEpoch).toBe(1737727200);
  });
});

describe('AppConsoleVersion Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders without crashing', () => {
    const { container } = render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('logs WebUI version on mount', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    const callsWithWebUI = consoleSpy.mock.calls.filter(
      (call) => call[0] && call[0].toString().includes('WebUI')
    );
    expect(callsWithWebUI.length).toBeGreaterThan(0);
    consoleSpy.mockRestore();
  });

  it('calls onWebuiLog callback with version info', () => {
    const onWebuiLog = vi.fn();
    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        onWebuiLog={onWebuiLog}
      />
    );
    expect(onWebuiLog).toHaveBeenCalled();
    expect(onWebuiLog.mock.calls[0][0].semver).toBe('1.0.0');
  });

  it('fetches and logs API version', async () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: '1.5.0.1737727200' }),
    });
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        apiStatusUrl="/api/v1/status"
      />
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/status');
    consoleSpy.mockRestore();
  });

  it('calls onApiLog callback when API version fetched', async () => {
    const onApiLog = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: '1.5.0.1737727200' }),
    });
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        onApiLog={onApiLog}
      />
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(onApiLog).toHaveBeenCalled();
  });

  it('calls onApiError when API fetch fails', async () => {
    const onApiError = vi.fn();
    const fetchMock = vi.fn().mockRejectedValue(new Error('Network error'));
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        onApiError={onApiError}
      />
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(onApiError).toHaveBeenCalled();
  });

  it('uses custom API status URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: '1.5.0.1737727200' }),
    });
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        apiStatusUrl="/api/v2/health"
      />
    );

    await new Promise(resolve => setTimeout(resolve, 50));
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/health');
  });

  it('renders children when provided', () => {
    const { container } = render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
      >
        <div data-testid="app-child">App Content</div>
      </AppConsoleVersion>
    );
    expect(container.querySelector('[data-testid="app-child"]')).toBeInTheDocument();
  });

  it('passes environment to WebUI console log', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        environment="production"
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('uses custom emojis for WebUI and API', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: '1.5.0.1737727200' }),
    });
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        webuiEmoji="🎨"
        apiEmoji="⚡"
      />
    );

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('includes metadata in WebUI log', () => {
    const consoleSpy = vi.spyOn(console, 'log');
    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        metadata={{ 'Build': 'webpack' }}
      />
    );
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('handles API response without version field', async () => {
    const onApiError = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ build_epoch: 1737727200 }),
    });
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        onApiError={onApiError}
      />
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(fetchMock).toHaveBeenCalled();
  });

  it('handles API response with non-ok status', async () => {
    const onApiError = vi.fn();
    const consoleSpy = vi.spyOn(console, 'warn');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
    });
    global.fetch = fetchMock;

    render(
      <AppConsoleVersion
        appName="TestApp"
        webuiVersion="1.0.0.1737727200"
        onApiError={onApiError}
      />
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(onApiError).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

describe('useApiVersionInfo Hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns initial loading state', () => {
    const fetchMock = vi.fn().mockImplementation(() => new Promise(() => {}));
    global.fetch = fetchMock;

    const { result } = renderHook(() =>
      useApiVersionInfo('/api/v1/status')
    );

    expect(result.current.loading).toBe(true);
    expect(result.current.apiVersion).toBe(null);
    expect(result.current.error).toBe(null);
  });

  it('fetches and parses API version', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: '1.5.0.1737727200' }),
    });
    global.fetch = fetchMock;

    const { result } = renderHook(() =>
      useApiVersionInfo('/api/v1/status')
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(result.current.apiVersion?.semver).toBe('1.5.0');
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('handles fetch error', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('Network error'));
    global.fetch = fetchMock;

    const { result } = renderHook(() =>
      useApiVersionInfo('/api/v1/status')
    );

    await new Promise(resolve => setTimeout(resolve, 50));

    expect(result.current.apiVersion).toBe(null);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it('refetches when URL changes', () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: '1.0.0.1737727200' }),
    });
    global.fetch = fetchMock;

    const { rerender } = renderHook(
      ({ url }) => useApiVersionInfo(url),
      { initialProps: { url: '/api/v1/status' } }
    );

    rerender({ url: '/api/v2/status' });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
