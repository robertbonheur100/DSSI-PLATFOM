from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from config import Config
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

dashboard_bp = Blueprint('dashboard', __name__)

NATCASH_ADMIN = '41727986'


def _get_rates(db):
    """
    Retounen dict { rate_buy, rate_sell, rate_convert }
    Chache dènye valè chak tip nan exchange_rates.
    Si kolòn manke oswa vid → 130.0 pa defò.
    """
    defaults = {'rate_buy': 130.0, 'rate_sell': 130.0, 'rate_convert': 130.0}
    try:
        res  = db.table('exchange_rates').select('*').order('created_at', desc=True).limit(20).execute()
        rows = res.data or []
        result = {}
        for key in ('rate_buy', 'rate_sell', 'rate_convert'):
            for row in rows:
                val = row.get(key)
                if val is not None:
                    result[key] = float(val)
                    break
            if key not in result:
                result[key] = defaults[key]
        return result
    except Exception:
        return defaults


def _get_profile(db, uid):
    res = db.table('profiles').select('*').eq('id', uid).execute()
    return res.data[0] if res.data else {
        'username': 'User', 'balance': 0, 'balance_htg': 0
    }


# ─────────────────────────────────────────────
# DASHBOARD HOME
# ─────────────────────────────────────────────
@dashboard_bp.route('/')
@login_required
def index():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        profile = _get_profile(db, uid)

        deposits = db.table('deposits')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        withdrawals = db.table('withdrawals')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        investments = db.table('investments')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).execute().data or []

        transactions = db.table('transactions')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(30).execute().data or []

        rates = _get_rates(db)
        rate  = rates['rate_convert']   # backward-compat pou template

        buy_requests = db.table('buy_crypto_requests')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        sell_requests = db.table('sell_crypto_requests')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        htg_transactions = db.table('htg_transactions')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(30).execute().data or []

        htg_withdrawals = db.table('htg_withdrawals')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        l1_res   = db.table('profiles').select('id', count='exact').eq('referred_by', uid).execute()
        l1_count = getattr(l1_res, 'count', 0) or 0

        l2_res   = db.table('profiles').select('id', count='exact').eq('referred_by_l2', uid).execute()
        l2_count = getattr(l2_res, 'count', 0) or 0

        ref_earn = sum(
            t.get('amount', 0) for t in transactions
            if t.get('type') == 'referral_bonus'
        )

        return render_template('dashboard.html',
            profile=profile,
            deposits=deposits,
            withdrawals=withdrawals,
            investments=investments,
            transactions=transactions,
            l1_count=l1_count,
            l2_count=l2_count,
            referral_earnings=ref_earn,
            plans=Config.INVESTMENT_PLANS,
            usdt_trc20=Config.USDT_TRC20_ADDRESS,
            usdt_bep20=Config.USDT_BEP20_ADDRESS,
            whatsapp=Config.WHATSAPP_NUMBER,
            rate=rate,
            rate_buy=rates['rate_buy'],
            rate_sell=rates['rate_sell'],
            rate_convert=rates['rate_convert'],
            natcash_admin=NATCASH_ADMIN,
            buy_requests=buy_requests,
            sell_requests=sell_requests,
            htg_transactions=htg_transactions,
            htg_withdrawals=htg_withdrawals,
        )

    except Exception as e:
        return f'<h2 style="font-family:sans-serif;padding:2rem">Dashboard error: {e}</h2>', 500


# ─────────────────────────────────────────────
# DEPOSIT
# ─────────────────────────────────────────────
@dashboard_bp.route('/deposit', methods=['POST'])
@login_required
def deposit():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount  = float(request.form.get('amount', 0))
        network = request.form.get('network', '')
        proof   = request.form.get('proof_note', '')

        if amount <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        db.table('deposits').insert({
            'user_id':    uid,
            'amount':     amount,
            'network':    network,
            'proof_note': proof,
            'status':     'pending',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }).execute()

        flash('Deposit submitted! Send proof via WhatsApp to get approved.', 'success')

    except Exception as e:
        flash(f'Deposit error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# WITHDRAW (USDT)
# ─────────────────────────────────────────────
@dashboard_bp.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount  = float(request.form.get('amount', 0))
        wallet  = request.form.get('wallet_address', '').strip()
        network = request.form.get('network', '')

        profile = _get_profile(db, uid)
        balance = float(profile.get('balance') or 0)

        if amount <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        if amount > balance:
            flash(f'Not enough money. Balans ou: ${balance:.2f} USDT.', 'error')
            return redirect(url_for('dashboard.index'))

        if not wallet:
            flash('Wallet address required.', 'error')
            return redirect(url_for('dashboard.index'))

        db.table('withdrawals').insert({
            'user_id':        uid,
            'amount':         amount,
            'wallet_address': wallet,
            'network':        network,
            'status':         'pending',
            'created_at':     datetime.now(timezone.utc).isoformat(),
        }).execute()

        flash('Withdrawal request submitted! Under review.', 'success')

    except Exception as e:
        flash(f'Withdrawal error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# BUY CRYPTO (HTG → platfòm)
# Itilize rate_buy
# ─────────────────────────────────────────────
@dashboard_bp.route('/buy-crypto', methods=['POST'])
@login_required
def buy_crypto():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_htg     = float(request.form.get('amount_htg', 0))
        natcash_sender = request.form.get('natcash_sender', '').strip()
        proof_note     = request.form.get('proof_note', '').strip()

        if amount_htg <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        if not natcash_sender:
            flash('Please provide your NatCash sender number.', 'error')
            return redirect(url_for('dashboard.index'))

        # Kalkile USDT ekvalan pou montre nan rekò (rate_buy)
        rate_buy    = _get_rates(db)['rate_buy']
        amount_usdt = round(amount_htg / rate_buy, 6)

        db.table('buy_crypto_requests').insert({
            'user_id':        uid,
            'amount_htg':     amount_htg,
            'amount_usdt':    amount_usdt,
            'rate':           rate_buy,
            'natcash_sender': natcash_sender,
            'proof_note':     proof_note,
            'status':         'pending',
            'created_at':     datetime.now(timezone.utc).isoformat(),
        }).execute()

        flash(f'Buy request submitted! ≈ {amount_usdt:.4f} USDT pou {amount_htg:.2f} HTG @ {rate_buy} HTG/USDT.', 'success')

    except Exception as e:
        flash(f'Buy crypto error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# SELL CRYPTO (USDT → HTG)
# Itilize rate_sell
# ─────────────────────────────────────────────
@dashboard_bp.route('/sell-crypto', methods=['POST'])
@login_required
def sell_crypto():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_usdt      = float(request.form.get('amount_usdt', 0))
        tx_hash          = request.form.get('tx_hash', '').strip()
        network          = request.form.get('network', 'TRC-20')
        natcash_receiver = request.form.get('natcash_receiver', '').strip()

        if amount_usdt <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        if not natcash_receiver:
            flash('Please provide your NatCash phone number.', 'error')
            return redirect(url_for('dashboard.index'))

        if not tx_hash:
            flash('Please provide the transaction hash.', 'error')
            return redirect(url_for('dashboard.index'))

        # Kalkile HTG ekvalan pou montre nan rekò (rate_sell)
        rate_sell  = _get_rates(db)['rate_sell']
        amount_htg = round(amount_usdt * rate_sell, 2)

        db.table('sell_crypto_requests').insert({
            'user_id':          uid,
            'amount_usdt':      amount_usdt,
            'amount_htg':       amount_htg,
            'rate':             rate_sell,
            'tx_hash':          tx_hash,
            'network':          network,
            'natcash_receiver': natcash_receiver,
            'status':           'pending',
            'created_at':       datetime.now(timezone.utc).isoformat(),
        }).execute()

        flash(f'Sell request submitted! {amount_usdt:.4f} USDT → ≈ {amount_htg:.2f} HTG @ {rate_sell} HTG/USDT.', 'success')

    except Exception as e:
        flash(f'Sell crypto error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# CONVERT HTG → USDT
# Itilize rate_convert
# ─────────────────────────────────────────────
@dashboard_bp.route('/convert-htg-to-usdt', methods=['POST'])
@login_required
def convert_htg_to_usdt():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_htg = float(request.form.get('amount_htg', 0))

        if amount_htg <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        profile  = _get_profile(db, uid)
        bal_htg  = float(profile.get('balance_htg') or 0)
        bal_usdt = float(profile.get('balance') or 0)

        if amount_htg > bal_htg:
            flash(f'Not enough money. Balans HTG ou: {bal_htg:.2f} HTG.', 'error')
            return redirect(url_for('dashboard.index'))

        rate        = _get_rates(db)['rate_convert']
        amount_usdt = round(amount_htg / rate, 6)
        now         = datetime.now(timezone.utc).isoformat()

        db.table('profiles').update({
            'balance_htg': round(bal_htg - amount_htg, 2),
            'balance':     round(bal_usdt + amount_usdt, 6),
        }).eq('id', uid).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'convert',
            'amount_htg':  -amount_htg,
            'amount_usdt': amount_usdt,
            'rate':        rate,
            'description': f'Converted {amount_htg} HTG to {amount_usdt} USDT @ {rate}',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        flash(f'Konvèsyon reyisi! {amount_htg:.2f} HTG → {amount_usdt:.6f} USDT @ {rate}', 'success')

    except Exception as e:
        flash(f'Conversion error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# CONVERT USDT → HTG
# Itilize rate_convert
# ─────────────────────────────────────────────
@dashboard_bp.route('/convert-usdt-to-htg', methods=['POST'])
@login_required
def convert_usdt_to_htg():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_usdt = float(request.form.get('amount_usdt', 0))

        if amount_usdt <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        profile  = _get_profile(db, uid)
        bal_usdt = float(profile.get('balance') or 0)
        bal_htg  = float(profile.get('balance_htg') or 0)

        if amount_usdt > bal_usdt:
            flash(f'Not enough money. Balans USDT ou: ${bal_usdt:.2f} USDT.', 'error')
            return redirect(url_for('dashboard.index'))

        rate       = _get_rates(db)['rate_convert']
        amount_htg = round(amount_usdt * rate, 2)
        now        = datetime.now(timezone.utc).isoformat()

        db.table('profiles').update({
            'balance':     round(bal_usdt - amount_usdt, 6),
            'balance_htg': round(bal_htg + amount_htg, 2),
        }).eq('id', uid).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'convert',
            'amount_htg':  amount_htg,
            'amount_usdt': -amount_usdt,
            'rate':        rate,
            'description': f'Converted {amount_usdt} USDT to {amount_htg} HTG @ {rate}',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        flash(f'Konvèsyon reyisi! {amount_usdt:.6f} USDT → {amount_htg:.2f} HTG @ {rate}', 'success')

    except Exception as e:
        flash(f'Conversion error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# HTG WITHDRAWAL
# ─────────────────────────────────────────────
@dashboard_bp.route('/htg-withdraw', methods=['POST'])
@login_required
def htg_withdraw():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_htg     = float(request.form.get('amount_htg', 0))
        natcash_number = request.form.get('natcash_number', '').strip()

        if amount_htg <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        if not natcash_number:
            flash('NatCash number is required.', 'error')
            return redirect(url_for('dashboard.index'))

        profile = _get_profile(db, uid)
        bal_htg = float(profile.get('balance_htg') or 0)

        if amount_htg > bal_htg:
            flash(f'Not enough money. Balans HTG ou: {bal_htg:.2f} HTG.', 'error')
            return redirect(url_for('dashboard.index'))

        now     = datetime.now(timezone.utc).isoformat()
        new_htg = round(bal_htg - amount_htg, 2)

        db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()

        db.table('htg_withdrawals').insert({
            'user_id':        uid,
            'amount_htg':     amount_htg,
            'natcash_number': natcash_number,
            'status':         'pending',
            'created_at':     now,
        }).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'withdrawal_htg',
            'amount_htg':  -amount_htg,
            'description': f'HTG withdrawal {amount_htg} HTG to NatCash {natcash_number}',
            'status':      'pending',
            'created_at':  now,
        }).execute()

        flash(f'HTG withdrawal of {amount_htg:.2f} HTG submitted!', 'success')

    except Exception as e:
        flash(f'Withdrawal error: {e}', 'error')

    return redirect(url_for('dashboard.index'))
