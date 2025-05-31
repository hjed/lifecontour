import winston from 'winston';
import { singleton } from 'tsyringe';
import { config } from './config';

// Custom log format for Australian locale
const australianFormat = winston.format.combine(
  winston.format.timestamp({
    format: 'DD/MM/YYYY HH:mm:ss', // Australian date format
  }),
  winston.format.errors({ stack: true }),
  winston.format.json()
);

// Simple format for development
const simpleFormat = winston.format.combine(
  winston.format.timestamp({
    format: 'DD/MM/YYYY HH:mm:ss',
  }),
  winston.format.errors({ stack: true }),
  winston.format.printf(({ timestamp, level, message, ...meta }) => {
    const metaStr = Object.keys(meta).length ? JSON.stringify(meta, null, 2) : '';
    return `${timestamp} [${level.toUpperCase()}]: ${message} ${metaStr}`;
  })
);

// Create transports based on configuration
const createTransports = () => {
  const transports: winston.transport[] = [];

  // Console transport
  if (config.logging.enableConsole) {
    transports.push(
      new winston.transports.Console({
        format: config.logging.format === 'json' ? australianFormat : simpleFormat,
      })
    );
  }

  // File transport
  if (config.logging.enableFile && config.logging.filename) {
    transports.push(
      new winston.transports.File({
        filename: config.logging.filename,
        format: australianFormat,
        maxsize: 10 * 1024 * 1024, // 10MB
        maxFiles: 5,
        tailable: true,
      })
    );
  }

  return transports;
};

// Create logger instance
const createLogger = () => {
  return winston.createLogger({
    level: config.logging.level,
    format: australianFormat,
    transports: createTransports(),
    // Don't exit on handled exceptions
    exitOnError: false,
    // Handle uncaught exceptions
    exceptionHandlers: [
      new winston.transports.Console({
        format: simpleFormat,
      }),
    ],
    // Handle unhandled promise rejections
    rejectionHandlers: [
      new winston.transports.Console({
        format: simpleFormat,
      }),
    ],
  });
};

@singleton()
export class LoggerService {
  private readonly _logger = createLogger();

  get logger() {
    return this._logger;
  }

  // Convenience methods
  error(message: string, meta?: Record<string, unknown>) {
    this._logger.error(message, meta);
  }

  warn(message: string, meta?: Record<string, unknown>) {
    this._logger.warn(message, meta);
  }

  info(message: string, meta?: Record<string, unknown>) {
    this._logger.info(message, meta);
  }

  debug(message: string, meta?: Record<string, unknown>) {
    this._logger.debug(message, meta);
  }

  // Structured logging for API requests
  logRequest(
    method: string,
    url: string,
    statusCode: number,
    responseTime: number,
    meta?: Record<string, unknown>
  ) {
    this._logger.info('API Request', {
      method,
      url,
      statusCode,
      responseTime,
      ...meta,
    });
  }

  // Structured logging for errors
  logError(error: Error, context?: string, meta?: Record<string, unknown>) {
    this._logger.error('Application Error', {
      message: error.message,
      stack: error.stack,
      context,
      ...meta,
    });
  }

  // Structured logging for database operations
  logDatabase(operation: string, table: string, duration: number, meta?: Record<string, unknown>) {
    this._logger.debug('Database Operation', {
      operation,
      table,
      duration,
      ...meta,
    });
  }

  // Structured logging for external API calls
  logExternalApi(
    service: string,
    method: string,
    url: string,
    statusCode: number,
    duration: number,
    meta?: Record<string, unknown>
  ) {
    this._logger.info('External API Call', {
      service,
      method,
      url,
      statusCode,
      duration,
      ...meta,
    });
  }
}

// Export singleton instance
export const logger = createLogger();
