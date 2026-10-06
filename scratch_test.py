import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server.database import Base
from server.models import Project
from server.models_entry_qc import CaseEntryQcResult
from sqlalchemy import inspect

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=engine)
insp = inspect(engine)
print(insp.get_table_names())
