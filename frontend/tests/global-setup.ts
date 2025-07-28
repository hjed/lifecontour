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

import { chromium, FullConfig } from '@playwright/test';
import { execSync } from 'child_process';

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
function execCommand(command: string, description: string): void {
  console.log(`🔧 ${description}...`);
  try {
    execSync(command, {
      stdio: 'inherit',
      cwd: process.cwd().replace('/frontend', ''), // Ensure we're in project root
    });
    console.log(`✅ ${description} completed`);
  } catch (error) {
    console.error(`❌ ${description} failed:`, error);
    throw error;
  }
}

/**
 * Check if Docker services are already running
 */
function areServicesRunning(): boolean {
  try {
    const dockerComposeCmd = getDockerComposeCommand();
    const result = execSync(
      `${dockerComposeCmd} -f docker-compose.test.yml ps --services --filter "status=running"`,
      {
        encoding: 'utf8',
        stdio: 'pipe',
        cwd: process.cwd().replace('/frontend', ''),
      }
    );

    const runningServices = result.trim().split('\n').filter(Boolean);
    const expectedServices = [
      'database-test',
      'oauth-provider-test',
      'backend-test',
      'meilisearch-test',
      'redis-test',
    ];

    return expectedServices.every(service => runningServices.includes(service));
  } catch {
    return false;
  }
}

async function globalSetup(_config: FullConfig) {
  console.log('🚀 Starting Playwright Global Setup...');

  // Change to project root directory
  const projectRoot = process.cwd().replace('/frontend', '');
  process.chdir(projectRoot);

  // Detect the correct Docker Compose command
  const dockerComposeCmd = getDockerComposeCommand();
  console.log(`🐳 Using Docker Compose command: ${dockerComposeCmd}`);

  try {
    // In CI, services should already be started by the CI workflow
    // In local development, we may need to start them
    if (process.env.CI) {
      console.log(
        '🏗️ CI environment detected - services should already be running'
      );
      console.log('🔍 Verifying service health...');
    } else {
      // Check if services are already running
      if (areServicesRunning()) {
        console.log('📋 Docker services already running, skipping startup...');
      } else {
        // Stop any existing containers to ensure clean state
        execCommand(
          `${dockerComposeCmd} -f docker-compose.test.yml down --remove-orphans`,
          'Cleaning up existing containers'
        );

        // Start Docker services (docker-compose v1 doesn't support --wait)
        execCommand(
          `${dockerComposeCmd} -f docker-compose.test.yml up -d --build`,
          'Starting Docker services'
        );
      }

      console.log('🔍 Verifying service health...');
    }

    // Wait for backend API
    console.log('🔍 Checking backend API health...');
    await waitForService('http://localhost:8001/api/health');

    // Wait for OAuth provider (check admin health endpoint)
    console.log('🔍 Checking OAuth provider health...');
    await waitForService('http://localhost:4447/health/ready');

    // Wait for MeiliSearch
    console.log('🔍 Checking MeiliSearch health...');
    await waitForService('http://localhost:7701/health');

    console.log('✅ All services are ready!');

    // Optional: Create a test browser instance to verify frontend connectivity
    console.log('🌐 Verifying frontend connectivity...');
    const browser = await chromium.launch();
    const page = await browser.newPage();

    try {
      // Test that we can reach the backend through the frontend
      const response = await page.request.get(
        'http://localhost:8001/api/health'
      );
      if (!response.ok()) {
        throw new Error(`Backend health check failed: ${response.status()}`);
      }
      console.log('✅ Backend connectivity verified');
    } finally {
      await browser.close();
    }

    console.log('🎉 Global setup completed successfully!');
  } catch (error) {
    console.error('❌ Global setup failed:', error);

    // Show service logs for debugging
    try {
      console.log('📋 Docker service logs:');
      const dockerComposeCmd = getDockerComposeCommand();
      execSync(
        `${dockerComposeCmd} -f docker-compose.test.yml logs --tail=50`,
        {
          stdio: 'inherit',
          cwd: projectRoot,
        }
      );
    } catch (logError) {
      console.error('Failed to retrieve logs:', logError);
    }

    throw error;
  }
}

export default globalSetup;
