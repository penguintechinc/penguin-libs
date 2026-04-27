/**
 * React Console Version Package
 *
 * Focused package containing ConsoleVersion component and utilities.
 */

export {
  ConsoleVersion,
  AppConsoleVersion,
  parseVersion,
  logVersionToConsole,
  useVersionInfo,
  useApiVersionInfo,
} from './ConsoleVersion';

export type {
  VersionInfo,
  ConsoleStyleConfig,
  ConsoleVersionProps,
  AppConsoleVersionProps,
  ApiStatusResponse,
} from './ConsoleVersion';
