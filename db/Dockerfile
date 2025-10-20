FROM postgres:18-alpine

# Copy the initialization SQL script into the default bootstrap directory so
# the database schema is created automatically on first run.
COPY init.sql /docker-entrypoint-initdb.d/init.sql
