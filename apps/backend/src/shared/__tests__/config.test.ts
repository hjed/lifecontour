import { ConfigService } from '../config';

describe('Configuration System', () => {
  let originalEnv: NodeJS.ProcessEnv;

  beforeEach(() => {
    // Save original environment
    originalEnv = { ...process.env };

    // Clear relevant environment variables (but keep NODE_ENV as Jest sets it)
    delete process.env.PORT;
    delete process.env.SERVER_PORT;
    delete process.env.HOST;
    delete process.env.SERVER_HOST;
    delete process.env.DATABASE_URL;
    delete process.env.LOG_LEVEL;
    delete process.env.CORS_ORIGIN;
    delete process.env.RATE_LIMIT_MAX_REQUESTS;
    delete process.env.SESSION_SECRET;
  });

  afterEach(() => {
    // Restore original environment
    process.env = originalEnv;

    // Clear module cache to ensure fresh config loading
    jest.resetModules();
  });

  describe('Default Configuration', () => {
    it('should load with default values when no environment variables are set', async () => {
      // Dynamically import to get fresh config
      const { config } = await import('../config');

      expect(config.nodeEnv).toBe('test'); // Will be 'test' in Jest environment
      expect(config.server.port).toBe(3001);
      expect(config.server.host).toBe('0.0.0.0');
      expect(config.server.trustProxy).toBe(false); // Will be false because TRUST_PROXY env var is not set
      expect(config.database.url).toBe(':memory:'); // Will be ':memory:' in test environment
      expect(config.logging.level).toBe('error'); // Will be 'error' in test environment
      expect(config.cors.origin).toBe('http://localhost:3000');
      expect(config.rateLimit.maxRequests).toBe(100);
    });

    it('should have correct helper properties with defaults', async () => {
      const { config } = await import('../config');

      expect(config.isDevelopment).toBe(false); // Will be false in Jest test environment
      expect(config.isProduction).toBe(false);
      expect(config.isTest).toBe(true); // Will be true in Jest test environment
    });
  });

  describe('Environment Variable Override', () => {
    it('should override port from environment variables', async () => {
      process.env.PORT = '4000';

      const { config } = await import('../config');
      expect(config.server.port).toBe(4000);
    });

    it('should override port from SERVER_PORT environment variable', async () => {
      process.env.SERVER_PORT = '5000';

      const { config } = await import('../config');
      expect(config.server.port).toBe(5000);
    });

    it('should override host from environment variables', async () => {
      process.env.HOST = '127.0.0.1';

      const { config } = await import('../config');
      expect(config.server.host).toBe('127.0.0.1');
    });

    it('should override database URL from environment variables', async () => {
      process.env.DATABASE_URL = '/custom/path/db.sqlite';

      const { config } = await import('../config');
      expect(config.database.url).toBe('/custom/path/db.sqlite');
    });

    it('should override log level from environment variables', async () => {
      process.env.LOG_LEVEL = 'debug';

      const { config } = await import('../config');
      expect(config.logging.level).toBe('debug');
    });

    it('should parse multiple CORS origins from environment variables', async () => {
      process.env.CORS_ORIGIN = 'http://localhost:3000,https://example.com,https://app.example.com';

      const { config } = await import('../config');
      expect(config.cors.origin).toEqual([
        'http://localhost:3000',
        'https://example.com',
        'https://app.example.com',
      ]);
    });

    it('should override rate limit settings from environment variables', async () => {
      process.env.RATE_LIMIT_MAX_REQUESTS = '200';
      process.env.RATE_LIMIT_WINDOW_MS = '60000';

      const { config } = await import('../config');
      expect(config.rateLimit.maxRequests).toBe(200);
      expect(config.rateLimit.windowMs).toBe(60000);
    });
  });

  describe('Environment-specific Configuration', () => {
    it('should set helper properties correctly for production', async () => {
      process.env.NODE_ENV = 'production';

      const { config } = await import('../config');
      expect(config.nodeEnv).toBe('production');
      expect(config.isDevelopment).toBe(false);
      expect(config.isProduction).toBe(true);
      expect(config.isTest).toBe(false);
    });

    it('should set helper properties correctly for test', async () => {
      process.env.NODE_ENV = 'test';

      const { config } = await import('../config');
      expect(config.nodeEnv).toBe('test');
      expect(config.isDevelopment).toBe(false);
      expect(config.isProduction).toBe(false);
      expect(config.isTest).toBe(true);
    });
  });

  describe('Configuration Service', () => {
    it('should create ConfigService instance', () => {
      const configService = new ConfigService();
      expect(configService).toBeInstanceOf(ConfigService);
      expect(configService.config).toBeDefined();
    });

    it('should have helper methods in ConfigService', () => {
      process.env.NODE_ENV = 'development';

      const configService = new ConfigService();
      expect(configService.isDevelopment).toBe(true);
      expect(configService.isProduction).toBe(false);
      expect(configService.isTest).toBe(false);
    });
  });

  describe('Validation', () => {
    it('should validate port range', async () => {
      process.env.PORT = '70000'; // Invalid port

      // Mock console.error and process.exit to test validation failure
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      const exitSpy = jest.spyOn(process, 'exit').mockImplementation();

      try {
        await import('../config');
      } catch {
        // Expected to fail
      }

      expect(consoleSpy).toHaveBeenCalledWith(
        'Configuration validation failed:',
        expect.any(Object)
      );
      expect(exitSpy).toHaveBeenCalledWith(1);

      consoleSpy.mockRestore();
      exitSpy.mockRestore();
    });

    it('should validate log level enum', async () => {
      process.env.LOG_LEVEL = 'invalid-level';

      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      const exitSpy = jest.spyOn(process, 'exit').mockImplementation();

      try {
        await import('../config');
      } catch {
        // Expected to fail
      }

      expect(consoleSpy).toHaveBeenCalledWith(
        'Configuration validation failed:',
        expect.any(Object)
      );
      expect(exitSpy).toHaveBeenCalledWith(1);

      consoleSpy.mockRestore();
      exitSpy.mockRestore();
    });
  });
});
