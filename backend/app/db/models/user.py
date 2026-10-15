from sqlalchemy import Column, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.base import Base, Id


class User(Base):
    """A doctor account. Emails are stored lower-cased."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id = Column(Id, primary_key=True, autoincrement=True)
    email = Column(String(320), nullable=False)
    full_name = Column(String(200), nullable=False)
    password_hash = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    cases = relationship("Case", back_populates="owner")
