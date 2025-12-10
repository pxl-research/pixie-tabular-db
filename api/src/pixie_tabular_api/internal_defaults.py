"""Internal defaults for service-to-service configuration.

These values are not meant for end users; they keep API and DB aligned inside
the tabular stack. Adjust here if the internal wiring changes.
"""

DEFAULT_POSTGRES = {
    "db": "pixie_tabular",
    "user": "pixie",
    "password": "devpassword",
    "host": "tabular-db",
    "port": 5432,
}


__all__ = ["DEFAULT_POSTGRES"]
