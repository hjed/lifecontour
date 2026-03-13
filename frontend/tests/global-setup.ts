/**
 * Playwright Global Setup
 *
 * Sets up the Docker environment for e2e tests including:
 * - PostgreSQL test database
 * - OAuth provider (Hydra)
 * - Backend API
 * - MeiliSearch
 * - Redis
 */

import { FullConfig } from '@playwright/test';
import { execSync } from 'node:child_process';
import {
  FRONTEND_TEST_CALLBACK_URL,
  FRONTEND_TEST_PORT,
  FRONTEND_TEST_URL,
  getFrontendCorsOrigins,
  CONTAINER_PREFIX,
  BACKEND_TEST_PORT,
  OAUTH_ADMIN_TEST_PORT,
  MEILI_TEST_PORT,
  workspaceEnv,
} from './e2e/utils/frontend-test-config';

type Logger = Pick<Console, 'log' | 'error'>;

type GlobalSetupDependencies = {
  env: NodeJS.ProcessEnv;
  cwd: () => string;
  chdir: (directory: string) => void;
  logger: Logger;
  waitForService: typeof waitForService;
  getDockerComposeCommand: typeof getDockerComposeCommand;
  areServicesRunning: typeof areServicesRunning;
  removeExistingContainers: typeof removeExistingContainers;
  execCommand: typeof execCommand;
  printServiceLogs: typeof printServiceLogs;
  hasExpectedBackendConfig: typeof hasExpectedBackendConfig;
  hasExpectedOAuthClientRedirect: typeof hasExpectedOAuthClientRedirect;
};

function getProjectRoot(currentWorkingDirectory: string): string {
  return currentWorkingDirectory.replace(/[/\\]frontend$/, '');
}

/**
 * Wait for a service to be ready by polling its health endpoint
 */
async function waitForService(
  url: string,
  maxAttempts = 120,
  interval = 3000
): Promise<void> {
  console.log(`Waiting for service: ${url}`);

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(url);
      // For OAuth auth endpoint, we expect a redirect (3xx) or method not allowed (405)
      // For other endpoints, we expect 200 OK
      if (
        response.ok ||
        (url.includes('/oauth2/auth') &&
          response.status >= 300 &&
          response.status < 400) ||
        (url.includes('/oauth2/auth') && response.status === 405)
      ) {
        console.log(`✅ Service ready: ${url} (status: ${response.status})`);
        return;
      } else {
        console.log(
          `⏳ Service not ready: ${url} (status: ${response.status})`
        );
      }
    } catch (error) {
      console.log(
        `⏳ Service not ready: ${url} (error: ${error instanceof Error ? error.message : String(error)})`
      );
    }

    if (attempt === maxAttempts) {
      throw new Error(
        `❌ Service failed to start after ${maxAttempts} attempts: ${url}`
      );
    }

    console.log(
      `⏳ Attempt ${attempt}/${maxAttempts} - waiting ${interval}ms...`
    );
    await new Promise(resolve => setTimeout(resolve, interval));
  }
}

/**
 * Detect the correct Docker Compose command (v2 plugin vs standalone)
 */
function getDockerComposeCommand(): string {
  try {
    // Try 'docker compose' first (v2 plugin)
    execSync('docker compose version', { stdio: 'pipe' });
    return 'docker compose';
  } catch {
    try {
      // Fall back to 'docker-compose' (standalone)
      execSync('docker-compose version', { stdio: 'pipe' });
      return 'docker-compose';
    } catch {
      throw new Error(
        'Neither "docker compose" nor "docker-compose" is available'
      );
    }
  }
}

/**
 * Execute shell command with error handling
 */
function execCommand(
  command: string,
  description: string,
  projectRoot: string,
  options?: { env?: NodeJS.ProcessEnv; ignoreError?: boolean }
): void {
  console.log(`🔧 ${description}...`);
  try {
    execSync(command, {
      stdio: 'inherit',
      cwd: projectRoot,
      env: options?.env ?? process.env,
    });
    console.log(`✅ ${description} completed`);
  } catch (error) {
    if (options?.ignoreError) {
      console.log(`⚠️  ${description} completed with warnings (ignored)`);
      console.error(`ℹ️  Ignored error details for "${description}":`, error);
    } else {
      console.error(`❌ ${description} failed:`, error);
      throw error;
    }
  }
}

function printServiceLogs(dockerComposeCmd: string, projectRoot: string): void {
  execSync(`${dockerComposeCmd} --profile test logs --tail=50`, {
    stdio: 'inherit',
    cwd: projectRoot,
  });
}

function getDockerTestEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return {
    ...env,
    ...workspaceEnv,
    FRONTEND_URL: FRONTEND_TEST_URL,
    FRONTEND_PORT: FRONTEND_TEST_PORT,
    CORS_ORIGINS: getFrontendCorsOrigins(),
  };
}

function hasExpectedBackendConfig(
  frontendUrl: string,
  projectRoot: string
): boolean {
  try {
    const result = execSync(
      `docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' ${CONTAINER_PREFIX}-backend`,
      {
        encoding: 'utf8',
        stdio: 'pipe',
        cwd: projectRoot,
      }
    );

    return result.includes(`FRONTEND_URL=${frontendUrl}`);
  } catch {
    return false;
  }
}

async function hasExpectedOAuthClientRedirect(
  callbackUrl: string
): Promise<boolean> {
  try {
    const response = await fetch(
      `http://localhost:${OAUTH_ADMIN_TEST_PORT}/admin/clients/test-client-id`
    );

    if (!response.ok) {
      return false;
    }

    const client = (await response.json()) as { redirect_uris?: string[] };
    return client.redirect_uris?.includes(callbackUrl) ?? false;
  } catch {
    return false;
  }
}

/**
 * Force-remove any existing containers that share names with the test-profile
 * containers.  This prevents "name already in use" errors when switching from
 * the dev profile to the test profile (or vice versa).
 */
function removeExistingContainers(): void {
  // All container_name values used by test-profile services in docker-compose.yml
  const containerNames = [
    `${CONTAINER_PREFIX}-postgres`,
    `${CONTAINER_PREFIX}-redis`,
    `${CONTAINER_PREFIX}-meilisearch`,
    `${CONTAINER_PREFIX}-oauth`,
    `${CONTAINER_PREFIX}-oauth-login-consent`,
    `${CONTAINER_PREFIX}-oauth-init`,
    `${CONTAINER_PREFIX}-backend`,
    `${CONTAINER_PREFIX}-google-worker`,
  ];

  console.log(
    '🧹 Force-removing any pre-existing containers with test names...'
  );
  for (const name of containerNames) {
    try {
      execSync(`docker rm -f ${name}`, { stdio: 'pipe' });
      console.log(`  ✅ Removed container: ${name}`);
    } catch {
      // Container didn't exist — that's fine, ignore the error
    }
  }
}

/**
 * Check if Docker services are already running
 */
function areServicesRunning(
  dockerComposeCmd: string,
  projectRoot: string
): boolean {
  try {
    const result = execSync(
      `${dockerComposeCmd} --profile test ps --services --filter "status=running"`,
      {
        encoding: 'utf8',
        stdio: 'pipe',
        cwd: projectRoot,
      }
    );

    const runningServices = new Set(result.trim().split('\n').filter(Boolean));

    const expectedServices = [
      'database',
      'oauth-provider',
      'backend',
      'meilisearch',
      'redis',
      'google-worker',
    ];

    return expectedServices.every(service => runningServices.has(service));
  } catch {
    return false;
  }
}

function createDefaultDependencies(): GlobalSetupDependencies {
  return {
    env: process.env,
    cwd: () => process.cwd(),
    chdir: directory => process.chdir(directory),
    logger: console,
    waitForService,
    getDockerComposeCommand,
    areServicesRunning,
    removeExistingContainers,
    execCommand,
    printServiceLogs,
    hasExpectedBackendConfig,
    hasExpectedOAuthClientRedirect,
  };
}

function restartDockerServices(
  dependencies: GlobalSetupDependencies,
  dockerComposeCmd: string,
  projectRoot: string,
  dockerTestEnv: NodeJS.ProcessEnv
): void {
  dependencies.removeExistingContainers();

  dependencies.execCommand(
    `${dockerComposeCmd} --profile test --env-file .env.test down --remove-orphans`,
    'Cleaning up existing containers',
    projectRoot,
    { env: dockerTestEnv }
  );

  dependencies.execCommand(
    `${dockerComposeCmd} --profile test --env-file .env.test up -d --build`,
    'Starting Docker services',
    projectRoot,
    { env: dockerTestEnv, ignoreError: true }
  );
}

async function ensureLocalDockerServices(
  dependencies: GlobalSetupDependencies,
  dockerComposeCmd: string,
  projectRoot: string,
  dockerTestEnv: NodeJS.ProcessEnv
): Promise<void> {
  const servicesRunning = dependencies.areServicesRunning(
    dockerComposeCmd,
    projectRoot
  );
  const backendConfigMatches = servicesRunning
    ? dependencies.hasExpectedBackendConfig(FRONTEND_TEST_URL, projectRoot)
    : false;
  const oauthClientMatches = servicesRunning
    ? await dependencies.hasExpectedOAuthClientRedirect(
        FRONTEND_TEST_CALLBACK_URL
      )
    : false;

  if (servicesRunning && backendConfigMatches && oauthClientMatches) {
    dependencies.logger.log(
      '📋 Docker services already running, skipping startup...'
    );
    dependencies.logger.log('🔍 Verifying service health...');
    return;
  }

  if (servicesRunning) {
    dependencies.logger.log(
      '♻️ Docker services are running with stale frontend/OAuth config, restarting them...'
    );
  }

  restartDockerServices(
    dependencies,
    dockerComposeCmd,
    projectRoot,
    dockerTestEnv
  );
  dependencies.logger.log('🔍 Verifying service health...');
}

async function verifyCoreServiceHealth(
  dependencies: GlobalSetupDependencies,
  dockerComposeCmd: string,
  projectRoot: string
): Promise<void> {
  dependencies.logger.log('🔍 Checking backend API readiness...');
  await dependencies.waitForService(
    `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
  );

  dependencies.execCommand(
    `${dockerComposeCmd} --profile test exec -T backend alembic upgrade head`,
    'Ensuring backend database schema is up to date',
    projectRoot
  );

  dependencies.logger.log('🔍 Re-checking backend API readiness...');
  await dependencies.waitForService(
    `http://localhost:${BACKEND_TEST_PORT}/api/health/ready`
  );

  dependencies.logger.log('🔍 Checking OAuth provider health...');
  await dependencies.waitForService(
    `http://localhost:${OAUTH_ADMIN_TEST_PORT}/health/ready`
  );
}

function handleGlobalSetupFailure(
  dependencies: GlobalSetupDependencies,
  error: unknown,
  dockerComposeCmd: string,
  projectRoot: string
): never | void {
  dependencies.logger.error('❌ Global setup failed:', error);

  if (dependencies.env.CI) {
    dependencies.logger.log(
      '🧪 Docker failed in CI, enabling mock mode for tests'
    );
    dependencies.env.USE_MOCK_BACKEND = 'true';
    return;
  }

  try {
    dependencies.logger.log('📋 Docker service logs:');
    dependencies.printServiceLogs(dockerComposeCmd, projectRoot);
  } catch (logError) {
    dependencies.logger.error('Failed to retrieve logs:', logError);
  }

  throw error;
}

export async function runGlobalSetup(
  dependencies: GlobalSetupDependencies = createDefaultDependencies()
): Promise<void> {
  const projectRoot = getProjectRoot(dependencies.cwd());

  dependencies.logger.log('🚀 Starting Playwright Global Setup...');

  if (dependencies.env.SKIP_DOCKER_SETUP === 'true') {
    dependencies.logger.log(
      '⏭️ Skipping Docker setup (SKIP_DOCKER_SETUP=true)'
    );
    dependencies.logger.log('🧪 Running tests with mocked backend services');
    return;
  }

  dependencies.chdir(projectRoot);

  const dockerComposeCmd = dependencies.getDockerComposeCommand();
  const dockerTestEnv = getDockerTestEnv(dependencies.env);
  dependencies.logger.log(
    `🐳 Using Docker Compose command: ${dockerComposeCmd}`
  );

  try {
    if (dependencies.env.CI) {
      dependencies.logger.log(
        '🏗️ CI environment detected - services should already be running'
      );
      dependencies.logger.log('🔍 Verifying service health...');
    } else {
      await ensureLocalDockerServices(
        dependencies,
        dockerComposeCmd,
        projectRoot,
        dockerTestEnv
      );
    }

    await verifyCoreServiceHealth(dependencies, dockerComposeCmd, projectRoot);

    dependencies.logger.log('🔍 Checking MeiliSearch health...');
    await dependencies.waitForService(
      `http://localhost:${MEILI_TEST_PORT}/health`
    );

    dependencies.logger.log('✅ All services are ready!');
    dependencies.logger.log('🎉 Global setup completed successfully!');
  } catch (error) {
    return handleGlobalSetupFailure(
      dependencies,
      error,
      dockerComposeCmd,
      projectRoot
    );
  }
}

async function globalSetup(_config: FullConfig) {
  await runGlobalSetup();
}

export default globalSetup;
