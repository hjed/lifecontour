/**
 * Playwright Global Teardown
 *
 * Cleans up the Docker environment after all e2e tests complete.
 * Only runs cleanup in CI or when explicitly requested.
 */

import { execSync } from 'child_process';

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
      // globalTeardown() chdir's to project root; keep exec cwd consistent
      cwd: process.cwd(),
    });
    console.log(`✅ ${description} completed`);
  } catch (error) {
    console.error(`❌ ${description} failed:`, error);
    // Don't throw in teardown - log and continue
  }
}

async function globalTeardown() {
  console.log('🧹 Starting Playwright Global Teardown...');

  // Change to project root directory
  const projectRoot = process.cwd().replace(/[/\\]frontend$/, '');
  process.chdir(projectRoot);

  // Only cleanup in CI or when CLEANUP_AFTER_TESTS is set
  const shouldCleanup =
    process.env.CI || process.env.CLEANUP_AFTER_TESTS === 'true';

  if (!shouldCleanup) {
    console.log(
      '🏠 Local development mode - keeping services running for faster subsequent test runs'
    );
    console.log('💡 Set CLEANUP_AFTER_TESTS=true to force cleanup');
    return;
  }

  try {
    console.log('🛑 Stopping Docker services...');

    // Detect the correct Docker Compose command
    const dockerComposeCmd = getDockerComposeCommand();
    console.log(`🐳 Using Docker Compose command: ${dockerComposeCmd}`);

    // Stop and remove containers, networks, and volumes
    execCommand(
      `${dockerComposeCmd} --profile test --env-file .env.test down --volumes --remove-orphans`,
      'Stopping and cleaning up Docker services'
    );

    // Optional: Clean up any dangling images (only in CI)
    if (process.env.CI) {
      execCommand(
        'docker image prune -f',
        'Cleaning up dangling Docker images'
      );
    }

    console.log('✅ Global teardown completed successfully!');
  } catch (error) {
    console.error('❌ Global teardown encountered errors:', error);
    // Don't fail the test run due to cleanup issues
  }
}

export default globalTeardown;
