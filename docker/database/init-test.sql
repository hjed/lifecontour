-- Database initialization script for Lifecontour tests
-- Sets up extensions for the test database

-- Set timezone to UTC for consistency
SET timezone = 'UTC';

-- Enable necessary extensions for test database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
