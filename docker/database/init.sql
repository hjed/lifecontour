-- Database initialization script for Lifecontour
-- Sets up extensions for all databases (dev, test, prod)

-- Set timezone to UTC for consistency
SET timezone = 'UTC';

-- Create development database if it doesn't exist
SELECT 'CREATE DATABASE personal_management'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'personal_management')\gexec

-- Create test database if it doesn't exist
SELECT 'CREATE DATABASE personal_management_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'personal_management_test')\gexec

-- Connect to development database and set up extensions
\c personal_management
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Connect to test database and set up extensions
\c personal_management_test
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
