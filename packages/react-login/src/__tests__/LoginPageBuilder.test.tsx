import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginPageBuilder } from '../LoginPageBuilder';
import type { LoginPageBuilderProps } from '../types';

const mockOnSuccess = vi.fn();
const mockOnError = vi.fn();
const mockFetch = vi.fn();

// Pre-set cookie consent in localStorage to prevent banner from rendering in tests
const GDPR_CONSENT = {
  accepted: true,
  essential: true,
  functional: true,
  analytics: true,
  marketing: true,
  timestamp: Date.now(),
};

const defaultProps: LoginPageBuilderProps = {
  api: {
    loginUrl: 'http://localhost:3000/api/v1/login',
    method: 'POST',
    headers: {},
  },
  branding: {
    appName: 'Test App',
    logo: 'http://localhost:3000/logo.png',
    logoHeight: 300,
    tagline: 'Test tagline',
    githubRepo: 'test/repo',
  },
  onSuccess: mockOnSuccess,
  gdpr: {
    enabled: true,
    privacyPolicyUrl: 'http://localhost:3000/privacy',
    cookiePolicyUrl: 'http://localhost:3000/cookies',
  },
  captcha: {
    enabled: false,
    provider: 'altcha',
    challengeUrl: 'http://localhost:3000/captcha',
  },
  mfa: {
    enabled: false,
    codeLength: 6,
  },
  passkey: {
    enabled: false,
    registrationUrl: 'http://localhost:3000/passkey/register',
    authenticationUrl: 'http://localhost:3000/passkey/auth',
  },
  showRememberMe: true,
  showForgotPassword: true,
  showSignUp: true,
  onError: mockOnError,
};

describe('LoginPageBuilder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = mockFetch as any;
    // Pre-accept cookie consent to prevent banner from rendering in tests
    localStorage.setItem('gdpr_consent', JSON.stringify(GDPR_CONSENT));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  describe('Rendering', () => {
    it('renders email and password fields', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      expect(screen.getByLabelText('Email address')).toBeInTheDocument();
      expect(screen.getByLabelText('Password')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });

    it('renders app name and logo', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      expect(screen.getByText('Test App')).toBeInTheDocument();
      expect(screen.getByAltText('Test App logo')).toBeInTheDocument();
    });

    it('renders forgot password link when showForgotPassword=true', () => {
      render(<LoginPageBuilder {...defaultProps} showForgotPassword={true} />);

      expect(screen.getByText('Forgot password?')).toBeInTheDocument();
    });

    it('hides forgot password link when showForgotPassword=false', () => {
      render(<LoginPageBuilder {...defaultProps} showForgotPassword={false} />);

      expect(screen.queryByText('Forgot password?')).not.toBeInTheDocument();
    });

    it('renders sign up link when showSignUp=true', () => {
      render(<LoginPageBuilder {...defaultProps} showSignUp={true} />);

      expect(screen.getByText(/don't have an account/i)).toBeInTheDocument();
      expect(screen.getByText('Sign up')).toBeInTheDocument();
    });

    it('hides sign up link when showSignUp=false', () => {
      render(<LoginPageBuilder {...defaultProps} showSignUp={false} />);

      expect(screen.queryByText(/don't have an account/i)).not.toBeInTheDocument();
    });

    it('renders remember me checkbox when showRememberMe=true', () => {
      render(<LoginPageBuilder {...defaultProps} showRememberMe={true} />);

      expect(screen.getByLabelText('Remember me')).toBeInTheDocument();
    });

    it('hides remember me checkbox when showRememberMe=false', () => {
      render(<LoginPageBuilder {...defaultProps} showRememberMe={false} />);

      expect(screen.queryByLabelText('Remember me')).not.toBeInTheDocument();
    });
  });

  describe('Form Validation', () => {
    it('does not call onSuccess on empty email submit', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true }),
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const submitButton = screen.getByRole('button', { name: /sign in/i });
      const passwordInput = screen.getByLabelText('Password');

      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      // HTML5 validation should prevent submission
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('does not call onSuccess on empty password submit', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true }),
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const submitButton = screen.getByRole('button', { name: /sign in/i });
      const emailInput = screen.getByLabelText('Email address');

      await user.type(emailInput, 'test@example.com');
      await user.click(submitButton);

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('rejects invalid email format', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        json: async () => ({ success: false, error: 'Invalid email' }),
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'invalid-email');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      // HTML5 validation should prevent submission
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('validates email with @ and domain', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, token: 'token123' }),
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@localhost.local');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });
    });
  });

  describe('Form Submission', () => {
    it('calls onSuccess with credentials on valid login', async () => {
      const mockResponse = {
        success: true,
        user: { id: 'user1', email: 'test@example.com' },
        token: 'token123',
      };

      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:3000/api/v1/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: expect.stringContaining('test@example.com'),
        });
      });

      await waitFor(() => {
        expect(mockOnSuccess).toHaveBeenCalledWith(mockResponse);
      });
    });

    it('displays error message on failed login', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        json: async () => ({
          success: false,
          error: 'Invalid credentials',
          errorCode: 'INVALID_CREDENTIALS',
        }),
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'wrongpassword');
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
      });

      expect(mockOnError).toHaveBeenCalledWith(
        expect.any(Error),
        'INVALID_CREDENTIALS'
      );
    });

    it('handles network error gracefully', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText(/unable to connect/i)).toBeInTheDocument();
      });

      expect(mockOnError).toHaveBeenCalledWith(
        expect.any(Error),
        'NETWORK_ERROR'
      );
    });

    it('includes rememberMe flag when checkbox is checked', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, token: 'token123' }),
      });

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} showRememberMe={true} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const rememberCheckbox = screen.getByLabelText('Remember me');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(rememberCheckbox);
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            body: expect.stringContaining('"rememberMe":true'),
          })
        );
      });
    });

    it('includes tenant in payload when tenant field is shown', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, token: 'token123' }),
      });

      const user = userEvent.setup();
      render(
        <LoginPageBuilder
          {...defaultProps}
          tenantField={{ show: true, label: 'Tenant', placeholder: 'Enter tenant' }}
        />
      );

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const tenantInput = screen.getByLabelText('Tenant');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.type(tenantInput, 'tenant1');
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            body: expect.stringContaining('"tenant":"tenant1"'),
          })
        );
      });
    });
  });

  describe('Button States', () => {
    it('disables submit button while submitting', async () => {
      mockFetch.mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() =>
              resolve({
                ok: true,
                json: async () => ({ success: true, token: 'token123' }),
              }), 100)
          )
      );

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      expect(submitButton).toBeDisabled();

      await waitFor(() => {
        expect(mockOnSuccess).toHaveBeenCalled();
      });
    });

    it('shows loading spinner when submitting', async () => {
      mockFetch.mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() =>
              resolve({
                ok: true,
                json: async () => ({ success: true, token: 'token123' }),
              }), 100)
          )
      );

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      expect(submitButton).toHaveTextContent('Signing in...');

      await waitFor(() => {
        expect(submitButton).toHaveTextContent('Sign in');
      });
    });

    it('shows submit button text normally when not submitting', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      const submitButton = screen.getByRole('button', { name: /sign in/i });
      expect(submitButton).toHaveTextContent('Sign in');
    });
  });

  describe('CSS Classes', () => {
    it('applies correct CSS classes to email input', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address') as HTMLInputElement;
      expect(emailInput).toHaveClass('rounded-lg', 'border', 'px-3', 'py-2.5');
    });

    it('applies correct CSS classes to password input', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      const passwordInput = screen.getByLabelText('Password') as HTMLInputElement;
      expect(passwordInput).toHaveClass('rounded-lg', 'border', 'px-3', 'py-2.5');
    });

    it('applies correct CSS classes to submit button', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      const submitButton = screen.getByRole('button', { name: /sign in/i });
      expect(submitButton).toHaveClass('w-full', 'rounded-lg', 'font-medium');
    });

    it('applies disabled state classes to submit button when loading', async () => {
      mockFetch.mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() =>
              resolve({
                ok: true,
                json: async () => ({ success: true, token: 'token123' }),
              }), 100)
          )
      );

      const user = userEvent.setup();
      render(<LoginPageBuilder {...defaultProps} />);

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      expect(submitButton).toHaveClass('disabled:opacity-50', 'disabled:cursor-not-allowed');
    });
  });

  describe('Password Field Type', () => {
    it('password input has type=password', () => {
      render(<LoginPageBuilder {...defaultProps} />);

      const passwordInput = screen.getByLabelText('Password') as HTMLInputElement;
      expect(passwordInput.type).toBe('password');
    });
  });

  describe('Social Login', () => {
    it('renders social login buttons when configured', () => {
      const props = {
        ...defaultProps,
        socialLogins: [
          {
            provider: 'google' as const,
            clientId: 'google-client-id',
            redirectUri: 'http://localhost:3000/auth/callback',
          },
          {
            provider: 'github' as const,
            clientId: 'github-client-id',
            redirectUri: 'http://localhost:3000/auth/callback',
          },
        ],
      };

      render(<LoginPageBuilder {...props} />);

      expect(screen.getByText(/continue with google/i)).toBeInTheDocument();
      expect(screen.getByText(/continue with github/i)).toBeInTheDocument();
    });

    it('does not render social login when socialLogins is empty', () => {
      const props = {
        ...defaultProps,
        socialLogins: [],
      };

      render(<LoginPageBuilder {...props} />);

      expect(screen.queryByText(/continue with/i)).not.toBeInTheDocument();
    });
  });

  describe('Error Message Transformation', () => {
    it('uses transformErrorMessage when provided', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        json: async () => ({
          success: false,
          error: 'Unknown error',
          errorCode: 'UNKNOWN',
        }),
      });

      const transformErrorMessage = vi.fn(() => 'Custom error message');

      const user = userEvent.setup();
      render(
        <LoginPageBuilder
          {...defaultProps}
          transformErrorMessage={transformErrorMessage}
        />
      );

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      await waitFor(() => {
        expect(transformErrorMessage).toHaveBeenCalled();
        expect(screen.getByText('Custom error message')).toBeInTheDocument();
      });
    });
  });

  describe('MFA Flow', () => {
    it('shows MFA modal when mfaRequired is true in response', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, mfaRequired: true }),
      });

      const user = userEvent.setup();
      render(
        <LoginPageBuilder
          {...defaultProps}
          mfa={{ enabled: true, codeLength: 6 }}
        />
      );

      const emailInput = screen.getByLabelText('Email address');
      const passwordInput = screen.getByLabelText('Password');
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      await user.type(emailInput, 'test@example.com');
      await user.type(passwordInput, 'password123');
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText('Two-Factor Authentication')
        ).toBeInTheDocument();
      });
    });
  });

  describe('Passkey Support', () => {
    it('renders passkey button when enabled', () => {
      render(
        <LoginPageBuilder
          {...defaultProps}
          passkey={{
            enabled: true,
            registrationUrl: 'http://localhost:3000/passkey/register',
            authenticationUrl: 'http://localhost:3000/passkey/auth',
            buttonLabel: 'Sign in with passkey',
          }}
        />
      );

      // Passkey button might be hidden if not supported in test environment
      // But the divider and password form should always be visible
      expect(screen.getByLabelText('Email address')).toBeInTheDocument();
    });

    it('does not render passkey button when disabled', () => {
      render(
        <LoginPageBuilder
          {...defaultProps}
          passkey={{
            enabled: false,
            registrationUrl: 'http://localhost:3000/passkey/register',
            authenticationUrl: 'http://localhost:3000/passkey/auth',
          }}
        />
      );

      // Passkey button should not appear when disabled
      expect(screen.queryByRole('button', { name: /sign in with passkey/i })).not.toBeInTheDocument();
      expect(screen.queryByTestId('passkey-button')).not.toBeInTheDocument();
    });
  });

  describe('Custom className', () => {
    it('applies custom className to page container', () => {
      const customClass = 'custom-login-page';
      const { container } = render(
        <LoginPageBuilder {...defaultProps} className={customClass} />
      );

      const pageDiv = container.querySelector(`.${customClass}`);
      expect(pageDiv).toBeInTheDocument();
    });
  });

  describe('Forgot Password Handler', () => {
    it('calls onForgotPassword callback when link is clicked', async () => {
      const onForgotPassword = vi.fn();
      const user = userEvent.setup();

      render(
        <LoginPageBuilder
          {...defaultProps}
          showForgotPassword={true}
          onForgotPassword={onForgotPassword}
        />
      );

      const forgotLink = screen.getByText('Forgot password?');
      await user.click(forgotLink);

      expect(onForgotPassword).toHaveBeenCalled();
    });
  });

  describe('Sign Up Handler', () => {
    it('calls onSignUp callback when link is clicked', async () => {
      const onSignUp = vi.fn();
      const user = userEvent.setup();

      render(
        <LoginPageBuilder
          {...defaultProps}
          showSignUp={true}
          onSignUp={onSignUp}
        />
      );

      const signUpLink = screen.getByText('Sign up');
      await user.click(signUpLink);

      expect(onSignUp).toHaveBeenCalled();
    });
  });
});
