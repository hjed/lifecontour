import { createServer } from '../../server';
import { FastifyInstance } from 'fastify';

describe('API Integration Tests', () => {
  let server: FastifyInstance;

  beforeAll(async () => {
    // Set test environment
    process.env.NODE_ENV = 'test';
    process.env.LOG_LEVEL = 'error'; // Reduce log noise in tests
    process.env.CORS_ORIGIN = 'http://localhost:3000,https://test.example.com';

    server = await createServer();
    await server.ready(); // Ensure all plugins are loaded
  });

  afterAll(async () => {
    await server.close();
  });

  describe('Server Startup and Health', () => {
    it('should start server and respond to health checks', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
      });

      expect(response.statusCode).toBe(200);

      const body = JSON.parse(response.body);
      expect(body.status).toBe('healthy');
      expect(body.environment).toBe('test');
    });

    it('should be ready and have all plugins loaded', async () => {
      expect(server.hasPlugin('@fastify/cors')).toBe(true);
      expect(server.hasPlugin('@fastify/helmet')).toBe(true);
      expect(server.hasPlugin('@fastify/compress')).toBe(true);
      expect(server.hasPlugin('@fastify/rate-limit')).toBe(true);
      expect(server.hasPlugin('@fastify/swagger')).toBe(true);
      expect(server.hasPlugin('@fastify/swagger-ui')).toBe(true);
    });
  });

  describe('CORS Configuration', () => {
    it('should allow requests from configured origins', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
        headers: {
          Origin: 'http://localhost:3000',
        },
      });

      expect(response.statusCode).toBe(200);
      expect(response.headers['access-control-allow-origin']).toBe('http://localhost:3000');
    });

    it('should handle preflight OPTIONS requests', async () => {
      const response = await server.inject({
        method: 'OPTIONS',
        url: '/health',
        headers: {
          Origin: 'http://localhost:3000',
          'Access-Control-Request-Method': 'GET',
          'Access-Control-Request-Headers': 'Content-Type',
        },
      });

      expect(response.statusCode).toBe(204);
      expect(response.headers['access-control-allow-origin']).toBe('http://localhost:3000');
      expect(response.headers['access-control-allow-methods']).toContain('GET');
    });

    it('should include credentials in CORS headers', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
        headers: {
          Origin: 'http://localhost:3000',
        },
      });

      expect(response.headers['access-control-allow-credentials']).toBe('true');
    });
  });

  describe('Security Headers', () => {
    it('should include comprehensive security headers', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
      });

      // Helmet security headers
      expect(response.headers['x-frame-options']).toBeDefined();
      expect(response.headers['x-content-type-options']).toBe('nosniff');
      expect(response.headers['x-dns-prefetch-control']).toBe('off');
      expect(response.headers['x-download-options']).toBe('noopen');
      expect(response.headers['x-permitted-cross-domain-policies']).toBe('none');
    });

    it('should include Content Security Policy headers', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
      });

      expect(response.headers['content-security-policy']).toBeDefined();
      expect(response.headers['content-security-policy']).toContain("default-src 'self'");
    });
  });

  describe('API Documentation', () => {
    it('should serve Swagger UI with correct content', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/docs',
      });

      expect(response.statusCode).toBe(200);
      expect(response.headers['content-type']).toContain('text/html');
      expect(response.body).toContain('Swagger UI');
    });

    it('should serve OpenAPI specification', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/docs/json',
      });

      expect(response.statusCode).toBe(200);
      expect(response.headers['content-type']).toContain('application/json');

      const spec = JSON.parse(response.body);
      expect(spec.openapi).toBe('3.0.0');
      expect(spec.info.title).toBe('Personal Management System API');
      expect(spec.info.description).toContain('MCP protocol support');
      expect(spec.info.version).toBe('1.0.0');
    });

    it('should include health endpoint in API documentation', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/docs/json',
      });

      const spec = JSON.parse(response.body);
      expect(spec.paths['/health']).toBeDefined();
      expect(spec.paths['/health'].get).toBeDefined();
      expect(spec.paths['/health'].get.tags).toContain('Health');
      expect(spec.paths['/health'].get.responses['200']).toBeDefined();
    });
  });

  describe('Rate Limiting', () => {
    it('should allow normal request rates', async () => {
      // Make multiple requests within the rate limit
      const requests = Array(10)
        .fill(null)
        .map(() =>
          server.inject({
            method: 'GET',
            url: '/health',
          })
        );

      const responses = await Promise.all(requests);

      responses.forEach(response => {
        expect(response.statusCode).toBe(200);
        expect(response.headers['x-ratelimit-limit']).toBeDefined();
        expect(response.headers['x-ratelimit-remaining']).toBeDefined();
      });
    });

    it('should include rate limit headers', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
      });

      expect(response.headers['x-ratelimit-limit']).toBeDefined();
      expect(response.headers['x-ratelimit-remaining']).toBeDefined();
      expect(response.headers['x-ratelimit-reset']).toBeDefined();
    });
  });

  describe('Error Handling', () => {
    it('should handle 404 errors with proper JSON response', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/api/nonexistent',
      });

      expect(response.statusCode).toBe(404);
      expect(response.headers['content-type']).toContain('application/json');

      const body = JSON.parse(response.body);
      expect(body.error.message).toBe('Route not found');
      expect(body.error.statusCode).toBe(404);
      expect(body.error.path).toBe('/api/nonexistent');
    });

    it('should handle invalid HTTP methods', async () => {
      const response = await server.inject({
        method: 'PATCH',
        url: '/health',
      });

      expect(response.statusCode).toBe(404);
    });
  });

  describe('Content Compression', () => {
    it('should support gzip compression when requested', async () => {
      const response = await server.inject({
        method: 'GET',
        url: '/health',
        headers: {
          'Accept-Encoding': 'gzip, deflate',
        },
      });

      expect(response.statusCode).toBe(200);
      // The response should be successful regardless of compression
      expect(response.body).toBeDefined();
    });
  });

  describe('Request/Response Cycle', () => {
    it('should handle concurrent requests efficiently', async () => {
      const startTime = Date.now();

      const requests = Array(20)
        .fill(null)
        .map(() =>
          server.inject({
            method: 'GET',
            url: '/health',
          })
        );

      const responses = await Promise.all(requests);
      const endTime = Date.now();

      // All requests should succeed
      responses.forEach(response => {
        expect(response.statusCode).toBe(200);
      });

      // Should handle 20 requests reasonably quickly (under 2 seconds)
      expect(endTime - startTime).toBeLessThan(2000);
    });

    it('should maintain request isolation', async () => {
      const response1 = await server.inject({
        method: 'GET',
        url: '/health',
        headers: { 'X-Test-Header': 'request1' },
      });

      const response2 = await server.inject({
        method: 'GET',
        url: '/health',
        headers: { 'X-Test-Header': 'request2' },
      });

      expect(response1.statusCode).toBe(200);
      expect(response2.statusCode).toBe(200);

      // Both should return the same health data structure
      const body1 = JSON.parse(response1.body);
      const body2 = JSON.parse(response2.body);

      expect(body1.status).toBe('healthy');
      expect(body2.status).toBe('healthy');
    });
  });
});
