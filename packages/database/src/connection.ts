import Database, { type Database as DatabaseType } from 'better-sqlite3';
import { drizzle } from 'drizzle-orm/better-sqlite3';
import { migrate } from 'drizzle-orm/better-sqlite3/migrator';
// Schema will be imported as we build each domain
// import * as schema from './schema/index.js';
import { DATABASE_CONSTANTS } from '@personal-management/shared';

// Database configuration
const getDatabasePath = (): string => {
  const env = process.env.NODE_ENV ?? 'development';

  switch (env) {
    case 'test':
      return ':memory:'; // In-memory database for tests
    case 'production':
      return process.env.DATABASE_URL ?? '/data/database.sqlite';
    default:
      return process.env.DATABASE_URL ?? './data/database.sqlite';
  }
};

// Create SQLite connection
const sqlite: DatabaseType = new Database(getDatabasePath(), {
  verbose: process.env.NODE_ENV === 'development' ? console.log : undefined,
});

// Configure SQLite for optimal performance and safety
sqlite.pragma('journal_mode = WAL');
sqlite.pragma('synchronous = NORMAL');
sqlite.pragma('foreign_keys = ON');
sqlite.pragma(`busy_timeout = ${DATABASE_CONSTANTS.DEFAULT_BUSY_TIMEOUT}`);

// Create Drizzle instance (schema will be added as we build domains)
export const db = drizzle(sqlite, {
  logger: process.env.NODE_ENV === 'development',
});

// Migration function
export const runMigrations = async (): Promise<void> => {
  try {
    await migrate(db, { migrationsFolder: './src/migrations' });
    console.log('Database migrations completed successfully');
  } catch (error) {
    console.error('Database migration failed:', error);
    throw error;
  }
};

// Database health check
export const checkDatabaseHealth = (): boolean => {
  try {
    const result = sqlite.prepare('SELECT 1 as health').get() as { health: number };
    return result.health === 1;
  } catch (error) {
    console.error('Database health check failed:', error);
    return false;
  }
};

// Graceful shutdown
export const closeDatabaseConnection = (): void => {
  try {
    sqlite.close();
    console.log('Database connection closed');
  } catch (error) {
    console.error('Error closing database connection:', error);
  }
};

// Handle process termination
process.on('SIGINT', closeDatabaseConnection);
process.on('SIGTERM', closeDatabaseConnection);
process.on('exit', closeDatabaseConnection);

// Export with proper typing
export { sqlite };
export type { DatabaseType };
