"""Utilities for generating unique slugs."""
import re
from sqlalchemy import select


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "unnamed"


async def make_unique_slug(base: str, db, model_class, exclude_id=None, tenant_id=None) -> str:
    """Generate a slug unique within the tenant (tenant-less rows keep the
    platform-wide scope via the partial global index)."""
    slug = slugify(base)
    candidate = slug
    counter = 1
    while True:
        q = select(model_class).where(model_class.slug == candidate)
        if tenant_id is not None or hasattr(model_class, "tenant_id"):
            q = q.where(model_class.tenant_id == tenant_id)
        if exclude_id is not None:
            q = q.where(model_class.id != exclude_id)
        result = await db.execute(q)
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{slug}-{counter}"
        counter += 1
