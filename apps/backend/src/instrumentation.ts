// OpenTelemetry auto-instrumentation setup
// This must be imported before any other modules

import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { Resource } from '@opentelemetry/resources';
import { SemanticResourceAttributes } from '@opentelemetry/semantic-conventions';

// Initialize OpenTelemetry SDK
const sdk = new NodeSDK({
  resource: new Resource({
    [SemanticResourceAttributes.SERVICE_NAME]: 'personal-management-backend',
    [SemanticResourceAttributes.SERVICE_VERSION]: '1.0.0',
    [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: process.env.NODE_ENV ?? 'development',
  }),
  instrumentations: [
    getNodeAutoInstrumentations({
      // Disable some instrumentations that might be noisy in development
      '@opentelemetry/instrumentation-fs': {
        enabled: process.env.NODE_ENV === 'production',
      },
      '@opentelemetry/instrumentation-http': {
        enabled: true,
        requestHook: (span, request) => {
          // Add custom attributes to HTTP spans
          if ('headers' in request && request.headers) {
            span.setAttributes({
              'http.request.header.user-agent': request.headers['user-agent'] ?? 'unknown',
            });
          }
        },
      },
      '@opentelemetry/instrumentation-fastify': {
        enabled: true,
      },
    }),
  ],
});

// Start the SDK
sdk.start();

// Graceful shutdown
process.on('SIGTERM', () => {
  sdk
    .shutdown()
    .then(() => console.log('OpenTelemetry terminated'))
    .catch((error: unknown) => console.log('Error terminating OpenTelemetry', error))
    .finally(() => process.exit(0));
});

export default sdk;
