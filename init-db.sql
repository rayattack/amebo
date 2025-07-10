-- Initialize Amebo database
-- This script will be run when the PostgreSQL container starts for the first time

-- Create the amebo database if it doesn't exist (handled by POSTGRES_DB env var)
-- Create the amebo user if it doesn't exist (handled by POSTGRES_USER env var)

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON DATABASE amebo TO amebo;

-- Connect to the amebo database
\c amebo;

-- Create the _amebo_ schema
CREATE SCHEMA IF NOT EXISTS _amebo_;

-- Set search path
SET search_path TO _amebo_;

-- Grant schema permissions
GRANT ALL ON SCHEMA _amebo_ TO amebo;
GRANT ALL ON ALL TABLES IN SCHEMA _amebo_ TO amebo;
GRANT ALL ON ALL SEQUENCES IN SCHEMA _amebo_ TO amebo;

-- The actual table creation will be handled by the amebo application
-- when it starts up via the pgscript in amebo/database/pg.py
