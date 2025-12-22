-- Database initialization script for Personal Management System
-- Sets up extensions for the main database

-- Set timezone to UTC for consistency
SET timezone = 'UTC';

-- Enable necessary extensions in the default postgres database
-- (The main database will be created by docker-compose and will inherit these)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
