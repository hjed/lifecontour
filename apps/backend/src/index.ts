import 'reflect-metadata'; // Required for tsyringe
import './instrumentation.js'; // OpenTelemetry must be imported first
// import { container } from 'tsyringe'; // Will be used when we add DI services
import { createServer } from './server.js';
import { logger } from './shared/logger.js';
import { config } from './shared/config.js';

// Graceful shutdown handler
const gracefulShutdown = (signal: string) => {
  logger.info(`Received ${signal}, starting graceful shutdown...`);

  process.exit(0);
};

// Handle shutdown signals
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

// Handle uncaught exceptions
process.on('uncaughtException', error => {
  logger.error('Uncaught exception:', error);
  process.exit(1);
});

process.on('unhandledRejection', (reason, promise) => {
  logger.error('Unhandled rejection at:', promise, 'reason:', reason);
  process.exit(1);
});

// Start the server
async function start() {
  try {
    const server = await createServer();

    const address = await server.listen({
      port: config.server.port,
      host: config.server.host,
    });

    logger.info(`🚀 Server listening at ${address}`);
    logger.info(`📚 API documentation available at ${address}/docs`);
    logger.info(`🔍 Health check available at ${address}/health`);
  } catch (error) {
    logger.error('Failed to start server:', error);
    process.exit(1);
  }
}

start();
