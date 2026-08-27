from sqlalchemy import inspect, text


def ensure_submission_status_schema(engine) -> None:
    """Normalize legacy submission workflow values after all tables exist."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "submissions" not in table_names:
        return

    with engine.begin() as connection:
        if "submission_review_histories" in table_names:
            history_columns = {
                column["name"]
                for column in inspector.get_columns("submission_review_histories")
            }
            history_indexes = {
                index["name"]
                for index in inspector.get_indexes("submission_review_histories")
            }
            if "confirmed_by_user_id" not in history_columns:
                connection.execute(text(
                    "ALTER TABLE submission_review_histories "
                    "ADD COLUMN confirmed_by_user_id INTEGER NULL"
                ))
            if "ix_submission_review_histories_confirmed_by_user_id" not in history_indexes:
                connection.execute(text(
                    "CREATE INDEX ix_submission_review_histories_confirmed_by_user_id "
                    "ON submission_review_histories (confirmed_by_user_id)"
                ))

        connection.execute(text(
            "UPDATE submissions SET status = 'pending_review' "
            "WHERE status = 'rejected'"
        ))

        if "submission_review_histories" in table_names:
            connection.execute(text(
                "UPDATE submissions SET status = CASE "
                "WHEN EXISTS ("
                "SELECT 1 FROM submission_review_histories history "
                "WHERE history.submission_id = submissions.id "
                "AND history.event_type IN "
                "('input_confirmed', 'input_corrected', 'input_correction')"
                ") THEN 'completed' "
                "ELSE 'pending_input_confirmation' END "
                "WHERE status = 'approved'"
            ))
        else:
            connection.execute(text(
                "UPDATE submissions SET status = 'pending_input_confirmation' "
                "WHERE status = 'approved'"
            ))
