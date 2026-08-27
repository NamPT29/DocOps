from sqlalchemy import inspect, text


def ensure_project_status_schema(engine) -> None:
    """Normalize legacy project statuses after the projects table exists."""
    if "projects" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE projects SET status = CASE status "
                "WHEN 'configuring' THEN 'new' "
                "WHEN 'importing' THEN 'in_progress' "
                "WHEN 'ready' THEN 'in_progress' "
                "WHEN 'new' THEN 'new' "
                "WHEN 'in_progress' THEN 'in_progress' "
                "WHEN 'completed' THEN 'completed' "
                "WHEN 'overdue' THEN 'overdue' "
                "ELSE 'new' END "
                "WHERE status IS NULL OR status NOT IN "
                "('new', 'in_progress', 'completed', 'overdue')"
            )
        )
