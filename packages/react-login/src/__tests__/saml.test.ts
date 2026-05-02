import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  buildSAMLRequest,
  buildSAMLRedirectUrl,
  buildSAMLPostForm,
  initiateSAMLLogin,
  initiateSAMLPostLogin,
  validateRelayState,
  getStoredRequestId,
  clearSAMLSession,
} from '../utils/saml';
import type { SAMLProvider } from '../types';

const mockSAMLConfig: SAMLProvider = {
  provider: 'saml',
  idpSsoUrl: 'https://idp.example.com/sso',
  entityId: 'urn:app:entity:id',
  acsUrl: 'http://localhost:3000/auth/saml/acs',
  certificate: 'MIIDXTCCAkWgAwIBAgI...',
};

describe('SAML Utils', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  describe('buildSAMLRequest', () => {
    it('generates valid SAML AuthnRequest XML', () => {
      const xml = buildSAMLRequest(mockSAMLConfig);

      expect(xml).toMatch(/^<\?xml version="1\.0"/);
      expect(xml).toContain('samlp:AuthnRequest');
      expect(xml).toContain(mockSAMLConfig.idpSsoUrl);
      expect(xml).toContain(mockSAMLConfig.acsUrl);
      expect(xml).toContain(mockSAMLConfig.entityId);
    });

    it('includes Version and IssueInstant attributes', () => {
      const xml = buildSAMLRequest(mockSAMLConfig);

      expect(xml).toContain('Version="2.0"');
      expect(xml).toContain('IssueInstant=');
    });

    it('includes RequestID in SAML request', () => {
      const xml = buildSAMLRequest(mockSAMLConfig);

      expect(xml).toContain('ID="_');
    });

    it('includes NameIDPolicy with email format', () => {
      const xml = buildSAMLRequest(mockSAMLConfig);

      expect(xml).toContain('samlp:NameIDPolicy');
      expect(xml).toContain('emailAddress');
      expect(xml).toContain('AllowCreate="true"');
    });

    it('stores request ID in sessionStorage', () => {
      buildSAMLRequest(mockSAMLConfig);

      expect(sessionStorage.getItem('saml_request_id')).not.toBeNull();
      expect(sessionStorage.getItem('saml_request_id')).toMatch(/^_[0-9a-f]{32}$/);
    });

    it('generates unique request IDs', () => {
      const xml1 = buildSAMLRequest(mockSAMLConfig);
      const xml2 = buildSAMLRequest(mockSAMLConfig);

      const id1 = xml1.match(/ID="(_[0-9a-f]+)"/)?.[1];
      const id2 = xml2.match(/ID="(_[0-9a-f]+)"/)?.[1];

      expect(id1).not.toBe(id2);
    });
  });

  describe('buildSAMLRedirectUrl', () => {
    it('builds SAML redirect URL', () => {
      const url = buildSAMLRedirectUrl(mockSAMLConfig);

      expect(url).toContain(mockSAMLConfig.idpSsoUrl);
      expect(url).toContain('SAMLRequest=');
      expect(url).toContain('RelayState=');
    });

    it('URL-encodes SAMLRequest parameter', () => {
      const url = buildSAMLRedirectUrl(mockSAMLConfig);
      const urlObj = new URL(url);

      const samlRequest = urlObj.searchParams.get('SAMLRequest');
      expect(samlRequest).not.toBeNull();
      // Base64 encoded (may include +, /, = for padding)
      expect(samlRequest).toMatch(/^[A-Za-z0-9+/=]+$/);
    });

    it('stores relay state in sessionStorage', () => {
      buildSAMLRedirectUrl(mockSAMLConfig);

      expect(sessionStorage.getItem('saml_relay_state')).not.toBeNull();
      expect(sessionStorage.getItem('saml_relay_state')).toMatch(/^_[0-9a-f]{32}$/);
    });

    it('returns valid URL object', () => {
      const url = buildSAMLRedirectUrl(mockSAMLConfig);

      expect(() => new URL(url)).not.toThrow();
    });

    it('includes both SAMLRequest and RelayState parameters', () => {
      const url = buildSAMLRedirectUrl(mockSAMLConfig);
      const urlObj = new URL(url);

      expect(urlObj.searchParams.has('SAMLRequest')).toBe(true);
      expect(urlObj.searchParams.has('RelayState')).toBe(true);
    });
  });

  describe('buildSAMLPostForm', () => {
    it('generates HTML form for POST binding', () => {
      const html = buildSAMLPostForm(mockSAMLConfig);

      expect(html).toContain('<form');
      expect(html).toContain(`action="${mockSAMLConfig.idpSsoUrl}"`);
      expect(html).toContain('method="POST"');
      expect(html).toContain('</form>');
    });

    it('includes SAMLRequest as hidden input', () => {
      const html = buildSAMLPostForm(mockSAMLConfig);

      expect(html).toContain('name="SAMLRequest"');
      expect(html).toContain('type="hidden"');
    });

    it('includes RelayState as hidden input', () => {
      const html = buildSAMLPostForm(mockSAMLConfig);

      expect(html).toContain('name="RelayState"');
      expect(html).toContain('type="hidden"');
    });

    it('includes auto-submit JavaScript', () => {
      const html = buildSAMLPostForm(mockSAMLConfig);

      expect(html).toContain('onload="document.forms[0].submit()"');
    });

    it('includes noscript fallback', () => {
      const html = buildSAMLPostForm(mockSAMLConfig);

      expect(html).toContain('<noscript>');
      expect(html).toContain('JavaScript is disabled');
      expect(html).toContain('</noscript>');
    });

    it('stores relay state in sessionStorage', () => {
      buildSAMLPostForm(mockSAMLConfig);

      expect(sessionStorage.getItem('saml_relay_state')).not.toBeNull();
    });

    it('SAMLRequest value is base64url encoded', () => {
      const html = buildSAMLPostForm(mockSAMLConfig);

      const samlRequestMatch = html.match(/value="([^"]+)"/);
      const samlValue = samlRequestMatch?.[1];

      expect(samlValue).toMatch(/^[A-Za-z0-9+/=]+$/); // Base64 encoded
    });
  });

  describe('initiateSAMLLogin', () => {
    it('sets window.location.href to redirect URL', () => {
      const originalLocation = window.location;
      delete (window as any).location;
      window.location = { href: '' } as any;

      initiateSAMLLogin(mockSAMLConfig);

      expect(window.location.href).toContain(mockSAMLConfig.idpSsoUrl);

      window.location = originalLocation;
    });
  });

  describe('initiateSAMLPostLogin', () => {
    it('opens a new window with auto-submitting form', () => {
      const openSpy = vi.spyOn(window, 'open').mockReturnValue({
        document: {
          write: vi.fn(),
          close: vi.fn(),
        },
      } as any);

      initiateSAMLPostLogin(mockSAMLConfig);

      expect(openSpy).toHaveBeenCalledWith('', '_self');

      openSpy.mockRestore();
    });

    it('writes SAML form to popup window', () => {
      const writeSpy = vi.fn();
      const closeSpy = vi.fn();

      vi.spyOn(window, 'open').mockReturnValue({
        document: {
          write: writeSpy,
          close: closeSpy,
        },
      } as any);

      initiateSAMLPostLogin(mockSAMLConfig);

      expect(writeSpy).toHaveBeenCalled();
      const written = writeSpy.mock.calls[0][0];
      expect(written).toContain('<form');
      expect(written).toContain('method="POST"');
    });

    it('closes popup document after writing', () => {
      const closeSpy = vi.fn();

      vi.spyOn(window, 'open').mockReturnValue({
        document: {
          write: vi.fn(),
          close: closeSpy,
        },
      } as any);

      initiateSAMLPostLogin(mockSAMLConfig);

      expect(closeSpy).toHaveBeenCalled();
    });

    it('throws error if popup is blocked', () => {
      vi.spyOn(window, 'open').mockReturnValue(null);

      expect(() => initiateSAMLPostLogin(mockSAMLConfig)).toThrow(
        /popup blocked/i
      );
    });
  });

  describe('validateRelayState', () => {
    it('validates matching relay state', () => {
      const relayState = '_0123456789abcdef0123456789abcdef';
      sessionStorage.setItem('saml_relay_state', relayState);

      const isValid = validateRelayState(relayState);

      expect(isValid).toBe(true);
    });

    it('clears relay state after successful validation', () => {
      const relayState = '_0123456789abcdef0123456789abcdef';
      sessionStorage.setItem('saml_relay_state', relayState);

      validateRelayState(relayState);

      expect(sessionStorage.getItem('saml_relay_state')).toBeNull();
    });

    it('rejects mismatched relay state', () => {
      sessionStorage.setItem('saml_relay_state', 'stored-state');

      const isValid = validateRelayState('different-state');

      expect(isValid).toBe(false);
    });

    it('rejects validation when relay state not stored', () => {
      const isValid = validateRelayState('any-state');

      expect(isValid).toBe(false);
    });

    it('does not clear relay state on failed validation', () => {
      sessionStorage.setItem('saml_relay_state', 'stored-state');

      validateRelayState('different-state');

      expect(sessionStorage.getItem('saml_relay_state')).toBe('stored-state');
    });
  });

  describe('getStoredRequestId', () => {
    it('returns stored request ID', () => {
      const requestId = '_0123456789abcdef0123456789abcdef';
      sessionStorage.setItem('saml_request_id', requestId);

      const stored = getStoredRequestId();

      expect(stored).toBe(requestId);
    });

    it('returns null when no request ID stored', () => {
      const stored = getStoredRequestId();

      expect(stored).toBeNull();
    });
  });

  describe('clearSAMLSession', () => {
    it('clears request ID from sessionStorage', () => {
      sessionStorage.setItem('saml_request_id', '_abc123');
      sessionStorage.setItem('saml_relay_state', '_def456');

      clearSAMLSession();

      expect(sessionStorage.getItem('saml_request_id')).toBeNull();
    });

    it('clears relay state from sessionStorage', () => {
      sessionStorage.setItem('saml_request_id', '_abc123');
      sessionStorage.setItem('saml_relay_state', '_def456');

      clearSAMLSession();

      expect(sessionStorage.getItem('saml_relay_state')).toBeNull();
    });

    it('clears both request ID and relay state', () => {
      sessionStorage.setItem('saml_request_id', '_abc123');
      sessionStorage.setItem('saml_relay_state', '_def456');

      clearSAMLSession();

      expect(sessionStorage.length).toBe(0);
    });
  });

  describe('SAML flow integration', () => {
    it('SAML request ID and relay state match between request and validation', () => {
      const xml = buildSAMLRequest(mockSAMLConfig);
      const requestId = getStoredRequestId();

      // Request ID should be stored and retrievable
      expect(requestId).not.toBeNull();
      expect(xml).toContain(requestId!);
    });

    it('complete SAML flow stores and validates state', () => {
      const url = buildSAMLRedirectUrl(mockSAMLConfig);
      const urlObj = new URL(url);
      const relayState = urlObj.searchParams.get('RelayState');

      expect(relayState).not.toBeNull();

      // Should validate successfully
      const isValid = validateRelayState(relayState!);
      expect(isValid).toBe(true);

      // Should be cleared after validation
      expect(sessionStorage.getItem('saml_relay_state')).toBeNull();
    });
  });
});
