import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  buildSAMLRequest,
  buildSAMLRedirectUrl,
  buildSAMLPostForm,
  initiateSAMLLogin,
  initiateSAMLPostLogin,
  validateRelayState,
  getStoredRequestId,
  clearSAMLSession,
} from './saml';
import type { SAMLProvider } from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function samlConfig(overrides?: Partial<SAMLProvider>): SAMLProvider {
  return {
    provider: 'saml',
    idpSsoUrl: 'https://idp.example.com/sso',
    entityId: 'https://sp.example.com',
    acsUrl: 'https://sp.example.com/acs',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// buildSAMLRequest
// ---------------------------------------------------------------------------

describe('buildSAMLRequest', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it('returns valid XML with AuthnRequest element', () => {
    const xml = buildSAMLRequest(samlConfig());
    expect(xml).toContain('<samlp:AuthnRequest');
    expect(xml).toContain('Version="2.0"');
  });

  it('embeds IdP SSO URL as Destination', () => {
    const xml = buildSAMLRequest(samlConfig());
    expect(xml).toContain('Destination="https://idp.example.com/sso"');
  });

  it('embeds ACS URL as AssertionConsumerServiceURL', () => {
    const xml = buildSAMLRequest(samlConfig());
    expect(xml).toContain('AssertionConsumerServiceURL="https://sp.example.com/acs"');
  });

  it('embeds entityId as Issuer', () => {
    const xml = buildSAMLRequest(samlConfig());
    expect(xml).toContain('<saml:Issuer>https://sp.example.com</saml:Issuer>');
  });

  it('generates a unique ID starting with underscore', () => {
    const xml = buildSAMLRequest(samlConfig());
    const idMatch = xml.match(/ID="_([0-9a-f]+)"/);
    expect(idMatch).not.toBeNull();
  });

  it('stores request ID in sessionStorage', () => {
    buildSAMLRequest(samlConfig());
    const stored = sessionStorage.getItem('saml_request_id');
    expect(stored).toBeTruthy();
    expect(stored).toMatch(/^_[0-9a-f]+$/);
  });

  it('includes IssueInstant with ISO timestamp', () => {
    const xml = buildSAMLRequest(samlConfig());
    expect(xml).toMatch(/IssueInstant="\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });

  it('includes HTTP-POST ProtocolBinding', () => {
    const xml = buildSAMLRequest(samlConfig());
    expect(xml).toContain('ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"');
  });
});

// ---------------------------------------------------------------------------
// buildSAMLRedirectUrl
// ---------------------------------------------------------------------------

describe('buildSAMLRedirectUrl', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it('returns a URL pointing to the IdP SSO URL', () => {
    const url = buildSAMLRedirectUrl(samlConfig());
    expect(url).toContain('https://idp.example.com/sso');
  });

  it('includes SAMLRequest query parameter', () => {
    const url = buildSAMLRedirectUrl(samlConfig());
    expect(new URL(url).searchParams.has('SAMLRequest')).toBe(true);
  });

  it('includes RelayState query parameter', () => {
    const url = buildSAMLRedirectUrl(samlConfig());
    expect(new URL(url).searchParams.has('RelayState')).toBe(true);
  });

  it('stores RelayState in sessionStorage for CSRF validation', () => {
    buildSAMLRedirectUrl(samlConfig());
    expect(sessionStorage.getItem('saml_relay_state')).toBeTruthy();
  });

  it('SAMLRequest is base64-encoded (no XML visible in raw param)', () => {
    const url = buildSAMLRedirectUrl(samlConfig());
    const raw = new URL(url).searchParams.get('SAMLRequest') ?? '';
    expect(raw).not.toContain('<samlp:AuthnRequest');
  });
});

// ---------------------------------------------------------------------------
// buildSAMLPostForm
// ---------------------------------------------------------------------------

describe('buildSAMLPostForm', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it('returns HTML with a form that POSTs to IdP SSO URL', () => {
    const html = buildSAMLPostForm(samlConfig());
    expect(html).toContain('<form method="POST" action="https://idp.example.com/sso"');
  });

  it('contains a hidden SAMLRequest input', () => {
    const html = buildSAMLPostForm(samlConfig());
    expect(html).toContain('name="SAMLRequest"');
  });

  it('contains a hidden RelayState input', () => {
    const html = buildSAMLPostForm(samlConfig());
    expect(html).toContain('name="RelayState"');
  });

  it('includes auto-submit onload handler', () => {
    const html = buildSAMLPostForm(samlConfig());
    expect(html).toContain('onload="document.forms[0].submit()"');
  });
});

// ---------------------------------------------------------------------------
// initiateSAMLLogin
// ---------------------------------------------------------------------------

describe('initiateSAMLLogin', () => {
  beforeEach(() => {
    sessionStorage.clear();
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it('sets window.location.href to the redirect URL', () => {
    initiateSAMLLogin(samlConfig());
    expect(window.location.href).toContain('https://idp.example.com/sso');
  });

  it('assigned URL includes SAMLRequest param', () => {
    initiateSAMLLogin(samlConfig());
    expect(window.location.href).toContain('SAMLRequest=');
  });
});

// ---------------------------------------------------------------------------
// initiateSAMLPostLogin
// ---------------------------------------------------------------------------

describe('initiateSAMLPostLogin', () => {
  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('calls window.open and writes form HTML', () => {
    const mockDoc = { write: vi.fn(), close: vi.fn() };
    const mockWindow = { document: mockDoc };
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(mockWindow as unknown as Window);

    initiateSAMLPostLogin(samlConfig());

    expect(openSpy).toHaveBeenCalledWith('', '_self');
    expect(mockDoc.write).toHaveBeenCalledWith(expect.stringContaining('<form method="POST"'));
    expect(mockDoc.close).toHaveBeenCalled();
  });

  it('throws when window.open returns null (popup blocked)', () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    expect(() => initiateSAMLPostLogin(samlConfig())).toThrow(
      'Failed to initiate SAML login - popup blocked'
    );
  });
});

// ---------------------------------------------------------------------------
// validateRelayState
// ---------------------------------------------------------------------------

describe('validateRelayState', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it('returns true when stored relay state matches', () => {
    sessionStorage.setItem('saml_relay_state', 'relay-xyz');
    expect(validateRelayState('relay-xyz')).toBe(true);
  });

  it('removes relay state from sessionStorage after success', () => {
    sessionStorage.setItem('saml_relay_state', 'relay-xyz');
    validateRelayState('relay-xyz');
    expect(sessionStorage.getItem('saml_relay_state')).toBeNull();
  });

  it('returns false when relay states do not match', () => {
    sessionStorage.setItem('saml_relay_state', 'relay-xyz');
    expect(validateRelayState('wrong-relay')).toBe(false);
  });

  it('returns false when no relay state is stored', () => {
    expect(validateRelayState('any-relay')).toBe(false);
  });

  it('does NOT remove relay state when validation fails', () => {
    sessionStorage.setItem('saml_relay_state', 'relay-xyz');
    validateRelayState('wrong');
    expect(sessionStorage.getItem('saml_relay_state')).toBe('relay-xyz');
  });
});

// ---------------------------------------------------------------------------
// getStoredRequestId
// ---------------------------------------------------------------------------

describe('getStoredRequestId', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it('returns stored request ID', () => {
    sessionStorage.setItem('saml_request_id', '_abc123');
    expect(getStoredRequestId()).toBe('_abc123');
  });

  it('returns null when nothing is stored', () => {
    expect(getStoredRequestId()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// clearSAMLSession
// ---------------------------------------------------------------------------

describe('clearSAMLSession', () => {
  it('removes saml_request_id and saml_relay_state from sessionStorage', () => {
    sessionStorage.setItem('saml_request_id', '_abc');
    sessionStorage.setItem('saml_relay_state', 'relay');
    clearSAMLSession();
    expect(sessionStorage.getItem('saml_request_id')).toBeNull();
    expect(sessionStorage.getItem('saml_relay_state')).toBeNull();
  });
});
