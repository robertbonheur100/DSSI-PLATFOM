"""
Investments blueprint — activate plans, referral commission engine.
URL prefix: /investments

Plan model: 7% profit credited to the user's balance every month,
for 3 months. At the end of the 3rd month, the principal (the amount
the user invested) is credited back to the balance along with the
final month's interest, so the plan is fully closed out and the user
is free to reinvest.
"""
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from flask import Blueprint, request, redirect, url_for, session, flash
from config import Config
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

investments_bp = Blueprint('investments', __name__)

TERM_MONTHS = 3


# ── Referral commission helper ────────────────────────────────────────────────

def pay_referral_commissions(db, user_id: str, amount: float, tx_type: str = 'deposit'):
    try:
        res = db.table('profiles') \
            .select('referred_by, referred_by_l2') \
            .eq('id', user_id).execute()

        if not res.data:
            return

        profile = res.data[0]

    except Exception as e:
        return

    now = datetime.now(timezone.utc).isoformat()

    def _credit(referrer_id, rate, level):
        try:
            bonus = round(amount * rate, 2)
            ref_res = db.table('profiles').select('balance').eq('id', referrer_id).execute()
            if not ref_res.data:
                return
            new_bal = round(float(ref_res.data[0]['balance']) + bonus, 2)
            db.table('profiles').update({'balance': new_bal}).eq('id', referrer_id).execute()
            db.table('transactions').insert({
                'user_id':     referrer_id,
                'type':        'referral_bonus',
                'amount':      bonus,
                'description': f'Level {level} referral commission ({int(rate*100)}%) on ${amount} {tx_type}',
                'status':      'completed',
                'ref_user_id': user_id,
                'created_at':  now,
            }).execute()
        except Exception as e:
            pass

    l1 = profile.get('referred_by')
    l2 = profile.get('referred_by_l2')

    if l1:
        _credit(l1, Config.REFERRAL_L1_RATE, 1)
    if l2:
        _credit(l2, Config.REFERRAL_L2_RATE, 2)


# ── Activate plan ─────────────────────────────────────────────────────────────

@investments_bp.route('/activate', methods=['POST'])
@login_required
def activate():
    db      = get_admin_supabase()
    uid     = session['user_id']

    try:
        plan_id = int(request.form.get('plan_id', 0))
    except (ValueError, TypeError):
        flash('Invalid investment plan.', 'error')
        return redirect(url_for('dashboard.index'))

    plan = Config.INVESTMENT_PLANS.get(plan_id)
    if not plan:
        flash('Invalid investment plan.', 'error')
        return redirect(url_for('dashboard.index'))

    # 7%/mwa pou tout plan yo. Si Config gen yon 'monthly_rate' pwòp pou plan
    # sa a, itilize li; sinon defo a se 7% (0.07).
    monthly_rate = plan.get('monthly_rate', 0.07)

    try:
        profile_res = db.table('profiles').select('balance_htg').eq('id', uid).execute()

        if not profile_res.data:
            flash('User profile not found.', 'error')
            return redirect(url_for('dashboard.index'))

        profile = profile_res.data[0]
        balance = float(profile.get('balance_htg') or 0)

        if balance < plan['amount']:
            flash(f"Balans ou pa sifi. Ou bezwen {plan['amount']:,} HTG pou aktive plan sa a.", 'error')
            return redirect(url_for('dashboard.index'))

        now = datetime.now(timezone.utc)
        matures_at = now + relativedelta(months=TERM_MONTHS)

        # Deduct from balance (Goud)
        new_balance = round(balance - plan['amount'], 2)
        db.table('profiles').update({'balance_htg': new_balance}).eq('id', uid).execute()

        # Create investment record
        db.table('investments').insert({
            'user_id':          uid,
            'plan_id':          plan_id,
            'plan_name':        plan['name'],
            'amount':           plan['amount'],
            'monthly_rate':     monthly_rate,
            'term_months':      TERM_MONTHS,
            'months_paid':      0,
            'status':           'active',
            'start_date':       now.isoformat(),
            'last_profit_date': None,
            'matures_at':       matures_at.isoformat(),
            'total_earned':     0.0,
            'created_at':       now.isoformat(),
        }).execute()

        # Log transaction
        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'investment',
            'amount':      plan['amount'],
            'description': f"Activated {plan['name']} Plan ({plan['amount']:,} HTG) — 7% chak mwa pandan 3 mwa",
            'status':      'completed',
            'created_at':  now.isoformat(),
        }).execute()

        # NOTE: Referral commission intentionally removed here.
        # Commission is paid ONLY on deposit/recharge — see deposit route.

        flash(f"Plan {plan['name']} aktive! Ou ap touche 7% chak mwa pandan 3 mwa. "
              f"Lè 3 mwa yo pase, kapital ou a ap retounen tounen sou balans ou.", 'success')

    except Exception as e:
        flash(f'Activation error: {e}', 'error')

    return redirect(url_for('dashboard.index'))
