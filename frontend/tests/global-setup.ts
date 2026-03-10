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
};

function getProjectRoot(currentWorkingDirectory: string): string {
  return currentWorkingDirectory.replace(/[/\\]frontend$/, '');
}

/**
 * Wait for a service to be ready by polling its health endpoint
 */
async function waitForService(
  url: string,
  maxAttempts = 30,
  interval = 2000
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
      "docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' pms-backend",
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
      'http://localhost:4447/admin/clients/test-client-id'
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
    'pms-postgres',
    'pms-redis',
    'pms-meilisearch',
    'pms-oauth',
    'pms-oauth-login-consent',
    'pms-oauth-init',
    'pms-backend',
    'pms-google-worker',
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
      'google-contacts-worker',
    ];

    return expectedServices.every(service => runningServices.has(service));
  } catch {
    return false;
  }
}

<<<<<<< HEAD
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
  };
}
=======
function restartDockerServices(
  dockerComposeCmd: string,
  dockerTestEnv: NodeJS.ProcessEnv
): void {
  // Force-remove any pre-existing containers whose names overlap with the
  // test profile (e.g. leftover containers from the dev profile).
  removeExistingContainers();

  // Stop any existing containers to ensure clean state
  execCommand(
    `${dockerComposeCmd} --profile test --env-file .env.test down --remove-orphans`,
    'Cleaning up existing containers',
    { env: dockerTestEnv }
  );

  // Start Docker services (docker-compose v1 doesn't support --wait)
  // Note: This may exit with error code if init containers exit after completing,
  // but we ignore that since we verify service health separately
  execCommand(
    `${dockerComposeCmd} --profile test --env-file .env.test up -d --build`,
    'Starting Docker services',
    { env: dockerTestEnv, ignoreError: true }
  );
}

async function ensureLocalDockerServices(
  dockerComposeCmd: string,
  dockerTestEnv: NodeJS.ProcessEnv
): Promise<void> {
  const servicesRunning = areServicesRunning();

  if (!servicesRunning) {
    restartDockerServices(dockerComposeCmd, dockerTestEnv);
    console.log('🔍 Verifying service health...');
    return;
  }

  const backendConfigMatches = hasExpectedBackendConfig(FRONTEND_TEST_URL);
  const oauthClientMatches = await hasExpectedOAuthClientRedirect(
    FRONTEND_TEST_CALLBACK_URL
  );

  if (backendConfigMatches && oauthClientMatches) {
    console.log('📋 Docker services already running, skipping startup...');
    console.log('🔍 Verifying service health...');
    return;
  }

  console.log(
    '♻️ Docker services are running with stale frontend/OAuth config, restarting them...'
  );
  restartDockerServices(dockerComposeCmd, dockerTestEnv);
  console.log('🔍 Verifying service health...');
}

async function verifyServiceHealth(): Promise<void> {
  // Wait for backend API readiness
  console.log('🔍 Checking backend API readiness...');
  await waitForService('http://localhost:8001/api/health/ready');

  // Wait for OAuth provider (check admin health endpoint)
  console.log('🔍 Checking OAuth provider health...');
  await waitForService('http://localhost:4447/health/ready');

  // Wait for MeiliSearch
  console.log('🔍 Checking MeiliSearch health...');
  await waitForService('http://localhost:7701/health');

  console.log('✅ All services are ready!');
}

function handleGlobalSetupFailure(
  error: unknown,
  projectRoot: string
): never | void {
  console.error('❌ Global setup failed:', error);

  // In CI, if Docker fails, we can fall back to mock mode
  if (process.env.CI) {
    console.log('🧪 Docker failed in CI, enabling mock mode for tests');
    process.env.USE_MOCK_BACKEND = 'true';
    return;
  }

  // Show service logs for debugging
  try {
    console.log('📋 Docker service logs:');
    const dockerComposeCmd = getDockerComposeCommand();
    execSync(`${dockerComposeCmd} --profile test logs --tail=50`, {
      stdio: 'inherit',
      cwd: projectRoot,
    });
  } catch (logError) {
    console.error('Failed to retrieve logs:', logError);
  }

  throw error;
}

async function globalSetup(_config: FullConfig) {
  console.log('🚀 Starting Playwright Global Setup...');
>>>>>>> 7a7458f20 (Address actionable Sonar findings)

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
<<<<<<< HEAD
      const servicesRunning = dependencies.areServicesRunning(
        dockerComposeCmd,
        projectRoot
      );
      const backendConfigMatches = servicesRunning
        ? hasExpectedBackendConfig(FRONTEND_TEST_URL, projectRoot)
        : false;
      const oauthClientMatches = servicesRunning
        ? await hasExpectedOAuthClientRedirect(FRONTEND_TEST_CALLBACK_URL)
        : false;

      if (servicesRunning && backendConfigMatches && oauthClientMatches) {
        dependencies.logger.log(
          '📋 Docker services already running, skipping startup...'
        );
      } else {
        if (servicesRunning) {
          dependencies.logger.log(
            '♻️ Docker services are running with stale frontend/OAuth config, restarting them...'
          );
        }

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

      dependencies.logger.log('🔍 Verifying service health...');
    }

    dependencies.logger.log('🔍 Checking backend API readiness...');
    await dependencies.waitForService('http://localhost:8001/api/health/ready');

    dependencies.execCommand(
      `${dockerComposeCmd} --profile test exec -T backend alembic upgrade head`,
      'Ensuring backend database schema is up to date',
      projectRoot
    );

    dependencies.logger.log('🔍 Re-checking backend API readiness...');
    await dependencies.waitForService('http://localhost:8001/api/health/ready');

    dependencies.logger.log('🔍 Checking OAuth provider health...');
    await dependencies.waitForService('http://localhost:4447/health/ready');
=======
      await ensureLocalDockerServices(dockerComposeCmd, dockerTestEnv);
    }

    await verifyServiceHealth();
>>>>>>> 7a7458f20 (Address actionable Sonar findings)

    dependencies.logger.log('🔍 Checking MeiliSearch health...');
    await dependencies.waitForService('http://localhost:7701/health');

    dependencies.logger.log('✅ All services are ready!');
    dependencies.logger.log('🎉 Global setup completed successfully!');
  } catch (error) {
<<<<<<< HEAD
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
=======
    return handleGlobalSetupFailure(error, projectRoot);
>>>>>>> 7a7458f20 (Address actionable Sonar findings)
  }
}

async function globalSetup(_config: FullConfig) {
  await runGlobalSetup();
}

export default globalSetup;
