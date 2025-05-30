import Fastify from 'fastify';
import { config } from './shared/config';
import { logger } from './shared/logger';

import cors from '@fastify/cors';
import helmet from '@fastify/helmet';
import compress from '@fastify/compress';
import rateLimit from '@fastify/rate-limit';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';

export async function createServer() {
  const server = Fastify({
    logger: false, // We use our own logger
    trustProxy: config.server.trustProxy,
    requestTimeout: config.api.timeout,
  });

  await server.register(helmet, {
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        styleSrc: ["'self'", "'unsafe-inline'"],
        scriptSrc: ["'self'"],
        imgSrc: ["'self'", 'data:', 'https:'],
      },
    },
  });

  await server.register(cors, {
    origin: config.cors.origin,
    credentials: config.cors.credentials,
  });

  await server.register(compress, {
    global: true,
  });

  await server.register(rateLimit, {
    max: config.rateLimit.maxRequests,
    timeWindow: config.rateLimit.windowMs,
  });

  await server.register(swagger, {
    openapi: {
      openapi: '3.0.0',
      info: {
        title: 'Personal Management System API',
        description: 'API for Personal CRM & Journal System with MCP protocol support',
        version: '1.0.0',
        contact: {
          name: 'Personal Management System',
        },
      },
      servers: [
        {
          url: `http://localhost:${config.server.port}`,
          description: 'Development server',
        },
      ],
      components: {
        securitySchemes: {
          bearerAuth: {
            type: 'http',
            scheme: 'bearer',
            bearerFormat: 'JWT',
          },
        },
      },
    },
  });

  await server.register(swaggerUi, {
    routePrefix: '/docs',
    uiConfig: {
      docExpansion: 'list',
      deepLinking: false,
    },
    staticCSP: true,
    transformStaticCSP: header => header,
  });

  server.addHook('onRequest', async request => {
    request.startTime = Date.now();
  });

  server.addHook('onResponse', async (request, reply) => {
    const responseTime = Date.now() - (request.startTime ?? Date.now());

    logger.info('Request completed', {
      method: request.method,
      url: request.url,
      statusCode: reply.statusCode,
      responseTime,
      userAgent: request.headers['user-agent'],
      ip: request.ip,
    });
  });

  server.setErrorHandler(async (error, request, reply) => {
    logger.error('Request error', {
      error: error.message,
      stack: error.stack,
      method: request.method,
      url: request.url,
      statusCode: error.statusCode ?? 500,
    });

    const statusCode = error.statusCode ?? 500;
    const message = config.isDevelopment ? error.message : 'Internal Server Error';

    return reply.status(statusCode).send({
      error: {
        message,
        statusCode,
        ...(config.isDevelopment && { stack: error.stack }),
      },
    });
  });

  server.get(
    '/health',
    {
      schema: {
        description: 'Health check endpoint',
        tags: ['Health'],
        response: {
          200: {
            type: 'object',
            properties: {
              status: { type: 'string' },
              timestamp: { type: 'string' },
              uptime: { type: 'number' },
              environment: { type: 'string' },
            },
          },
        },
      },
    },
    async () => {
      return {
        status: 'healthy',
        timestamp: new Date().toISOString(),
        uptime: process.uptime(),
        environment: config.nodeEnv,
      };
    }
  );

  // API routes will be registered here as we build each domain
  // Example: await server.register(contactRoutes, { prefix: config.api.prefix });

  // 404 handler
  server.setNotFoundHandler(async (request, reply) => {
    return reply.status(404).send({
      error: {
        message: 'Route not found',
        statusCode: 404,
        path: request.url,
      },
    });
  });

  return server;
}

// Extend Fastify request interface for our custom properties
declare module 'fastify' {
  interface FastifyRequest {
    startTime?: number;
  }
}
