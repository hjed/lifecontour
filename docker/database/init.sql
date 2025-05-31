-- Database initialization script for Personal Management System
-- Creates the test database and sets up initial configuration

-- Set timezone to UTC for consistency
SET timezone = 'UTC';

-- Create test database (main database is created by docker-compose)
CREATE DATABASE personal_management_test;

-- Connect to main database to set up extensions
\c personal_management;

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Connect to test database to set up extensions
\c personal_management_test;

-- Enable necessary extensions for test database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
