import { execFileSync } from 'node:child_process';

import path from 'node:path';
import { fileURLToPath } from 'node:url';

const localFilename =
  typeof __filename === 'undefined'
    ? fileURLToPath(import.meta.url)
    : __filename;
const localDirname =
  typeof __dirname === 'undefined' ? path.dirname(localFilename) : __dirname;

function getWorkspaceEnv() {
  try {
    const scriptPath = path.resolve(
      localDirname,
      '../../../../scripts/workspace_env.py'
    );
    const output = execFileSync('python3', [scriptPath, 'json'], {
      encoding: 'utf-8',
    });
    return JSON.parse(output);
  } catch (error) {
    console.error('Failed to load workspace env', error);
    return {};
  }
}

export const workspaceEnv = getWorkspaceEnv();

export const BACKEND_TEST_PORT = workspaceEnv.BACKEND_TEST_PORT || '8001';
export const OAUTH_PUBLIC_TEST_PORT =
  workspaceEnv.OAUTH_PUBLIC_TEST_PORT || '4446';
export const OAUTH_ADMIN_TEST_PORT =
  workspaceEnv.OAUTH_ADMIN_TEST_PORT || '4447';
export const OAUTH_UI_TEST_PORT = workspaceEnv.OAUTH_UI_TEST_PORT || '3002';
export const DB_TEST_PORT = workspaceEnv.DB_TEST_PORT || '5433';
export const MEILI_TEST_PORT = workspaceEnv.MEILI_TEST_PORT || '7701';
export const CONTAINER_PREFIX = workspaceEnv.CONTAINER_PREFIX || 'pms';

export const FRONTEND_TEST_URL =
  process.env.PLAYWRIGHT_FRONTEND_URL ??
  process.env.FRONTEND_URL ??
  `http://localhost:${workspaceEnv.FRONTEND_TEST_PORT || '3100'}`;

export const FRONTEND_TEST_PORT =
  new URL(FRONTEND_TEST_URL).port || workspaceEnv.FRONTEND_TEST_PORT || '3100';

export const FRONTEND_TEST_LOGIN_URL = new URL(
  '/auth/login',
  FRONTEND_TEST_URL
).toString();

export const FRONTEND_TEST_CALLBACK_URL = new URL(
  '/auth/callback',
  FRONTEND_TEST_URL
).toString();

export const BACKEND_TEST_URL = `http://localhost:${BACKEND_TEST_PORT}`;

/**
 * The MCP server's mount path and the OAuth callback FastMCP's proxy serves
 * under it. The Hydra client has to register this URI or the MCP OAuth flow is
 * rejected at the authorize step; docker/oauth-provider/init-oauth.sh builds
 * the same value from WEBHOOK_BASE_URL and MCP_MOUNT_PATH.
 */
export const MCP_TEST_MOUNT_PATH = '/mcp-server';

export const MCP_TEST_CALLBACK_URL = `${BACKEND_TEST_URL}${MCP_TEST_MOUNT_PATH}/auth/callback`;

export const SHOULD_REUSE_PLAYWRIGHT_WEB_SERVER =
  process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === 'true';

export function getFrontendCorsOrigins(
  frontendUrl = FRONTEND_TEST_URL
): string {
  const url = new URL(frontendUrl);
  const origins = [url.origin];

  if (url.hostname === 'localhost') {
    origins.push(`http://127.0.0.1:${url.port || FRONTEND_TEST_PORT}`);
  }

  origins.push('http://frontend:3000');

  return Array.from(new Set(origins)).join(',');
}
