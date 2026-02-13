/**
 * Shared theme types used across all react-libs components.
 *
 * All components accept:
 *   themeMode?: ThemeMode  — 'dark' (default) or 'light'
 *   colors?: Partial<XColorConfig>  — custom overrides merged on top of the preset
 */

/** Theme mode preset selector */
export type ThemeMode = 'dark' | 'light';

/**
 * Merge a theme preset with optional partial overrides.
 * Generic so each component can use its own ColorConfig type.
 */
export function resolveTheme<T>(presets: Record<ThemeMode, T>, mode: ThemeMode = 'dark', overrides?: Partial<T>): T {
  const base = presets[mode];
  if (!overrides) return base;
  return { ...base, ...overrides };
}
