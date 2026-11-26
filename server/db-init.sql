-- Run by the db_init service in docker-compose-traefik.yml (psql variables: db, usr, pw).
-- Creates the sync server's login and database on the shared Postgres; safe to run again.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'usr', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'usr') \gexec

-- Keep the password in step with server/.env if it was changed.
SELECT format('ALTER ROLE %I PASSWORD %L', :'usr', :'pw') \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'usr')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
