-- Development database initialization script
-- Creates test database and enables extensions

-- Create test database
CREATE DATABASE personal_management_test;

-- Enable extensions on main database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
