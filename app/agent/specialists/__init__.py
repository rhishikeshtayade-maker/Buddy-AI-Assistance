"""BUDDY Specialist Roles (Loop 12)."""

from app.agent.specialists.base import BaseSpecialist
from app.agent.specialists.browser import BrowserRole
from app.agent.specialists.coder import CoderRole
from app.agent.specialists.computer import ComputerRole
from app.agent.specialists.researcher import ResearcherRole
from app.agent.specialists.verifier import VerifierRole

__all__ = [
    "BaseSpecialist",
    "ResearcherRole",
    "CoderRole",
    "BrowserRole",
    "ComputerRole",
    "VerifierRole",
]
