import logging
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils.supabase_client import get_admin_supabase
from utils.helpers import admin_required

logger   = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)


def _q(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        logger.error(f'[Admin query] {e}')
        return []


def _now():
    return datetime.now(timezone.utc).isoformat()


def _get_rates(db):
    """
    Retounen yon dict { rate_buy, rate_sell, rate_convert }
    pou dènye valè chak tip nan tablo exchange_rates.
    Si yon kolòn manke, li tonbe sou 130.0 pa defò.
    """
    defaults = {'rate_buy': 130.0, 'rate_sell': 130.0, 'rate_convert': 130.0}
    try:
        res = db.table('exchange_rates').select('*').order('created_at', desc=True).limit(20).execute()
        rows = res.data or []
        result = {}
        for key in ('rate_buy', 'rate_sell', 'rate_convert'):
            # pran dènye ligne ki gen kolòn sa a ki non-null
            for row in rows:
                val = row.get(key)
                if val is not None:
                    result[key] = float(val)
                    break
            if key not in result:
                result[key] = defaults[key]
        return result
    except Exception as e:
        logger.error(f'[_get_rates] {e}')
        return defaults


def _get_rate(db):
    """
    Backward-compat: retounen rate_convert pou tout kote ki te itilize
    yon sèl taux anvan (sell, htg_wd, etc.).
    """
    return _get_rates(db)['rate_convert']


@admin_bp.route('/')
@admin_required
def dashboard():
    try:
        db = get_admin_supabase()

        users        = _q(lambda: db.table('profiles').select('*').execute())
        deposits     = _q(lambda: db.table('deposits').select('*').order('created_at', desc=True).execute())
        withdrawals  = _q(lambda: db.table('withdrawals').select('*').order('created_at', desc=True).execute())
        transactions = _q(lambda: db.table('transactions').select('*').order('created_at', desc=True).limit(60).execute())
        investments  = _q(lambda: db.table('investments').select('*').order('created_at', desc=True).execute())
        actions      = _q(lambda: db.table('admin_actions').select('*').order('created_at', desc=True).limit(50).execute())

        buy_requests  = _q(lambda: db.table('buy_crypto_requests').select('*').order('created_at', desc=True).execute())
        sell_requests = _q(lambda: db.table('sell_crypto_requests').select('*').order('created_at', desc=True).execute())
        htg_wds       = _q(lambda: db.table('htg_withdrawals').select('*').order('created_at', desc=True).execute())
        rates         = _q(lambda: db.table('exchange_rates').select('*').order('created_at', desc=True).limit(20).execute())

        all_rates    = _get_rates(db)
        current_rate = all_rates['rate_convert']   # backward-compat pou template vye kote

        user_map = {u['id']: u.get('username', '—') for u in users}

        pending_deps    = [d for d in deposits     if d.get('status') == 'pending']
        pending_wds     = [w for w in withdrawals  if w.get('status') == 'pending']
        active_invs     = [i for i in investments  if i.get('status') == 'active']
        pending_buys    = [r for r in buy_requests  if r.get('status') == 'pending']
        pending_sells   = [r for r in sell_requests if r.get('status') == 'pending']
        pending_htg_wds = [w for w in htg_wds       if w.get('status') == 'pending']

        total_balance = sum(float(u.get('balance') or 0) for u in users)
        invested_vol  = sum(float(i.get('amount')  or 0) for i in active_invs)

        return render_template('admin.html',
            users=users,
            deposits=deposits,
            withdrawals=withdrawals,
            transactions=transactions,
            investments=investments,
            actions=actions,
            user_map=user_map,
            total_balance=total_balance,
            invested_vol=invested_vol,
            pending_deposits=pending_deps,
            pending_withdrawals=pending_wds,
            active_investments=active_invs,
            buy_requests=buy_requests,
            sell_requests=sell_requests,
            htg_wds=htg_wds,
            rates=rates,
            current_rate=current_rate,
            rate_buy=all_rates['rate_buy'],
            rate_sell=all_rates['rate_sell'],
            rate_convert=all_rates['rate_convert'],
            pending_buys=pending_buys,
            pending_sells=pending_sells,
            pending_htg_wds=pending_htg_wds,
        )

    except Exception as e:
        logger.exception(f'Admin dashboard error: {e}')
        return f'''<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#0b0c10;color:#e8eaf0;padding:2rem">
<div style="max-width:600px;margin:4rem auto;background:#14171f;border:1px solid #222633;border-radius:12px;padding:2rem">
  <div style="font-size:2rem;font-weight:800;color:#d4a843;margin-bottom:1rem">DSSI Admin</div>
  <h2 style="color:#f87171">Dashboard Error</h2>
  <pre style="color:#9aa3b8;background:#0b0c10;padding:1rem;border-radius:8px;font-size:12px;
              white-space:pre-wrap;word-break:break-all">{type(e).__name__}: {e}</pre>
  <a href="/auth/logout" style="color:#d4a843">← Logout</a>
</div></body></html>''', 500


# ─────────────────────────────────────────────
# DEPOSIT APPROVE / REJECT
# ─────────────────────────────────────────────
@admin_bp.route('/deposit/<deposit_id>/<action>', methods=['POST'])
@admin_required
def handle_deposit(deposit_id, action):
    from routes.investments import pay_referral_commissions
    db  = get_admin_supabase()
    now = _now()

    deps = _q(lambda: db.table('deposits').select('*').eq('id', deposit_id).execute())
    if not deps:
        flash('Deposit not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    dep    = deps[0]
    uid    = dep.get('user_id')
    amount = float(dep.get('amount') or 0)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
        balance = float(profs[0].get('balance') or 0) if profs else 0.0
        db.table('profiles').update({'balance': round(balance + amount, 2)}).eq('id', uid).execute()
        db.table('deposits').update({'status': 'approved', 'reviewed_at': now}).eq('id', deposit_id).execute()
        db.table('transactions').insert({
            'user_id': uid, 'type': 'deposit', 'amount': amount,
            'description': f'Deposit approved — ${amount} via {dep.get("network","N/A")}',
            'status': 'completed', 'created_at': now,
        }).execute()
        try:
            pay_referral_commissions(db, uid, amount, tx_type='deposit')
        except Exception as e:
            logger.error(f'Referral commission error: {e}')
        flash(f'Deposit of ${amount} approved and credited.', 'success')

    elif action == 'reject':
        db.table('deposits').update({'status': 'rejected', 'reviewed_at': now}).eq('id', deposit_id).execute()
        flash('Deposit rejected.', 'info')

    _log(db, f'{action}_deposit', deposit_id, f'{action} deposit #{deposit_id[:8]}', now)
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# WITHDRAWAL APPROVE / REJECT
# ─────────────────────────────────────────────
@admin_bp.route('/withdrawal/<wd_id>/<action>', methods=['POST'])
@admin_required
def handle_withdrawal(wd_id, action):
    db  = get_admin_supabase()
    now = _now()

    wds = _q(lambda: db.table('withdrawals').select('*').eq('id', wd_id).execute())
    if not wds:
        flash('Withdrawal not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    wd     = wds[0]
    uid    = wd.get('user_id')
    amount = float(wd.get('amount') or 0)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
        balance = float(profs[0].get('balance') or 0) if profs else 0.0
        db.table('profiles').update({'balance': round(max(balance - amount, 0), 2)}).eq('id', uid).execute()
        db.table('withdrawals').update({'status': 'approved', 'reviewed_at': now}).eq('id', wd_id).execute()
        db.table('transactions').insert({
            'user_id': uid, 'type': 'withdrawal', 'amount': -amount,
            'description': f'Withdrawal approved — ${amount}',
            'status': 'completed', 'created_at': now,
        }).execute()
        flash(f'Withdrawal of ${amount} approved.', 'success')

    elif action == 'reject':
        db.table('withdrawals').update({'status': 'rejected', 'reviewed_at': now}).eq('id', wd_id).execute()
        flash('Withdrawal rejected.', 'info')

    _log(db, f'{action}_withdrawal', wd_id, f'{action} withdrawal #{wd_id[:8]}', now)
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# ADJUST USDT BALANCE
# ─────────────────────────────────────────────
@admin_bp.route('/adjust-balance', methods=['POST'])
@admin_required
def adjust_balance():
    db     = get_admin_supabase()
    now    = _now()
    uid    = request.form.get('user_id', '')
    amount = float(request.form.get('amount', 0))
    reason = request.form.get('reason', 'Admin adjustment')

    profs = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
    if not profs:
        flash('User not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    new_bal = round(float(profs[0].get('balance') or 0) + amount, 2)
    if new_bal < 0:
        flash('Balance cannot go negative.', 'error')
        return redirect(url_for('admin.dashboard'))

    db.table('profiles').update({'balance': new_bal}).eq('id', uid).execute()
    db.table('transactions').insert({
        'user_id': uid, 'type': 'admin_adjustment', 'amount': amount,
        'description': reason, 'status': 'completed', 'created_at': now,
    }).execute()
    _log(db, 'adjust_balance', uid, f'Adjusted ${amount} — {reason}', now)
    flash(f'Balance adjusted by ${amount}.', 'success')
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# SET EXCHANGE RATES  (3 tip separe)
# ─────────────────────────────────────────────
@admin_bp.route('/set-rate', methods=['POST'])
@admin_required
def set_rate():
    """
    Resevwa yon sèl tip taux nan yon fwa (rate_type = buy | sell | convert).
    Enstale yon nouvo ligne nan exchange_rates ak sèlman kolòn ki konsène a.
    """
    try:
        db        = get_admin_supabase()
        rate_type = request.form.get('rate_type', '')   # 'buy' | 'sell' | 'convert'
        rate_val  = float(request.form.get('rate', 0))

        allowed = ('buy', 'sell', 'convert')
        if rate_type not in allowed:
            flash('Type taux la pa valid.', 'error')
            return redirect(url_for('admin.dashboard'))

        if rate_val <= 0:
            flash('Taux la dwe plis ke zewo.', 'error')
            return redirect(url_for('admin.dashboard'))

        col_name = f'rate_{rate_type}'   # rate_buy | rate_sell | rate_convert

        db.table('exchange_rates').insert({
            col_name: rate_val,
        }).execute()

        labels = {'buy': 'Buy Crypto', 'sell': 'Sell Crypto', 'convert': 'Convert USDT↔HTG'}
        flash(f'Taux {labels[rate_type]} mizajou: {rate_val} HTG/USDT.', 'success')

    except Exception as e:
        flash(f'Erè taux: {e}', 'error')

    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# BUY CRYPTO APPROVE / REJECT
# ─────────────────────────────────────────────
@admin_bp.route('/buy-crypto/<req_id>/<action>', methods=['POST'])
@admin_required
def handle_buy(req_id, action):
    db  = get_admin_supabase()
    now = _now()

    reqs = _q(lambda: db.table('buy_crypto_requests').select('*').eq('id', req_id).execute())
    if not reqs:
        flash('Buy request not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    req        = reqs[0]
    uid        = req.get('user_id')
    amount_htg = float(req.get('amount_htg') or 0)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
        bal_htg = float(profs[0].get('balance_htg') or 0) if profs else 0.0
        db.table('profiles').update({'balance_htg': round(bal_htg + amount_htg, 2)}).eq('id', uid).execute()
        db.table('buy_crypto_requests').update({'status': 'approved', 'reviewed_at': now}).eq('id', req_id).execute()
        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'buy',
            'amount_htg':  amount_htg,
            'description': f'Buy approved — {amount_htg} HTG via NatCash',
            'status':      'completed',
            'created_at':  now,
        }).execute()
        _log(db, 'approve_buy', req_id, f'Approved buy #{req_id[:8]}: +{amount_htg} HTG', now)
        flash(f'Buy request approved. {amount_htg} HTG credited.', 'success')

    elif action == 'reject':
        db.table('buy_crypto_requests').update({'status': 'rejected', 'reviewed_at': now}).eq('id', req_id).execute()
        _log(db, 'reject_buy', req_id, f'Rejected buy #{req_id[:8]}', now)
        flash('Buy request rejected.', 'info')

    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# SELL CRYPTO APPROVE / REJECT
# ─────────────────────────────────────────────
@admin_bp.route('/sell-crypto/<req_id>/<action>', methods=['POST'])
@admin_required
def handle_sell(req_id, action):
    db  = get_admin_supabase()
    now = _now()

    reqs = _q(lambda: db.table('sell_crypto_requests').select('*').eq('id', req_id).execute())
    if not reqs:
        flash('Sell request not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    req         = reqs[0]
    uid         = req.get('user_id')
    amount_usdt = float(req.get('amount_usdt') or 0)
    rate        = _get_rates(db)['rate_sell']   # itilize taux sell espesifik
    amount_htg  = round(amount_usdt * rate, 2)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
        bal_htg = float(profs[0].get('balance_htg') or 0) if profs else 0.0
        db.table('profiles').update({'balance_htg': round(bal_htg + amount_htg, 2)}).eq('id', uid).execute()
        db.table('sell_crypto_requests').update({'status': 'approved', 'reviewed_at': now}).eq('id', req_id).execute()
        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'sell',
            'amount_htg':  amount_htg,
            'amount_usdt': -amount_usdt,
            'rate':        rate,
            'description': f'Sell approved — {amount_usdt} USDT → {amount_htg} HTG @ {rate}',
            'status':      'completed',
            'created_at':  now,
        }).execute()
        _log(db, 'approve_sell', req_id, f'Approved sell #{req_id[:8]}: {amount_usdt} USDT → {amount_htg} HTG', now)
        flash(f'Sell approved. {amount_htg} HTG credited to user.', 'success')

    elif action == 'reject':
        db.table('sell_crypto_requests').update({'status': 'rejected', 'reviewed_at': now}).eq('id', req_id).execute()
        _log(db, 'reject_sell', req_id, f'Rejected sell #{req_id[:8]}', now)
        flash('Sell request rejected.', 'info')

    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# HTG WITHDRAWAL APPROVE / REJECT
# ─────────────────────────────────────────────
@admin_bp.route('/htg-withdrawal/<wd_id>/<action>', methods=['POST'])
@admin_required
def handle_htg_withdrawal(wd_id, action):
    db  = get_admin_supabase()
    now = _now()

    wds = _q(lambda: db.table('htg_withdrawals').select('*').eq('id', wd_id).execute())
    if not wds:
        flash('HTG withdrawal not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    wd         = wds[0]
    uid        = wd.get('user_id')
    amount_htg = float(wd.get('amount_htg') or 0)

    if action == 'approve':
        db.table('htg_withdrawals').update({'status': 'approved', 'reviewed_at': now}).eq('id', wd_id).execute()
        _log(db, 'approve_htg_wd', wd_id, f'Approved HTG WD #{wd_id[:8]}: {amount_htg} HTG', now)
        flash(f'HTG withdrawal of {amount_htg} HTG approved.', 'success')

    elif action == 'reject':
        profs   = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
        bal_htg = float(profs[0].get('balance_htg') or 0) if profs else 0.0
        db.table('profiles').update({'balance_htg': round(bal_htg + amount_htg, 2)}).eq('id', uid).execute()
        db.table('htg_withdrawals').update({'status': 'rejected', 'reviewed_at': now}).eq('id', wd_id).execute()
        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'withdrawal_htg',
            'amount_htg':  amount_htg,
            'description': f'HTG withdrawal refunded (rejected) — {amount_htg} HTG',
            'status':      'completed',
            'created_at':  now,
        }).execute()
        _log(db, 'reject_htg_wd', wd_id, f'Rejected HTG WD #{wd_id[:8]}: refunded {amount_htg} HTG', now)
        flash(f'Rejected. {amount_htg} HTG refunded to user.', 'info')

    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# ADJUST HTG BALANCE
# ─────────────────────────────────────────────
@admin_bp.route('/adjust-htg', methods=['POST'])
@admin_required
def adjust_htg():
    db         = get_admin_supabase()
    now        = _now()
    uid        = request.form.get('user_id', '')
    amount_htg = float(request.form.get('amount_htg', 0))
    reason     = request.form.get('reason', 'Admin HTG adjustment')

    profs = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
    if not profs:
        flash('User not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    new_htg = round(float(profs[0].get('balance_htg') or 0) + amount_htg, 2)
    if new_htg < 0:
        flash('Balance cannot go negative.', 'error')
        return redirect(url_for('admin.dashboard'))

    db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()
    db.table('htg_transactions').insert({
        'user_id':     uid,
        'type':        'admin_adjustment',
        'amount_htg':  amount_htg,
        'description': reason,
        'status':      'completed',
        'created_at':  now,
    }).execute()
    _log(db, 'adjust_htg', uid, f'Adjusted HTG {amount_htg:+.2f} — {reason}', now)
    flash(f'HTG balance adjusted by {amount_htg} HTG.', 'success')
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# SUSPEND / REACTIVATE INVESTMENT PLAN
# ─────────────────────────────────────────────
@admin_bp.route('/investment/<inv_id>/suspend', methods=['POST'])
@admin_required
def suspend_investment(inv_id):
    db  = get_admin_supabase()
    now = _now()

    invs = _q(lambda: db.table('investments').select('*').eq('id', inv_id).execute())
    if not invs:
        flash('Investment plan not found.', 'error')
        return redirect(url_for('admin.dashboard') + '#tab-investments')

    inv    = invs[0]
    uid    = inv.get('user_id')
    reason = request.form.get('reason', 'Suspended by admin')

    if inv.get('status') == 'suspended':
        flash('Plan deja suspended.', 'info')
        return redirect(url_for('admin.dashboard') + '#tab-investments')

    db.table('investments').update({
        'status':         'suspended',
        'suspended_at':   now,
        'suspend_reason': reason,
    }).eq('id', inv_id).execute()

    db.table('transactions').insert({
        'user_id':     uid,
        'type':        'plan_suspended',
        'amount':      0,
        'description': f'Plan "{inv.get("plan_name","—")}" suspended — {reason}',
        'status':      'completed',
        'created_at':  now,
    }).execute()

    _log(db, 'suspend_investment', inv_id,
         f'Suspended plan "{inv.get("plan_name","—")}" for user {uid[:8]} — {reason}', now)

    flash(f'Plan "{inv.get("plan_name","—")}" suspended.', 'warning')
    return redirect(url_for('admin.dashboard') + '#tab-investments')


@admin_bp.route('/investment/<inv_id>/reactivate', methods=['POST'])
@admin_required
def reactivate_investment(inv_id):
    db  = get_admin_supabase()
    now = _now()

    invs = _q(lambda: db.table('investments').select('*').eq('id', inv_id).execute())
    if not invs:
        flash('Investment plan not found.', 'error')
        return redirect(url_for('admin.dashboard') + '#tab-investments')

    inv = invs[0]
    uid = inv.get('user_id')

    if inv.get('status') == 'active':
        flash('Plan deja aktif.', 'info')
        return redirect(url_for('admin.dashboard') + '#tab-investments')

    db.table('investments').update({
        'status':         'active',
        'suspended_at':   None,
        'suspend_reason': None,
        'reactivated_at': now,
    }).eq('id', inv_id).execute()

    db.table('transactions').insert({
        'user_id':     uid,
        'type':        'plan_reactivated',
        'amount':      0,
        'description': f'Plan "{inv.get("plan_name","—")}" reactivated by admin',
        'status':      'completed',
        'created_at':  now,
    }).execute()

    _log(db, 'reactivate_investment', inv_id,
         f'Reactivated plan "{inv.get("plan_name","—")}" for user {uid[:8]}', now)

    flash(f'Plan "{inv.get("plan_name","—")}" reactivated.', 'success')
    return redirect(url_for('admin.dashboard') + '#tab-investments')


def _log(db, action, target_id, details, now):
    try:
        db.table('admin_actions').insert({
            'admin_id': 'admin', 'action': action,
            'target_id': str(target_id), 'details': details,
            'created_at': now,
        }).execute()
    except Exception as e:
        logger.error(f'[Admin log] {e}')
