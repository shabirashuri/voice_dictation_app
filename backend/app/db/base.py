from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# BIGINT in Postgres; SQLite only autoincrements an INTEGER PRIMARY KEY.
Id = BigInteger().with_variant(Integer, "sqlite")
