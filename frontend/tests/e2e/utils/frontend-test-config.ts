const DEFAULT_FRONTEND_TEST_PORT = '3100';

export const FRONTEND_TEST_URL =
  process.env.PLAYWRIGHT_FRONTEND_URL ??
  process.env.FRONTEND_URL ??
  `http://localhost:${DEFAULT_FRONTEND_TEST_PORT}`;

export const FRONTEND_TEST_PORT =
  new URL(FRONTEND_TEST_URL).port || DEFAULT_FRONTEND_TEST_PORT;

export const FRONTEND_TEST_LOGIN_URL = new URL(
  '/auth/login',
  FRONTEND_TEST_URL
).toString();

export const FRONTEND_TEST_CALLBACK_URL = new URL(
  '/auth/callback',
  FRONTEND_TEST_URL
).toString();

export const SHOULD_REUSE_PLAYWRIGHT_WEB_SERVER =
  process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === 'true';

export function getFrontendCorsOrigins(
  frontendUrl = FRONTEND_TEST_URL
): string {
  const url = new URL(frontendUrl);
  const origins = [url.origin];

  if (url.hostname === 'localhost') {
    origins.push(`http://127.0.0.1:${url.port || DEFAULT_FRONTEND_TEST_PORT}`);
  }

  origins.push('http://frontend:3000');

  return Array.from(new Set(origins)).join(',');
}
