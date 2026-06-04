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
    # CORRECT: first arg is the ENV VAR NAME, second is the default value
    SUPABASE_URL         = os.environ.get('SUPABASE_URL',         'https://dwpqshayuuivlmuvmpsb.supabase.co')
    SUPABASE_ANON_KEY    = os.environ.get('SUPABASE_ANON_KEY',    'sb_publishable_XqkNeTKirUWG3f8qi-bk6g_uzTgDtiu')
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', 'YOUR_SERVICE_ROLE_KEY_HERE')

    # ── Admin ──────────────────────────────────────────────────
    ADMIN_EMAIL    = os.environ.get('ADMIN_EMAIL',    'bonheurrobert701@gmail.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Aaa111@@@')

    # ── Platform ───────────────────────────────────────────────
    DAILY_PROFIT_RATE = 0.02
    REFERRAL_L1_RATE  = 0.05
    REFERRAL_L2_RATE  = 0.02

    INVESTMENT_PLANS = {
        0: {'name': 'Mini',    'amount': 4,    'daily_rate': 0.02},
        1: {'name': 'Starter', 'amount': 50,   'daily_rate': 0.02},
        2: {'name': 'Basic',   'amount': 100,  'daily_rate': 0.02},
        3: {'name': 'Pro',     'amount': 500,  'daily_rate': 0.02},
        4: {'name': 'Elite',   'amount': 1000, 'daily_rate': 0.02},
    }

    USDT_TRC20_ADDRESS = 'TNjKythwpkcPQo5XwckeBC4ZyeKZf7HaJ2'
    USDT_BEP20_ADDRESS = '0x2ba88a4d6cabaded5d06c75ef3b3efec386acaef'
    WHATSAPP_NUMBER    = '50941727986'
