"""
Investments blueprint — activate plans, referral commission engine.
URL prefix: /investments
"""
from datetime import datetime, timezone
from flask import Blueprint, request, redirect, url_for, session, flash
from config import Config
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

investments_bp = Blueprint('investments', __name__)


# ── Referral commission helper ────────────────────────────────────────────────

def pay_referral_commissions(db, user_id: str, amount: float, tx_type: str = 'deposit'):
    """
    Called after a deposit is approved or a plan is activated.
    Credits L1 (5%) and L2 (2%) referrers instantly.
    """
    try:
        res = db.table('profiles') \
            .select('referred_by, referred_by_l2') \
            .eq('id', user_id).execute()
        profile = res.data[0] if res.data else None

        if not profile:
            print(f"=== REFERRAL: no profile found for {user_id} ===")
            return

        now = datetime.now(timezone.utc).isoformat()

        def _credit(referrer_id, rate, level):
            try:
                bonus = round(amount * rate, 2)
                ref_res = db.table('profiles').select('balance') \
                    .eq('id', referrer_id).execute()
                ref_profile = ref_res.data[0] if ref_res.data else None
                if not ref_profile:
                    return
                new_bal = round(ref_profile['balance'] + bonus, 2)
                db.table('profiles').update(
                    {'balance': new_bal}
                ).eq('id', referrer_id).execute()
                db.table('transactions').insert({
                    'user_id':     referrer_id,
                    'type':        'referral_bonus',
                    'amount':      bonus,
                    'description': f'Level {level} referral commission ({int(rate*100)}%) on ${amount} {tx_type}',
                    'status':      'completed',
                    'ref_user_id': user_id,
                    'created_at':  now,
                }).execute()
                print(f"=== REFERRAL L{level} credited {bonus} to {referrer_id} ===")
            except Exception as e:
                print(f"=== REFERRAL _credit ERROR L{level}: {e} ===")

        l1 = profile.get('referred_by')
        l2 = profile.get('referred_by_l2')

        if l1:
            _credit(l1, Config.REFERRAL_L1_RATE, 1)
        if l2:
            _credit(l2, Config.REFERRAL_L2_RATE, 2)

    except Exception as e:
        print(f"=== REFERRAL COMMISSION ERROR: {e} ===")


# ── Activate plan ─────────────────────────────────────────────────────────────

@investments_bp.route('/activate', methods=['POST'])
@login_required
def activate():
    db      = get_admin_supabase()
    uid     = session['user_id']
    plan_id = int(request.form.get('plan_id', 0))

    try:
        print(f"=== ACTIVATE START uid={uid} plan_id={plan_id} ===")

        plan = Config.INVESTMENT_PLANS.get(plan_id)
        if not plan:
            flash('Invalid investment plan.', 'error')
            return redirect(url_for('dashboard.index'))

        profile_res = db.table('profiles').select('balance').eq('id', uid).execute()
        profile = profile_res.data[0] if profile_res.data else None
        if not profile:
            flash('Profile not found.', 'error')
            return redirect(url_for('dashboard.index'))

        print(f"=== BALANCE={profile['balance']} PLAN={plan['amount']} ===")

        if profile['balance'] < plan['amount']:
            flash(f"Insufficient balance. You need ${plan['amount']} to activate this plan.", 'error')
            return redirect(url_for('dashboard.index'))

        now = datetime.now(timezone.utc)
        new_balance = round(profile['balance'] - plan['amount'], 2)

        print("=== UPDATING BALANCE ===")
        db.table('profiles').update(
            {'balance': new_balance}
        ).eq('id', uid).execute()

        print("=== INSERTING INVESTMENT ===")
        db.table('investments').insert({
            'user_id':          uid,
            'plan_id':          plan_id,
            'plan_name':        plan['name'],
            'amount':           plan['amount'],
            'daily_rate':       plan['daily_rate'],
            'status':           'active',
            'start_date':       now.isoformat(),
            'last_profit_date': None,
            'total_earned':     0.0,
            'created_at':       now.isoformat(),
        }).execute()

        print("=== INSERTING TRANSACTION ===")
        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'investment',
            'amount':      plan['amount'],
            'description': f"Activated {plan['name']} Plan (${plan['amount']})",
            'status':      'completed',
            'created_at':  now.isoformat(),
        }).execute()

        print("=== PAYING REFERRAL ===")
        try:
            pay_referral_commissions(db, uid, plan['amount'], tx_type='investment')
        except Exception as e:
            print(f"=== REFERRAL ERROR: {e} ===")

        print("=== ACTIVATE DONE ===")
        flash(f"{plan['name']} Plan activated! You will earn 2% daily.", 'success')
        return redirect(url_for('dashboard.index'))

    except Exception as e:
        print(f"=== ACTIVATE EXCEPTION: {e} ===")
        flash(f'Activation error: {e}', 'error')
        return redirect(url_for('dashboard.index'))
