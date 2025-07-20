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
async function waitForService(url: string, maxAttempts = 30, interval = 2000): Promise<void> {
  console.log(`Waiting for service: ${url}`);
  
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        console.log(`✅ Service ready: ${url}`);
        return;
      }
    } catch (error) {
      // Service not ready yet
    }
    
    if (attempt === maxAttempts) {
      throw new Error(`❌ Service failed to start after ${maxAttempts} attempts: ${url}`);
    }
    
    console.log(`⏳ Attempt ${attempt}/${maxAttempts} - waiting ${interval}ms...`);
    await new Promise(resolve => setTimeout(resolve, interval));
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
      cwd: process.cwd().replace('/frontend', '') // Ensure we're in project root
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
    const result = execSync('docker-compose -f docker-compose.test.yml ps --services --filter "status=running"', {
      encoding: 'utf8',
      stdio: 'pipe',
      cwd: process.cwd().replace('/frontend', '')
    });
    
    const runningServices = result.trim().split('\n').filter(Boolean);
    const expectedServices = ['database-test', 'oauth-provider-test', 'backend-test', 'meilisearch-test', 'redis-test'];
    
    return expectedServices.every(service => runningServices.includes(service));
  } catch {
    return false;
  }
}

async function globalSetup(config: FullConfig) {
  console.log('🚀 Starting Playwright Global Setup...');
  
  // Change to project root directory
  const projectRoot = process.cwd().replace('/frontend', '');
  process.chdir(projectRoot);
  
  try {
    // Check if services are already running
    if (areServicesRunning()) {
      console.log('📋 Docker services already running, skipping startup...');
    } else {
      // Stop any existing containers to ensure clean state
      execCommand(
        'docker-compose -f docker-compose.test.yml down --remove-orphans',
        'Cleaning up existing containers'
      );
      
      // Start Docker services (docker-compose v1 doesn't support --wait)
      execCommand(
        'docker-compose -f docker-compose.test.yml up -d --build',
        'Starting Docker services'
      );
    }
    
    // Wait for critical services to be ready
    console.log('🔍 Verifying service health...');
    
    // Wait for backend API
    await waitForService('http://localhost:8001/api/health');
    
    // Wait for OAuth provider
    await waitForService('http://localhost:4446/.well-known/openid_configuration');
    
    // Wait for MeiliSearch
    await waitForService('http://localhost:7701/health');
    
    console.log('✅ All services are ready!');
    
    // Optional: Create a test browser instance to verify frontend connectivity
    console.log('🌐 Verifying frontend connectivity...');
    const browser = await chromium.launch();
    const page = await browser.newPage();
    
    try {
      // Test that we can reach the backend through the frontend
      const response = await page.request.get('http://localhost:8001/api/health');
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
      execSync('docker-compose -f docker-compose.test.yml logs --tail=50', { 
        stdio: 'inherit',
        cwd: projectRoot
      });
    } catch (logError) {
      console.error('Failed to retrieve logs:', logError);
    }
    
    throw error;
  }
}

export default globalSetup;
