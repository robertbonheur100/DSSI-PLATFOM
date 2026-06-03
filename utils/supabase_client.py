from supabase import create_client, Client
from config import Config

_client: Client = None
_admin_client: Client = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)
    return _client


def get_admin_supabase() -> Client:
    """Server-side client — uses service role key, bypasses RLS."""
    global _admin_client
    if _admin_client is None:
        _admin_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
    return _admin_client
