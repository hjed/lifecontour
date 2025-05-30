import { NodeSDK } from '@opentelemetry/sdk-node';

// Create mock SDK instance
const mockSDK = {
  start: jest.fn(),
  shutdown: jest.fn().mockResolvedValue(undefined),
} as any;

// Mock OpenTelemetry modules
jest.mock('@opentelemetry/sdk-node', () => {
  return {
    NodeSDK: jest.fn(() => mockSDK),
  };
});
jest.mock('@opentelemetry/auto-instrumentations-node', () => ({
  getNodeAutoInstrumentations: jest.fn(() => []),
}));
jest.mock('@opentelemetry/resources', () => ({
  Resource: jest.fn().mockImplementation(attributes => ({ attributes })),
}));
jest.mock('@opentelemetry/semantic-conventions', () => ({
  SemanticResourceAttributes: {
    SERVICE_NAME: 'service.name',
    SERVICE_VERSION: 'service.version',
    DEPLOYMENT_ENVIRONMENT: 'deployment.environment',
  },
}));

describe('OpenTelemetry Instrumentation', () => {
  let originalEnv: NodeJS.ProcessEnv;
  let originalExit: typeof process.exit;

  beforeEach(() => {
    // Save original environment and process.exit
    originalEnv = { ...process.env };
    originalExit = process.exit;

    // Mock process.exit to prevent actual exit
    process.exit = jest.fn() as any;

    // Clear module cache to ensure fresh imports
    jest.resetModules();

    // Clear all mocks but re-setup the NodeSDK mock
    jest.clearAllMocks();
    (NodeSDK as jest.MockedClass<typeof NodeSDK>).mockImplementation(() => mockSDK);
  });

  afterEach(() => {
    // Restore original environment and process.exit
    process.env = originalEnv;
    process.exit = originalExit;

    // Clear all mocks
    jest.clearAllMocks();
  });

  describe('SDK Initialization', () => {
    it('should start the SDK after initialization', async () => {
      await import('../instrumentation');

      expect(mockSDK.start).toHaveBeenCalledTimes(1);
    });

    it('should export the SDK instance', async () => {
      const instrumentation = await import('../instrumentation');

      expect(instrumentation.default).toBeDefined();
    });
  });

  describe('Auto-instrumentations Configuration', () => {
    it('should configure HTTP instrumentation', async () => {
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      expect(getNodeAutoInstrumentations).toHaveBeenCalledWith(
        expect.objectContaining({
          '@opentelemetry/instrumentation-http': expect.objectContaining({
            enabled: true,
            requestHook: expect.any(Function),
          }),
          '@opentelemetry/instrumentation-fastify': expect.objectContaining({
            enabled: true,
          }),
        })
      );
    });

    it('should disable filesystem instrumentation in non-production environments', async () => {
      process.env.NODE_ENV = 'development';
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      expect(getNodeAutoInstrumentations).toHaveBeenCalledWith(
        expect.objectContaining({
          '@opentelemetry/instrumentation-fs': expect.objectContaining({
            enabled: false,
          }),
        })
      );
    });

    it('should enable filesystem instrumentation in production', async () => {
      process.env.NODE_ENV = 'production';
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      expect(getNodeAutoInstrumentations).toHaveBeenCalledWith(
        expect.objectContaining({
          '@opentelemetry/instrumentation-fs': expect.objectContaining({
            enabled: true,
          }),
        })
      );
    });
  });

  describe('HTTP Request Hook', () => {
    it('should configure request hook for HTTP instrumentation', async () => {
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      const callArgs = (getNodeAutoInstrumentations as jest.Mock).mock.calls[0][0];
      const httpConfig = callArgs['@opentelemetry/instrumentation-http'];

      expect(httpConfig.requestHook).toBeDefined();
      expect(typeof httpConfig.requestHook).toBe('function');
    });

    it('should add user-agent attribute to spans when available', async () => {
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      const callArgs = (getNodeAutoInstrumentations as jest.Mock).mock.calls[0][0];
      const requestHook = callArgs['@opentelemetry/instrumentation-http'].requestHook;

      const mockSpan = {
        setAttributes: jest.fn(),
      };

      const mockRequest = {
        headers: {
          'user-agent': 'test-browser/1.0',
        },
      };

      requestHook(mockSpan, mockRequest);

      expect(mockSpan.setAttributes).toHaveBeenCalledWith({
        'http.request.header.user-agent': 'test-browser/1.0',
      });
    });

    it('should handle requests without user-agent header', async () => {
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      const callArgs = (getNodeAutoInstrumentations as jest.Mock).mock.calls[0][0];
      const requestHook = callArgs['@opentelemetry/instrumentation-http'].requestHook;

      const mockSpan = {
        setAttributes: jest.fn(),
      };

      const mockRequest = {
        headers: {},
      };

      requestHook(mockSpan, mockRequest);

      expect(mockSpan.setAttributes).toHaveBeenCalledWith({
        'http.request.header.user-agent': 'unknown',
      });
    });

    it('should handle requests without headers', async () => {
      const { getNodeAutoInstrumentations } = await import(
        '@opentelemetry/auto-instrumentations-node'
      );

      await import('../instrumentation');

      const callArgs = (getNodeAutoInstrumentations as jest.Mock).mock.calls[0][0];
      const requestHook = callArgs['@opentelemetry/instrumentation-http'].requestHook;

      const mockSpan = {
        setAttributes: jest.fn(),
      };

      const mockRequest = {};

      // Should not throw an error
      expect(() => requestHook(mockSpan, mockRequest)).not.toThrow();
    });
  });

  describe('Graceful Shutdown', () => {
    it('should register SIGTERM handler for graceful shutdown', async () => {
      const originalOn = process.on;
      const mockOn = jest.fn();
      process.on = mockOn;

      await import('../instrumentation');

      expect(mockOn).toHaveBeenCalledWith('SIGTERM', expect.any(Function));

      // Restore original process.on
      process.on = originalOn;
    });

    it('should have shutdown method available on SDK', async () => {
      await import('../instrumentation');

      expect(mockSDK.shutdown).toBeDefined();
      expect(typeof mockSDK.shutdown).toBe('function');
    });
  });
});
