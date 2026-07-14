"""
Reusable DB functions. Routes and agent nodes should go through these
rather than writing raw queries inline, so the query logic (especially
product filtering) lives in exactly one place.
"""

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import (
    Website,
    Product,
    User,
    UserPreference,
    Recommendation,
    Category,
    Gender,
    ALL_ITEM_TYPES,
)
from scraping.cleaner import CleanedProduct


# ---------------------------------------------------------------------------
# Website / Products
# ---------------------------------------------------------------------------

def get_or_create_website(db: Session, url: str) -> Website:
    website = db.query(Website).filter(Website.url == url).first()
    if website:
        website.last_updated_at = datetime.utcnow()
        db.commit()
        db.refresh(website)
        return website

    website = Website(url=url, domain_name=_extract_domain(url))
    db.add(website)
    db.commit()
    db.refresh(website)
    return website


def _extract_domain(url: str) -> str:
    stripped = url.replace("https://", "").replace("http://", "")
    return stripped.split("/")[0]


def save_cleaned_products(
    db: Session, website_id: int, cleaned_products: List[CleanedProduct]
) -> int:
    """
    Inserts cleaned products for a website. Clears out the website's
    previous product rows first, since a re-scrape should reflect the
    current state of the site (prices/stock/deals change) rather than
    accumulating stale duplicates.
    """
    db.query(Product).filter(Product.website_id == website_id).delete()

    count = 0
    for item in cleaned_products:
        db.add(
            Product(
                website_id=website_id,
                name=item.name,
                price=item.price,
                category=item.category,
                item_type=item.item_type,
                size=item.size,
                color=item.color,
                deal_info=item.deal_info,
                source_url=item.source_url,
            )
        )
        count += 1

    db.commit()
    return count


def get_available_item_types(db: Session, website_id: int) -> List[str]:
    """
    Returns the list of distinct item_types found in the products table
    for a given website, ordered alphabetically.
    """
    rows = (
        db.query(Product.item_type)
        .filter(Product.website_id == website_id, Product.item_type.isnot(None))
        .distinct()
        .order_by(Product.item_type)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def set_pending_item_types(db: Session, user: User, item_types_str: str) -> User:
    user.pending_item_types = item_types_str
    db.commit()
    db.refresh(user)
    return user


def get_pending_item_types(db: Session, user: User) -> Optional[str]:
    return user.pending_item_types


def clear_pending_item_types(db: Session, user: User) -> User:
    user.pending_item_types = None
    db.commit()
    db.refresh(user)
    return user


def filter_products(
    db: Session,
    website_id: int,
    category: Category,
    item_types: Optional[List[str]] = None,
    shirt_size: Optional[str] = None,
    pant_size: Optional[str] = None,
    max_price_per_item: Optional[float] = None,
) -> Dict[str, List[Product]]:
    """
    Returns candidate products grouped by item_type, filtered by category
    and (where applicable) size, ordered cheapest-first.
    `item_types` controls which groups are returned — defaults to all known
    types if not specified.
    """
    base_query = db.query(Product).filter(
        Product.website_id == website_id,
        Product.category == category,
    )
    if max_price_per_item is not None:
        base_query = base_query.filter(Product.price <= max_price_per_item)

    types_to_query = item_types if item_types else ALL_ITEM_TYPES
    grouped: Dict[str, List[Product]] = {}

    for item_type in types_to_query:
        query = base_query.filter(Product.item_type == item_type)
        if item_type == "shirt" and shirt_size:
            query = query.filter((Product.size == shirt_size) | (Product.size.is_(None)))
        if item_type == "pant" and pant_size:
            query = query.filter((Product.size == pant_size) | (Product.size.is_(None)))
        if item_type == "jean" and pant_size:
            query = query.filter((Product.size == pant_size) | (Product.size.is_(None)))

        grouped[item_type] = query.order_by(Product.price.asc()).all()

    return grouped


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_session(db: Session, session_id: str) -> Optional[User]:
    return db.query(User).filter(User.session_id == session_id).first()


def get_or_create_user(
    db: Session,
    session_id: str,
    name: str,
    gender: Gender,
    phone: Optional[str] = None,
) -> User:
    user = get_user_by_session(db, session_id)
    if user:
        user.name = name
        user.gender = gender
        if phone:
            user.phone = phone
        db.commit()
        db.refresh(user)
        return user

    user = User(session_id=session_id, name=name, phone=phone, gender=gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Preferences (one row per "qualification round")
# ---------------------------------------------------------------------------

def create_preference(
    db: Session,
    user_id: int,
    category: Category,
    budget: float,
    item_types: Optional[str] = None,
    age: Optional[int] = None,
    height_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
    waist_in: Optional[float] = None,
) -> UserPreference:
    pref = UserPreference(
        user_id=user_id,
        category=category,
        budget=budget,
        item_types=item_types,
        age=age,
        height_cm=height_cm,
        weight_kg=weight_kg,
        waist_in=waist_in,
    )
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def update_preference_sizes(
    db: Session, preference_id: int, shirt_size: str, pant_size: str
) -> UserPreference:
    pref = db.query(UserPreference).get(preference_id)
    pref.computed_shirt_size = shirt_size
    pref.computed_pant_size = pant_size
    db.commit()
    db.refresh(pref)
    return pref


def mark_preference_ready(db: Session, preference_id: int, ready: bool = True) -> UserPreference:
    pref = db.query(UserPreference).get(preference_id)
    pref.is_ready = 1 if ready else 0
    db.commit()
    db.refresh(pref)
    return pref


def get_latest_preference(db: Session, user_id: int) -> Optional[UserPreference]:
    return (
        db.query(UserPreference)
        .filter(UserPreference.user_id == user_id)
        .order_by(UserPreference.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def save_recommendation(
    db: Session,
    user_id: int,
    preference_id: Optional[int],
    product_ids: List[int],
    generated_text: str,
    total_price: Optional[float],
) -> Recommendation:
    rec = Recommendation(
        user_id=user_id,
        preference_id=preference_id,
        product_ids=",".join(str(pid) for pid in product_ids),
        generated_text=generated_text,
        total_price=total_price,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec
