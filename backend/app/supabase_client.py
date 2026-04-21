from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from backend.app.config import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)
