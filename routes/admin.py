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
    Li yon sèl ligne exchange_rates epi retounen 3 taux dirèkteman.
    Pa chèche kolòn pa kolòn — pran tout kolòn ansanm nan premye ligne.
    """
    defaults = {'rate_buy': 130.0, 'rate_sell': 130.0, 'rate_convert': 130.0}
    try:
        res = db.table('exchange_rates') \
                .select('rate_buy, rate_sell, rate_convert') \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()
        if res.data:
            row = res.data[0]
            return {
                'rate_buy':     float(row['rate_buy'])     if row.get('rate_buy')     is not None else defaults['rate_buy'],
                'rate_sell':    float(row['rate_sell'])    if row.get('rate_sell')    is not None else defaults['rate_sell'],
                'rate_convert': float(row['rate_convert']) if row.get('rate_convert') is not None else defaults['rate_convert'],
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f'[_get_rates] {e}')
    return defaults


def _get_rate(db):
    """Backward-compat — retounen rate_convert sèlman."""
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

        # ── SMM: founisè + sèvis + lòd yo ──
        smm_providers = _q(lambda: db.table('smm_providers').select('*').order('name').execute())
        smm_services  = _q(lambda: db.table('smm_services').select('*').order('platform').order('category').execute())
        smm_orders    = _q(lambda: db.table('smm_orders').select('*').order('created_at', desc=True).limit(100).execute())

        smm_provider_map = {p['id']: p for p in smm_providers}
        smm_service_map  = {s['id']: s for s in smm_services}

        all_rates    = _get_rates(db)
        current_rate = all_rates['rate_convert']   # backward-compat pou template vye kote

        user_map = {u['id']: u.get('username', '—') for u in users}

        pending_deps    = [d for d in deposits     if d.get('status') == 'pending']
        pending_wds     = [w for w in withdrawals  if w.get('status') == 'pending']
        active_invs     = [i for i in investments  if i.get('status') == 'active']
        pending_buys    = [r for r in buy_requests  if r.get('status') == 'pending']
        pending_sells   = [r for r in sell_requests if r.get('status') == 'pending']
        pending_htg_wds = [w for w in htg_wds       if w.get('status') == 'pending']
        pending_smm     = [o for o in smm_orders    if o.get('status') in ('pending', 'processing')]

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
            smm_providers=smm_providers,
            smm_services=smm_services,
            smm_orders=smm_orders,
            smm_provider_map=smm_provider_map,
            smm_service_map=smm_service_map,
            pending_smm=pending_smm,
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
    UPDATE yon sèl ligne fiks nan exchange_rates.
    Konsa rate_buy, rate_sell, rate_convert toujou nan menm ligne —
    pa gen pwoblèm NULL ankò.
    """
    try:
        db        = get_admin_supabase()
        rate_type = request.form.get('rate_type', '')   # 'buy' | 'sell' | 'convert'
        rate_val  = float(request.form.get('rate', 0))

        if rate_type not in ('buy', 'sell', 'convert'):
            flash('Type taux la pa valid.', 'error')
            return redirect(url_for('admin.dashboard'))

        if rate_val <= 0:
            flash('Taux la dwe plis ke zewo.', 'error')
            return redirect(url_for('admin.dashboard'))

        col_name = f'rate_{rate_type}'

        # Verifye si ligne "current" deja egziste
        existing = db.table('exchange_rates').select('id').limit(1).execute()

        if existing.data:
            # UPDATE ligne ki egziste a
            row_id = existing.data[0]['id']
            db.table('exchange_rates').update({
                col_name:     rate_val,
                'created_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', row_id).execute()
        else:
            # Premye fwa — INSERT ak tout kolòn a 130 pa defò
            db.table('exchange_rates').insert({
                'rate':          130.0,
                'rate_buy':      130.0,
                'rate_sell':     130.0,
                'rate_convert':  130.0,
                col_name:        rate_val,
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


# ─────────────────────────────────────────────
# SMM — PROVIDERS (smm_providers)
# ─────────────────────────────────────────────
@admin_bp.route('/smm/provider/add', methods=['POST'])
@admin_required
def add_smm_provider():
    db  = get_admin_supabase()
    now = _now()

    try:
        name     = request.form.get('name', '').strip()
        api_url  = request.form.get('api_url', '').strip()
        api_key  = request.form.get('api_key', '').strip()
        currency = request.form.get('currency', 'USD').strip()

        if not name or not api_url or not api_key:
            flash('Non, API URL, ak API Key obligatwa.', 'error')
            return redirect(url_for('admin.dashboard') + '#tab-smm')

        db.table('smm_providers').insert({
            'name':       name,
            'api_url':    api_url,
            'api_key':    api_key,
            'currency':   currency or 'USD',
            'active':     True,
            'created_at': now,
        }).execute()

        _log(db, 'add_smm_provider', name, f'Ajoute founisè SMM: {name} ({api_url})', now)
        flash(f'Founisè "{name}" ajoute.', 'success')

    except Exception as e:
        flash(f'Erè ajoute founisè: {e}', 'error')

    return redirect(url_for('admin.dashboard') + '#tab-smm')


@admin_bp.route('/smm/provider/<provider_id>/toggle', methods=['POST'])
@admin_required
def toggle_smm_provider(provider_id):
    db = get_admin_supabase()
    providers = _q(lambda: db.table('smm_providers').select('*').eq('id', provider_id).execute())
    if not providers:
        flash('Founisè pa jwenn.', 'error')
        return redirect(url_for('admin.dashboard') + '#tab-smm')

    provider   = providers[0]
    new_active = not provider.get('active', True)
    db.table('smm_providers').update({'active': new_active}).eq('id', provider_id).execute()
    flash(f"Founisè {'aktive' if new_active else 'dezaktive'}.", 'success')
    return redirect(url_for('admin.dashboard') + '#tab-smm')


# ─────────────────────────────────────────────
# SMM — SERVICES (smm_services)
# ─────────────────────────────────────────────
@admin_bp.route('/smm/service/add', methods=['POST'])
@admin_required
def add_smm_service():
    db  = get_admin_supabase()
    now = _now()

    try:
        provider_id          = request.form.get('provider_id', '').strip()
        provider_service_id  = request.form.get('provider_service_id', '').strip()
        platform             = request.form.get('platform', '').strip()
        category             = request.form.get('category', '').strip()
        service_name         = request.form.get('service_name', '').strip()
        description          = request.form.get('description', '').strip()
        min_quantity         = int(request.form.get('min_quantity', 0))
        max_quantity         = int(request.form.get('max_quantity', 0))
        provider_price_usd   = float(request.form.get('provider_price_usd', 0))
        selling_price_htg    = float(request.form.get('selling_price_htg', 0))
        refill               = request.form.get('refill') == 'on'
        cancel               = request.form.get('cancel') == 'on'
        dripfeed             = request.form.get('dripfeed') == 'on'
        speed                = request.form.get('speed', '').strip()

        if not provider_id or not provider_service_id or not platform or not category \
           or min_quantity <= 0 or max_quantity <= 0 or selling_price_htg <= 0:
            flash('Tout chan obligatwa yo dwe ranpli e kantite/pri dwe pi gwo pase zewo.', 'error')
            return redirect(url_for('admin.dashboard') + '#tab-smm')

        if max_quantity < min_quantity:
            flash('Max quantity dwe pi gwo pase min quantity.', 'error')
            return redirect(url_for('admin.dashboard') + '#tab-smm')

        db.table('smm_services').insert({
            'provider_id':          provider_id,
            'provider_service_id':  provider_service_id,
            'platform':             platform,
            'category':             category,
            'service_name':         service_name or f'{platform} {category}',
            'description':          description,
            'min_quantity':         min_quantity,
            'max_quantity':         max_quantity,
            'provider_price_usd':   provider_price_usd,
            'selling_price_htg':    selling_price_htg,
            'refill':               refill,
            'cancel':               cancel,
            'dripfeed':             dripfeed,
            'speed':                speed,
            'active':               True,
            'created_at':           now,
        }).execute()

        _log(db, 'add_smm_service', provider_service_id,
             f'Ajoute sèvis SMM: {platform} {category} ({min_quantity}-{max_quantity}) — {selling_price_htg} HTG/1000', now)
        flash(f'Sèvis SMM ajoute: {platform} {category}.', 'success')

    except Exception as e:
        flash(f'Erè ajoute sèvis: {e}', 'error')

    return redirect(url_for('admin.dashboard') + '#tab-smm')


@admin_bp.route('/smm/service/<service_id>/toggle', methods=['POST'])
@admin_required
def toggle_smm_service(service_id):
    db = get_admin_supabase()

    services = _q(lambda: db.table('smm_services').select('*').eq('id', service_id).execute())
    if not services:
        flash('Sèvis pa jwenn.', 'error')
        return redirect(url_for('admin.dashboard') + '#tab-smm')

    service    = services[0]
    new_active = not service.get('active', True)
    db.table('smm_services').update({'active': new_active}).eq('id', service_id).execute()

    flash(f"Sèvis {'aktive' if new_active else 'dezaktive'}.", 'success')
    return redirect(url_for('admin.dashboard') + '#tab-smm')


@admin_bp.route('/smm/service/<service_id>/delete', methods=['POST'])
@admin_required
def delete_smm_service(service_id):
    db = get_admin_supabase()
    db.table('smm_services').delete().eq('id', service_id).execute()
    flash('Sèvis efase.', 'info')
    return redirect(url_for('admin.dashboard') + '#tab-smm')


def _log(db, action, target_id, details, now):
    try:
        db.table('admin_actions').insert({
            'admin_id': 'admin', 'action': action,
            'target_id': str(target_id), 'details': details,
            'created_at': now,
        }).execute()
    except Exception as e:
        logger.error(f'[Admin log] {e}')
