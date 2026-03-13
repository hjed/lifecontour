import { runGlobalSetup } from '../../../tests/global-setup';
import {
  FRONTEND_TEST_PORT,
  FRONTEND_TEST_URL,
  getFrontendCorsOrigins,
  workspaceEnv,
  BACKEND_TEST_PORT,
  OAUTH_ADMIN_TEST_PORT,
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
  const hasExpectedOAuthClientRedirect = jest.fn<Promise<boolean>, [string]>();
  const chdir = jest.fn();
  const logger = { log: jest.fn(), error: jest.fn() };
  const expectedDockerEnv: NodeJS.ProcessEnv = {
    ...testEnv,
    ...workspaceEnv,
    FRONTEND_URL: FRONTEND_TEST_URL,
    FRONTEND_PORT: FRONTEND_TEST_PORT,
    CORS_ORIGINS: getFrontendCorsOrigins(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    waitForService.mockResolvedValue(undefined);
    hasExpectedBackendConfig.mockReturnValue(true);
    hasExpectedOAuthClientRedirect.mockResolvedValue(true);
  });

  it('reruns backend migrations when reusing already-running local services', async () => {
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
    expect(execCommand).toHaveBeenCalledTimes(1);
    expect(execCommand).toHaveBeenCalledWith(
      'docker compose --profile test exec -T backend alembic upgrade head',
      'Ensuring backend database schema is up to date',
      '/workspace'
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      1,
      `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      2,
      `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      3,
      `http://localhost:${OAUTH_ADMIN_TEST_PORT}/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      4,
      `http://localhost:${MEILI_TEST_PORT}/health`
    );
  });

  it('starts services and still ensures backend schema is up to date', async () => {
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
    expect(execCommand).toHaveBeenNthCalledWith(
      3,
      'docker compose --profile test exec -T backend alembic upgrade head',
      'Ensuring backend database schema is up to date',
      '/workspace'
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      1,
      `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      2,
      `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
    );
    expect(waitForService).toHaveBeenNthCalledWith(
      3,
      `http://localhost:${OAUTH_ADMIN_TEST_PORT}/health/ready`
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
    expect(execCommand).toHaveBeenNthCalledWith(
      3,
      'docker compose --profile test exec -T backend alembic upgrade head',
      'Ensuring backend database schema is up to date',
      '/workspace'
    );
  });
});
