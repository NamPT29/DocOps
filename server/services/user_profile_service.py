from sqlalchemy import inspect, text


_USER_PROFILE_COLUMNS = {
    "full_name": "VARCHAR(255) NULL",
    "phone_number": "VARCHAR(50) NULL",
    "max_concurrent_sessions": "INTEGER NOT NULL DEFAULT 1",
}


def ensure_user_profile_schema(engine) -> None:
    """Add profile fields to legacy user tables and populate safe display names."""
    inspector = inspect(engine)
    if "users" not in set(inspector.get_table_names()):
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("users")
    }
    with engine.begin() as connection:
        for column_name, column_ddl in _USER_PROFILE_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(text(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_ddl}"
                ))
        connection.execute(text(
            "UPDATE users SET full_name = username "
            "WHERE full_name IS NULL OR TRIM(full_name) = ''"
        ))
        connection.execute(text(
            "UPDATE users SET max_concurrent_sessions = 1 "
            "WHERE max_concurrent_sessions IS NULL OR max_concurrent_sessions < 1"
        ))
