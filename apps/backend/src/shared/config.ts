import { z } from 'zod';
import { singleton } from 'tsyringe';

// Configuration schema with validation
const configSchema = z.object({
  // Environment
  nodeEnv: z.enum(['development', 'test', 'staging', 'production']).default('development'),

  // Server configuration
  server: z.object({
    port: z.coerce.number().int().min(1).max(65535).default(3001),
    host: z.string().default('0.0.0.0'),
    trustProxy: z.boolean().default(true),
  }),

  // Database configuration
  database: z.object({
    url: z.string().default('./data/database.sqlite'),
    enableWAL: z.boolean().default(true),
    busyTimeout: z.coerce.number().int().min(1000).default(5000),
  }),

  // Logging configuration
  logging: z.object({
    level: z.enum(['error', 'warn', 'info', 'debug']).default('info'),
    format: z.enum(['json', 'simple']).default('json'),
    enableConsole: z.boolean().default(true),
    enableFile: z.boolean().default(false),
    filename: z.string().optional(),
  }),

  // CORS configuration
  cors: z.object({
    origin: z.union([z.string(), z.array(z.string())]).default('http://localhost:3000'),
    credentials: z.boolean().default(true),
  }),

  // Rate limiting
  rateLimit: z.object({
    windowMs: z.coerce
      .number()
      .int()
      .min(1000)
      .default(15 * 60 * 1000), // 15 minutes
    maxRequests: z.coerce.number().int().min(1).default(100),
  }),

  // API configuration
  api: z.object({
    prefix: z.string().default('/api/v1'),
    timeout: z.coerce.number().int().min(1000).default(30000), // 30 seconds
  }),

  // Security
  security: z.object({
    sessionSecret: z.string().min(32).default('your-super-secret-session-key-change-in-production'),
    csrfEnabled: z.boolean().default(true),
  }),
});

// Load and validate configuration
const loadConfig = () => {
  const rawConfig = {
    nodeEnv: process.env.NODE_ENV,
    server: {
      port: process.env.PORT ?? process.env.SERVER_PORT,
      host: process.env.HOST ?? process.env.SERVER_HOST,
      trustProxy: process.env.TRUST_PROXY === 'true',
    },
    database: {
      url: process.env.DATABASE_URL,
      enableWAL: process.env.DATABASE_ENABLE_WAL !== 'false',
      busyTimeout: process.env.DATABASE_BUSY_TIMEOUT,
    },
    logging: {
      level: process.env.LOG_LEVEL,
      format: process.env.LOG_FORMAT,
      enableConsole: process.env.LOG_ENABLE_CONSOLE !== 'false',
      enableFile: process.env.LOG_ENABLE_FILE === 'true',
      filename: process.env.LOG_FILENAME,
    },
    cors: {
      origin: process.env.CORS_ORIGIN
        ? process.env.CORS_ORIGIN.split(',').map(origin => origin.trim())
        : undefined,
      credentials: process.env.CORS_CREDENTIALS !== 'false',
    },
    rateLimit: {
      windowMs: process.env.RATE_LIMIT_WINDOW_MS,
      maxRequests: process.env.RATE_LIMIT_MAX_REQUESTS,
    },
    api: {
      prefix: process.env.API_PREFIX,
      timeout: process.env.API_TIMEOUT,
    },
    security: {
      sessionSecret: process.env.SESSION_SECRET,
      csrfEnabled: process.env.CSRF_ENABLED !== 'false',
    },
  };

  try {
    return configSchema.parse(rawConfig);
  } catch (error) {
    console.error('Configuration validation failed:', error);
    process.exit(1);
  }
};

@singleton()
export class ConfigService {
  private readonly _config = loadConfig();

  get config() {
    return this._config;
  }

  get isDevelopment() {
    return this._config.nodeEnv === 'development';
  }

  get isProduction() {
    return this._config.nodeEnv === 'production';
  }

  get isTest() {
    return this._config.nodeEnv === 'test';
  }
}

// Load and export config with helper properties
const _config = loadConfig();

export const config = {
  ..._config,
  get isDevelopment() {
    return _config.nodeEnv === 'development';
  },
  get isProduction() {
    return _config.nodeEnv === 'production';
  },
  get isTest() {
    return _config.nodeEnv === 'test';
  },
};

export type Config = typeof config;
