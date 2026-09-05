import { runGlobalSetup } from '../../../tests/global-setup';
import {
  FRONTEND_TEST_CALLBACK_URL,
  FRONTEND_TEST_PORT,
  FRONTEND_TEST_URL,
  getFrontendCorsOrigins,
  workspaceEnv,
  BACKEND_TEST_PORT,
  BACKEND_TEST_URL,
  MCP_TEST_CALLBACK_URL,
  MCP_TEST_MOUNT_PATH,
  OAUTH_ADMIN_TEST_PORT,
  OAUTH_UI_TEST_PORT,
  MEILI_TEST_PORT,
} from '../../../tests/e2e/utils/frontend-test-config';

describe('runGlobalSetup', () => {
  const testEnv: NodeJS.ProcessEnv = { NODE_ENV: 'test' };
  const waitForService = jest.fn<Promise<void>, [string]>();
  const getDockerComposeCommand = jest.fn(() => 'docker compose');
  const areServicesRunning = jest.fn<boolean, [string, string]>();
  const removeExistingContainers = jest.fn();
  const execCommand = jest.fn<
    void,
    [
      string,
      string,
      string,
      { env?: NodeJS.ProcessEnv; ignoreError?: boolean }?,
    ]
  >();
  const printServiceLogs = jest.fn();
  const hasExpectedBackendConfig = jest.fn<boolean, [string, string]>();
  const hasExpectedOAuthClientRedirect = jest.fn<
    Promise<boolean>,
    [string[]]
  >();
  const chdir = jest.fn();
  const logger = { log: jest.fn(), error: jest.fn() };
  const oauthUiPort = workspaceEnv.OAUTH_UI_TEST_PORT || '3002';
  const oauthPublicPort = workspaceEnv.OAUTH_PUBLIC_TEST_PORT || '4446';
  const expectedDockerEnv: NodeJS.ProcessEnv = {
    ...testEnv,
    ...workspaceEnv,
    OAUTH_CONSENT_URL: `http://localhost:${oauthUiPort}/consent`,
    OAUTH_LOGIN_URL: `http://localhost:${oauthUiPort}/login`,
    OAUTH_UI_PORT: oauthUiPort,
    OAUTH_AUTHORIZATION_URL: `http://localhost:${oauthPublicPort}/oauth2/auth`,
    OAUTH_ISSUER: `http://localhost:${oauthPublicPort}`,
    OAUTH_PUBLIC_URL: `http://localhost:${oauthPublicPort}`,
    FRONTEND_URL: FRONTEND_TEST_URL,
    FRONTEND_PORT: FRONTEND_TEST_PORT,
    CORS_ORIGINS: getFrontendCorsOrigins(),
    WEBHOOK_BASE_URL: BACKEND_TEST_URL,
    MCP_MOUNT_PATH: MCP_TEST_MOUNT_PATH,
  };

  beforeEach(() => {
    jest.clearAllMocks();
    waitForService.mockResolvedValue(undefined);
    hasExpectedBackendConfig.mockReturnValue(true);
    hasExpectedOAuthClientRedirect.mockResolvedValue(true);
  });

  it('skips docker commands when reusing already-running local services', async () => {
    areServicesRunning.mockReturnValue(true);

    await runGlobalSetup({
      env: testEnv,
      cwd: () => '/workspace/frontend',
      chdir,
      logger,
      waitForService,
      getDockerComposeCommand,
      areServicesRunning,
      removeExistingContainers,
      execCommand,
      printServiceLogs,
      hasExpectedBackendConfig,
      hasExpectedOAuthClientRedirect,
    });

    expect(chdir).toHaveBeenCalledWith('/workspace');
    expect(removeExistingContainers).not.toHaveBeenCalled();
    expect(execCommand).not.toHaveBeenCalled();
    expect(waitForService).toHaveBeenNthCalledWith(
      1,
      `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      2,
      `http://localhost:${OAUTH_ADMIN_TEST_PORT}/health/ready`
    );
    // Hydra redirects the browser to the login-consent UI, so a healthy Hydra
    // alone is not enough for auth.setup to complete.
    expect(waitForService).toHaveBeenNthCalledWith(
      3,
      `http://localhost:${OAUTH_UI_TEST_PORT}/health`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      4,
      `http://localhost:${MEILI_TEST_PORT}/health`
    );
  });

  it('starts services when not already running', async () => {
    areServicesRunning.mockReturnValue(false);

    await runGlobalSetup({
      env: testEnv,
      cwd: () => '/workspace/frontend',
      chdir,
      logger,
      waitForService,
      getDockerComposeCommand,
      areServicesRunning,
      removeExistingContainers,
      execCommand,
      printServiceLogs,
      hasExpectedBackendConfig,
      hasExpectedOAuthClientRedirect,
    });

    expect(removeExistingContainers).toHaveBeenCalledTimes(1);
    expect(execCommand).toHaveBeenCalledTimes(2);
    expect(execCommand).toHaveBeenNthCalledWith(
      1,
      'docker compose --profile test --env-file .env.test down --remove-orphans',
      'Cleaning up existing containers',
      '/workspace',
      { env: expectedDockerEnv }
    );
    expect(execCommand).toHaveBeenNthCalledWith(
      2,
      'docker compose --profile test --env-file .env.test up -d --build',
      'Starting Docker services',
      '/workspace',
      { env: expectedDockerEnv, ignoreError: true }
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      1,
      `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      2,
      `http://localhost:${OAUTH_ADMIN_TEST_PORT}/health/ready`
    );
    // Hydra redirects the browser to the login-consent UI, so a healthy Hydra
    // alone is not enough for auth.setup to complete.
    expect(waitForService).toHaveBeenNthCalledWith(
      3,
      `http://localhost:${OAUTH_UI_TEST_PORT}/health`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      4,
      `http://localhost:${MEILI_TEST_PORT}/health`
    );
  });

  it('restarts local services when frontend or OAuth config is stale', async () => {
    areServicesRunning.mockReturnValue(true);
    hasExpectedBackendConfig.mockReturnValue(false);

    await runGlobalSetup({
      env: testEnv,
      cwd: () => '/workspace/frontend',
      chdir,
      logger,
      waitForService,
      getDockerComposeCommand,
      areServicesRunning,
      removeExistingContainers,
      execCommand,
      printServiceLogs,
      hasExpectedBackendConfig,
      hasExpectedOAuthClientRedirect,
    });

    expect(removeExistingContainers).toHaveBeenCalledTimes(1);
    expect(execCommand).toHaveBeenCalledTimes(2);
    expect(execCommand).toHaveBeenNthCalledWith(
      1,
      'docker compose --profile test --env-file .env.test down --remove-orphans',
      'Cleaning up existing containers',
      '/workspace',
      { env: expectedDockerEnv }
    );
    expect(execCommand).toHaveBeenNthCalledWith(
      2,
      'docker compose --profile test --env-file .env.test up -d --build',
      'Starting Docker services',
      '/workspace',
      { env: expectedDockerEnv, ignoreError: true }
    );
  });

  it('requires the OAuth client to allow the web app and MCP callbacks', async () => {
    // A stack left running from before the MCP callback was registered has a
    // client the MCP flow cannot use, so it has to count as stale.
    areServicesRunning.mockReturnValue(true);
    // Stale on the pre-restart check, present once the stack comes back up.
    hasExpectedOAuthClientRedirect
      .mockResolvedValueOnce(false)
      .mockResolvedValue(true);

    await runGlobalSetup({
      env: testEnv,
      cwd: () => '/workspace/frontend',
      chdir,
      logger,
      waitForService,
      getDockerComposeCommand,
      areServicesRunning,
      removeExistingContainers,
      execCommand,
      printServiceLogs,
      hasExpectedBackendConfig,
      hasExpectedOAuthClientRedirect,
    });

    expect(hasExpectedOAuthClientRedirect).toHaveBeenCalledWith([
      FRONTEND_TEST_CALLBACK_URL,
      MCP_TEST_CALLBACK_URL,
    ]);
    expect(removeExistingContainers).toHaveBeenCalledTimes(1);
  });
});
