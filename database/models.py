"""
SQLAlchemy ORM models for the AI Shopping Assistant.

Five tables, matching the design discussed:
    - Website          one row per scraped domain
    - Product           cleaned/scraped catalog items, linked to a Website
    - User               greeting/profile info collected by the frontend chat
    - UserPreference     category + measurements + budget + computed size
    - Recommendation    logged LLM recommendation output

Field names here map 1:1 onto what the frontend already sends:
    userProfile.name, userProfile.phone, userProfile.gender, userProfile.category
    formAge, formHeight, formWeight, formWaist, formBudget
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    Enum,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# All known item types used across the app (cleaner, CRUD, agents).
# Centralized here so every module reads from the same source of truth.
ALL_ITEM_TYPES = [
    "shirt", "pant", "jean", "shoes", "jacket", "hoodie", "sweater",
    "blazer", "suit", "shorts", "trunks", "kurta", "polo", "t-shirt",
    "trouser", "chino", "sneaker", "loafer", "boot", "watch",
    "accessory", "bag", "belt", "cap", "socks", "innerwear", "other",
]


# ---------------------------------------------------------------------------
# Enums — kept as plain string enums so they serialize cleanly to/from the
# frontend's quick-reply button values without any translation layer.
# ---------------------------------------------------------------------------

class Gender(str, PyEnum):
    MALE = "Men"
    FEMALE = "Women"


class Category(str, PyEnum):
    CASUAL = "Casual"
    FORMAL = "Formal"
    SMART_CASUAL = "Smart Casual"
    SPORTSWEAR = "Sportswear"
    PARTY_WEAR = "Party Wear"
    OFFICE_WEAR = "Office Wear"
    ETHNIC_WEAR = "Ethnic/Traditional Wear"
    OTHER = "Other"


# ---------------------------------------------------------------------------
# Website — one row per scraped domain (created by POST /api/scrape)
# ---------------------------------------------------------------------------

class Website(Base):
    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(500), nullable=False, unique=True)
    domain_name = Column(String(255), nullable=True)  # e.g. "breakout.com.pk"
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    products = relationship("Product", back_populates="website", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Website id={self.id} url={self.url!r}>"


# ---------------------------------------------------------------------------
# Product — cleaned, scraped catalog items
# ---------------------------------------------------------------------------

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    # Stored as plain text (e.g. "S", "M", "32") rather than a fixed enum —
    # shirt sizes (S/M/L) and pant sizes (28/30/32...) don't share one scale.
    size = Column(String(20), nullable=True)
    color = Column(String(50), nullable=True)
    category = Column(Enum(Category), nullable=False)
    # "shirt" / "pant" / "shoes" — needed so the Recommendation Agent can
    # assemble one of each rather than three random category matches.
    item_type = Column(String(30), nullable=True)

    price = Column(Float, nullable=False)
    in_stock = Column(Integer, default=1)  # 1 = true, 0 = false (SQLite-friendly boolean)

    deal_info = Column(String(255), nullable=True)   # e.g. "10% off"
    deal_expiry = Column(DateTime, nullable=True)     # null if no active deal

    source_url = Column(String(500), nullable=True)  # direct product page link, if scraped
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    website = relationship("Website", back_populates="products")

    def __repr__(self):
        return f"<Product id={self.id} name={self.name!r} price={self.price}>"


# ---------------------------------------------------------------------------
# User — profile info collected during PROFILE_NAME / PROFILE_PHONE steps
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, unique=True)  # matches frontend sessionId
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True, unique=True)  # optional/skippable, but unique when given
    gender = Column(Enum(Gender), nullable=False)
    # Pending item types selected by the user (comma-separated), survives
    # turns when the frontend doesn't resend them.
    pending_item_types = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# UserPreference — category + measurements + budget + computed size
# One row per "qualification round" — a new row is added each time the user
# changes category/budget, so history of what was asked/recommended is kept.
# ---------------------------------------------------------------------------

class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    category = Column(Enum(Category), nullable=False)

    # Item types the user wants (comma-separated, e.g. "shirt,pant,shoes")
    # Populated by the qualification agent after asking the user what they want.
    item_types = Column(String(200), nullable=True)

    age = Column(Integer, nullable=True)
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    waist_in = Column(Float, nullable=True)
    budget = Column(Float, nullable=False)

    # Filled in by sizing/size_calculator.py once measurements are present —
    # this is what the Recommendation Agent actually filters products on.
    computed_shirt_size = Column(String(10), nullable=True)   # e.g. "M"
    computed_pant_size = Column(String(10), nullable=True)    # e.g. "32"

    is_ready = Column(Integer, default=0)  # 1 once Qualification Agent marks this round complete
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="preferences")
    recommendations = relationship("Recommendation", back_populates="preference")

    def __repr__(self):
        return f"<UserPreference id={self.id} user_id={self.user_id} category={self.category}>"


# ---------------------------------------------------------------------------
# Recommendation — logged LLM output, linked back to the preference round
# that produced it
# ---------------------------------------------------------------------------

class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    preference_id = Column(Integer, ForeignKey("user_preferences.id", ondelete="SET NULL"), nullable=True)

    # Comma-separated product IDs actually recommended (shirt/pant/shoes),
    # kept simple rather than a many-to-many join table for now.
    product_ids = Column(String(100), nullable=True)

    generated_text = Column(Text, nullable=False)  # the formatted LLM answer shown in chat
    total_price = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="recommendations")
    preference = relationship("UserPreference", back_populates="recommendations")

    def __repr__(self):
        return f"<Recommendation id={self.id} user_id={self.user_id}>"


# ---------------------------------------------------------------------------
# Helpful composite constraints
# ---------------------------------------------------------------------------

UniqueConstraint(Website.url, name="uq_website_url")
