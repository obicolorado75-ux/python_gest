"""Base déclarative et types partagés."""
from sqlalchemy import Integer
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Montants en entiers XOF (§1.2) — jamais de flottants.
XOF = Integer
