import { describe, it, expect } from 'vitest';
import * as ReactLibs from '../index';

describe('Package exports', () => {
  it('exports LoginPageBuilder component', () => {
    expect(ReactLibs.LoginPageBuilder).toBeDefined();
  });

  it('exports FormModalBuilder component', () => {
    expect(ReactLibs.FormModalBuilder).toBeDefined();
  });

  it('exports SidebarMenu component', () => {
    expect(ReactLibs.SidebarMenu).toBeDefined();
  });

  it('exports SidebarMenuTrigger component', () => {
    expect(ReactLibs.SidebarMenuTrigger).toBeDefined();
  });

  it('exports ConsoleVersion component', () => {
    expect(ReactLibs.ConsoleVersion).toBeDefined();
  });

  it('exports AppConsoleVersion component', () => {
    expect(ReactLibs.AppConsoleVersion).toBeDefined();
  });

  it('exports useFormBuilder hook', () => {
    expect(ReactLibs.useFormBuilder).toBeDefined();
  });

  it('exports useBreakpoint hook', () => {
    expect(ReactLibs.useBreakpoint).toBeDefined();
  });

  it('exports parseVersion utility', () => {
    expect(ReactLibs.parseVersion).toBeDefined();
  });

  it('exports logVersionToConsole utility', () => {
    expect(ReactLibs.logVersionToConsole).toBeDefined();
  });

  it('exports useVersionInfo hook', () => {
    expect(ReactLibs.useVersionInfo).toBeDefined();
  });

  it('exports useApiVersionInfo hook', () => {
    expect(ReactLibs.useApiVersionInfo).toBeDefined();
  });

  it('exports MFAModal component', () => {
    expect(ReactLibs.MFAModal).toBeDefined();
  });

  it('exports MFAInput component', () => {
    expect(ReactLibs.MFAInput).toBeDefined();
  });

  it('exports CaptchaWidget component', () => {
    expect(ReactLibs.CaptchaWidget).toBeDefined();
  });

  it('exports SocialLoginButtons component', () => {
    expect(ReactLibs.SocialLoginButtons).toBeDefined();
  });

  it('exports LoginDivider component', () => {
    expect(ReactLibs.LoginDivider).toBeDefined();
  });

  it('exports CookieConsent component', () => {
    expect(ReactLibs.CookieConsent).toBeDefined();
  });

  it('exports Footer component', () => {
    expect(ReactLibs.Footer).toBeDefined();
  });

  it('exports social login icons', () => {
    expect(ReactLibs.GoogleIcon).toBeDefined();
    expect(ReactLibs.GitHubIcon).toBeDefined();
    expect(ReactLibs.MicrosoftIcon).toBeDefined();
    expect(ReactLibs.AppleIcon).toBeDefined();
    expect(ReactLibs.TwitchIcon).toBeDefined();
    expect(ReactLibs.DiscordIcon).toBeDefined();
    expect(ReactLibs.SSOIcon).toBeDefined();
    expect(ReactLibs.EnterpriseIcon).toBeDefined();
  });

  it('exports useCaptcha hook', () => {
    expect(ReactLibs.useCaptcha).toBeDefined();
  });

  it('exports useCookieConsent hook', () => {
    expect(ReactLibs.useCookieConsent).toBeDefined();
  });

  it('exports ELDER_LOGIN_THEME', () => {
    expect(ReactLibs.ELDER_LOGIN_THEME).toBeDefined();
  });

  it('exports mergeWithElderTheme utility', () => {
    expect(ReactLibs.mergeWithElderTheme).toBeDefined();
  });
});
