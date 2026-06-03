"""
Referrals blueprint — referral stats page.
URL prefix: /referrals
"""
from flask import Blueprint, render_template, session, request
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

referrals_bp = Blueprint('referrals', __name__)


@referrals_bp.route('/')
@login_required
def index():
    db  = get_admin_supabase()
    uid = session['user_id']

    profile  = db.table('profiles').select('referral_code, username').eq('id', uid).single().execute().data or {}
    l1_refs  = db.table('profiles').select('username, email, created_at').eq('referred_by', uid).execute().data or []
    l2_refs  = db.table('profiles').select('username, email, created_at').eq('referred_by_l2', uid).execute().data or []
    ref_txs  = db.table('transactions').select('*') \
                  .eq('user_id', uid).eq('type', 'referral_bonus') \
                  .order('created_at', desc=True).execute().data or []

    total_earned = sum(t['amount'] for t in ref_txs)
    ref_link     = f"{request.host_url}auth/register?ref={profile.get('referral_code', '')}"

    return render_template('referrals.html',
        profile=profile,
        l1_refs=l1_refs,
        l2_refs=l2_refs,
        ref_txs=ref_txs,
        total_earned=total_earned,
        ref_link=ref_link,
    )
