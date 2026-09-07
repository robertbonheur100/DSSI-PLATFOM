import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    # ── Flask ──────────────────────────────────────────────────
    SECRET_KEY           = os.environ.get('SECRET_KEY', 'edc-fallback-secret-key')
    SESSION_TYPE         = 'filesystem'
    SESSION_PERMANENT    = False
    SESSION_USE_SIGNER   = True
    SESSION_FILE_DIR     = os.path.join(os.path.dirname(__file__), 'flask_session')
    # ── Supabase ───────────────────────────────────────────────
    SUPABASE_URL         = os.environ.get('SUPABASE_URL',         'https://dwpqshayuuivlmuvmpsb.supabase.co')
    SUPABASE_ANON_KEY    = os.environ.get('SUPABASE_ANON_KEY',    'sb_publishable_XqkNeTKirUWG3f8qi-bk6g_uzTgDtiu')
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', 'YOUR_SERVICE_ROLE_KEY_HERE')
    # ── Admin ──────────────────────────────────────────────────
    ADMIN_EMAIL    = os.environ.get('ADMIN_EMAIL',    'bonheurrobert701@gmail.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Aaa111@@@')
    # ── Platform ───────────────────────────────────────────────
    # Pwofi peye chak MWA. To mansyèl la se 15% pou tout plan yo.
    MONTHLY_PROFIT_RATE = 0.15
    REFERRAL_L1_RATE    = 0.05
    REFERRAL_L2_RATE    = 0.02
    INVESTMENT_PLANS = {
        0: {'name': 'Mini',     'amount': 5000,    'monthly_rate': 0.15},
        1: {'name': 'Starter',  'amount': 10000,   'monthly_rate': 0.15},
        2: {'name': 'Basic',    'amount': 20000,   'monthly_rate': 0.15},
        3: {'name': 'Standard', 'amount': 50000,   'monthly_rate': 0.15},
        4: {'name': 'Pro',      'amount': 100000,  'monthly_rate': 0.15},
        5: {'name': 'VIP',      'amount': 500000,  'monthly_rate': 0.15},
        6: {'name': 'Elite',    'amount': 1000000, 'monthly_rate': 0.15},
    }
    USDT_TRC20_ADDRESS = 'TNjKythwpkcPQo5XwckeBC4ZyeKZf7HaJ2'
    USDT_BEP20_ADDRESS = '0x2ba88a4d6cabaded5d06c75ef3b3efec386acaef'
    WHATSAPP_NUMBER    = '50941727986'
    # ── SMM Panel ────────────────────────────────────────────────
    # NOTE: api_url / api_key pou chak founisè kounye a estoke nan tab
    # `smm_providers` (Supabase), jere nan Admin → Sèvis SMM. Pa gen
    # kle API ki ekri isit la ankò.
    # Chak konbyen minit backend la tcheke/soumèt lòd SMM yo
    SMM_CHECK_INTERVAL_MINUTES = int(os.environ.get('SMM_CHECK_INTERVAL_MINUTES', 20))
