/**
 * Global setup for Playwright tests.
 *
 * Handles test environment setup including:
 * - API mocking configuration
 * - Test database setup
 * - Authentication state preparation
 */

import { chromium, FullConfig } from '@playwright/test';

async function globalSetup(_config: FullConfig) {
  console.log('🚀 Setting up Playwright test environment...');

  // Ensure backend is running
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';

  try {
    // Check if backend is available
    const response = await fetch(`${backendUrl}/api/health`);
    if (!response.ok) {
      throw new Error(`Backend health check failed: ${response.status}`);
    }
    console.log('✅ Backend is running and healthy');
  } catch (error) {
    console.error('❌ Backend is not available:', error);
    console.log('💡 Make sure to run: docker-compose up -d');
    process.exit(1);
  }

  // Set up test authentication state
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Create authenticated session for tests that need it
    // This will be used by tests that require authentication
    await page.goto('http://localhost:3000/');

    // Store authentication state
    await context.storageState({ path: 'tests/e2e/fixtures/auth-state.json' });
  } catch (error) {
    console.log('⚠️  Frontend not running, using default auth state');
    // Create minimal auth state for tests
    await context.storageState({ path: 'tests/e2e/fixtures/auth-state.json' });
  }

  await browser.close();

  console.log('✅ Global setup completed');
}

export default globalSetup;
