import winston from 'winston';
import { LoggerService } from '../logger';

// Mock winston to capture log calls
jest.mock('winston', () => {
  const mockLogger = {
    error: jest.fn(),
    warn: jest.fn(),
    info: jest.fn(),
    debug: jest.fn(),
  };

  return {
    createLogger: jest.fn(() => mockLogger),
    format: {
      combine: jest.fn(),
      timestamp: jest.fn(),
      errors: jest.fn(),
      json: jest.fn(),
      printf: jest.fn(),
    },
    transports: {
      Console: jest.fn(),
      File: jest.fn(),
    },
  };
});

describe('Logger System', () => {
  let loggerService: LoggerService;
  let mockLogger: any;

  beforeEach(() => {
    // Clear all mocks
    jest.clearAllMocks();

    // Set test environment
    process.env.NODE_ENV = 'test';
    process.env.LOG_LEVEL = 'debug';

    // Create logger service instance
    loggerService = new LoggerService();

    // Get the mock logger from winston.createLogger
    mockLogger = (winston.createLogger as jest.Mock).mock.results[0]?.value;
  });

  afterEach(() => {
    jest.resetModules();
  });

  describe('LoggerService Creation', () => {
    it('should create LoggerService instance', () => {
      expect(loggerService).toBeInstanceOf(LoggerService);
      expect(loggerService.logger).toBeDefined();
    });

    it('should call winston.createLogger during initialization', () => {
      expect(winston.createLogger).toHaveBeenCalled();
    });
  });

  describe('Basic Logging Methods', () => {
    it('should log error messages', () => {
      const message = 'Test error message';
      const meta = { userId: 123 };

      loggerService.error(message, meta);

      expect(mockLogger.error).toHaveBeenCalledWith(message, meta);
    });

    it('should log warning messages', () => {
      const message = 'Test warning message';
      const meta = { action: 'test' };

      loggerService.warn(message, meta);

      expect(mockLogger.warn).toHaveBeenCalledWith(message, meta);
    });

    it('should log info messages', () => {
      const message = 'Test info message';
      const meta = { status: 'success' };

      loggerService.info(message, meta);

      expect(mockLogger.info).toHaveBeenCalledWith(message, meta);
    });

    it('should log debug messages', () => {
      const message = 'Test debug message';
      const meta = { debug: true };

      loggerService.debug(message, meta);

      expect(mockLogger.debug).toHaveBeenCalledWith(message, meta);
    });

    it('should handle logging without metadata', () => {
      const message = 'Simple message';

      loggerService.info(message);

      expect(mockLogger.info).toHaveBeenCalledWith(message, undefined);
    });
  });

  describe('Structured Logging Methods', () => {
    it('should log API requests with structured data', () => {
      const method = 'GET';
      const url = '/api/test';
      const statusCode = 200;
      const responseTime = 150;
      const meta = { userAgent: 'test-agent' };

      loggerService.logRequest(method, url, statusCode, responseTime, meta);

      expect(mockLogger.info).toHaveBeenCalledWith('API Request', {
        method,
        url,
        statusCode,
        responseTime,
        userAgent: 'test-agent',
      });
    });

    it('should log errors with structured data', () => {
      const error = new Error('Test error');
      const context = 'user-service';
      const meta = { userId: 456 };

      loggerService.logError(error, context, meta);

      expect(mockLogger.error).toHaveBeenCalledWith('Application Error', {
        message: error.message,
        stack: error.stack,
        context,
        userId: 456,
      });
    });

    it('should log database operations with structured data', () => {
      const operation = 'SELECT';
      const table = 'users';
      const duration = 25;
      const meta = { rowCount: 10 };

      loggerService.logDatabase(operation, table, duration, meta);

      expect(mockLogger.debug).toHaveBeenCalledWith('Database Operation', {
        operation,
        table,
        duration,
        rowCount: 10,
      });
    });

    it('should log external API calls with structured data', () => {
      const service = 'google-calendar';
      const method = 'POST';
      const url = 'https://api.google.com/calendar/events';
      const statusCode = 201;
      const duration = 500;
      const meta = { eventId: 'abc123' };

      loggerService.logExternalApi(service, method, url, statusCode, duration, meta);

      expect(mockLogger.info).toHaveBeenCalledWith('External API Call', {
        service,
        method,
        url,
        statusCode,
        duration,
        eventId: 'abc123',
      });
    });
  });

  describe('Error Handling', () => {
    it('should handle Error objects in logError method', () => {
      const error = new Error('Database connection failed');
      error.stack = 'Error: Database connection failed\n    at test.js:1:1';

      loggerService.logError(error);

      expect(mockLogger.error).toHaveBeenCalledWith('Application Error', {
        message: 'Database connection failed',
        stack: error.stack,
        context: undefined,
      });
    });

    it('should handle errors without context', () => {
      const error = new Error('Simple error');

      loggerService.logError(error);

      expect(mockLogger.error).toHaveBeenCalledWith('Application Error', {
        message: 'Simple error',
        stack: error.stack,
        context: undefined,
      });
    });
  });

  describe('Metadata Handling', () => {
    it('should merge metadata correctly in structured logging', () => {
      const meta1 = { userId: 123 };
      const meta2 = { sessionId: 'abc' };

      loggerService.logRequest('GET', '/test', 200, 100, { ...meta1, ...meta2 });

      expect(mockLogger.info).toHaveBeenCalledWith('API Request', {
        method: 'GET',
        url: '/test',
        statusCode: 200,
        responseTime: 100,
        userId: 123,
        sessionId: 'abc',
      });
    });

    it('should handle empty metadata objects', () => {
      loggerService.logRequest('GET', '/test', 200, 100, {});

      expect(mockLogger.info).toHaveBeenCalledWith('API Request', {
        method: 'GET',
        url: '/test',
        statusCode: 200,
        responseTime: 100,
      });
    });

    it('should handle null metadata', () => {
      loggerService.logRequest('GET', '/test', 200, 100, null);

      expect(mockLogger.info).toHaveBeenCalledWith('API Request', {
        method: 'GET',
        url: '/test',
        statusCode: 200,
        responseTime: 100,
      });
    });
  });
});
