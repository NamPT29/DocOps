from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./scan_to_excel.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Store the entire 186 columns as a JSON string to easily support schema changes
    data_json = Column(String, nullable=False)
    
    # Keep track of which template this belongs to
    template_name = Column(String, default="Excel_FormMau_v5_04082026.xlsx")

# Create tables
Base.metadata.create_all(bind=engine)
