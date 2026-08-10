from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from datetime import datetime
from server.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False) # Plain text per user request
    role = Column(String(255), default="user") # 'admin' or 'user'
    created_at = Column(DateTime, default=datetime.utcnow)

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    config_json = Column(Text, nullable=True) # Lưu cấu hình JSON của biểu mẫu

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True) # Which template this task is for
    title = Column(String(255), nullable=False)
    target_quantity = Column(Integer, nullable=False)
    current_quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(255), default="in_progress") # in_progress, completed

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Store the dynamically filled JSON
    data_json = Column(Text, nullable=False)
    
    # Track which template this belongs to
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    
    # Track which user created this submission
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Track admin check status
    is_checked = Column(Boolean, default=False)
    
    # Workflow status: draft, pending_review, rejected, approved
    status = Column(String(50), default="draft")

class AssignedDocument(Base):
    __tablename__ = "assigned_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    uuid_filename = Column(String(255), nullable=False, unique=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True) # null = unassigned
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    status = Column(String(255), default="pending") # pending, assigned, completed
    created_at = Column(DateTime, default=datetime.utcnow)

from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint

class Dictionary(Base):
    __tablename__ = "dictionaries"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    name = Column(String(100), index=True, nullable=False) # e.g. "DM_DanToc"
    description = Column(String(255), nullable=True) # e.g. "Dân tộc"
    
    __table_args__ = (UniqueConstraint('template_id', 'name', name='uix_template_dict_name'),)
    
    items = relationship("DictionaryItem", back_populates="dictionary", cascade="all, delete-orphan")

class DictionaryItem(Base):
    __tablename__ = "dictionary_items"

    id = Column(Integer, primary_key=True, index=True)
    dictionary_id = Column(Integer, ForeignKey("dictionaries.id"))
    code = Column(String(50), nullable=True)  # e.g. "1" or "01"
    value = Column(String(255), nullable=False) # e.g. "Kinh"
    
    dictionary = relationship("Dictionary", back_populates="items")
