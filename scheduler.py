import json
import logging
import requests
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from config import Config

logger    = logging.getLogger(__name__)
_scheduler = None


def distribute_monthly_profits():
    try:
        from utils.supabase_client import get_admin_supabase
        db     = get_admin_supabase()
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        result      = db.table('investments').select('*').eq('status', 'active').execute()
        investments = result.data or []
        paid        = 0
        for inv in investments:
            last_paid = inv.get('last_profit_date')
            if last_paid:
                last_paid_dt = datetime.fromisoformat(last_paid.replace('Z', '+00:00'))
                if last_paid_dt > cutoff:
                    continue
            profit  = round(inv['amount'] * Config.DAILY_PROFIT_RATE, 2)  # 7% mansyèl
            user_id = inv['user_id']
            prof_res = db.table('profiles').select('balance_htg').eq('id', user_id).execute()
            if not prof_res.data:
                continue
            new_balance = round((prof_res.data[0].get('balance_htg') or 0) + profit, 2)
            db.table('profiles').update({'balance_htg': new_balance}).eq('id', user_id).execute()
            db.table('investments').update({
                'last_profit_date': now.isoformat(),
                'total_earned':     round((inv.get('total_earned') or 0) + profit, 2)
            }).eq('id', inv['id']).execute()
            db.table('transactions').insert({
                'user_id':     user_id,
                'type':        'monthly_profit',
                'amount':      profit,
                'description': f"7% mansyèl sou {inv['amount']:,} HTG ({inv.get('plan_name','Plan')})",
                'status':      'completed',
                'created_at':  now.isoformat(),
            }).execute()
            paid += 1
        logger.info(f'[Scheduler] Paid monthly profits to {paid} investment(s).')
    except Exception as e:
        logger.error(f'[Scheduler] Error: {e}')


# ─────────────────────────────────────────────────────────────
# SMM PANEL — API client jenerik (mache ak founisè estil smmzio.com,
# JAP, elatriye — tout founisè "SMM Panel API v2" itilize menm fòma)
# ─────────────────────────────────────────────────────────────

def smm_provider_request(provider: dict, payload: dict) -> dict:
    """
    Voye yon requèt POST bay API yon founisè espesifik (soti nan tab smm_providers).
    payload dwe gen 'action' + paramèt aksyon an mande.
    """
    api_url = provider.get('api_url')
    api_key = provider.get('api_key')

    if not api_url or not api_key:
        return {'error': f"Founisè '{provider.get('name','?')}' pa gen api_url/api_key konfigire."}

    data = {'key': api_key}
    data.update(payload)

    try:
        resp = requests.post(api_url, data=data, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"[SMM] API error ({provider.get('name','?')}): {e}")
        return {'error': str(e)}


def smm_add_order(provider: dict, provider_service_id: str, link: str, quantity: int) -> dict:
    return smm_provider_request(provider, {
        'action':   'add',
        'service':  provider_service_id,
        'link':     link,
        'quantity': quantity,
    })


def smm_get_status(provider: dict, provider_order_id: str) -> dict:
    return smm_provider_request(provider, {
        'action': 'status',
        'order':  provider_order_id,
    })


def _refund_htg(db, order: dict, now: str, reason: str):
    """Ranbouse HTG bay user a lè yon lòd SMM echwe."""
    profile = db.table('profiles').select('balance_htg').eq('id', order['user_id']).execute().data
    if not profile:
        return
    new_bal = round(float(profile[0].get('balance_htg') or 0) + float(order.get('charge_htg') or 0), 2)
    db.table('profiles').update({'balance_htg': new_bal}).eq('id', order['user_id']).execute()
    db.table('htg_transactions').insert({
        'user_id':     order['user_id'],
        'type':        'smm_refund',
        'amount_htg':  order.get('charge_htg') or 0,
        'description': f"Ranbousman lòd SMM #{order['id']} — {reason}",
        'status':      'completed',
        'created_at':  now,
    }).execute()


def process_smm_orders():
    """
    Job ki woule chak SMM_CHECK_INTERVAL_MINUTES minit:
    1) Pran lòd ki 'pending' → soumèt yo bay founisè a (via smm_providers) → 'processing'
    2) Pran lòd ki 'processing' → tcheke statis yo → mete ajou 'completed'/'partial'/'failed'
    """
    try:
        from utils.supabase_client import get_admin_supabase
        db  = get_admin_supabase()
        now = datetime.now(timezone.utc).isoformat()

        providers_by_id = {p['id']: p for p in db.table('smm_providers').select('*').execute().data or []}
        services_by_id  = {s['id']: s for s in db.table('smm_services').select('*').execute().data or []}

        # ── 1) Soumèt lòd 'pending' bay founisè a ──
        pending = db.table('smm_orders').select('*').eq('status', 'pending').execute().data or []
        for order in pending:
            service  = services_by_id.get(order['service_id'])
            provider = providers_by_id.get(order['provider_id'])

            if not service or not provider or not provider.get('active', True):
                _refund_htg(db, order, now, 'sèvis oswa founisè pa disponib')
                db.table('smm_orders').update({
                    'status': 'failed', 'provider_status': 'service/provider unavailable', 'updated_at': now,
                }).eq('id', order['id']).execute()
                continue

            result = smm_add_order(provider, service['provider_service_id'], order['link'], order['quantity'])

            if result.get('error') or not result.get('order'):
                logger.error(f"[SMM] Order {order['id']} soumission echwe: {result}")
                _refund_htg(db, order, now, 'founisè refize lòd la')
                db.table('smm_orders').update({
                    'status':          'failed',
                    'provider_status': str(result.get('error', 'unknown')),
                    'api_response':    json.dumps(result),
                    'updated_at':      now,
                }).eq('id', order['id']).execute()
                continue

            db.table('smm_orders').update({
                'provider_order_id': str(result['order']),
                'status':             'processing',
                'api_response':       json.dumps(result),
                'updated_at':         now,
            }).eq('id', order['id']).execute()
            logger.info(f"[SMM] Order {order['id']} soumèt kay {provider['name']}, provider_order_id={result['order']}")

        # ── 2) Tcheke statis lòd 'processing' yo ──
        processing = db.table('smm_orders').select('*').eq('status', 'processing').execute().data or []
        for order in processing:
            if not order.get('provider_order_id'):
                continue
            provider = providers_by_id.get(order['provider_id'])
            if not provider:
                continue

            result = smm_get_status(provider, order['provider_order_id'])
            if result.get('error'):
                continue

            provider_status = str(result.get('status', '')).lower()
            update_fields = {
                'provider_status': provider_status,
                'api_response':     json.dumps(result),
                'updated_at':       now,
            }

            if 'start_count' in result and result['start_count'] not in (None, ''):
                update_fields['start_count'] = result['start_count']
            if 'remains' in result and result['remains'] not in (None, ''):
                update_fields['remains'] = result['remains']
            if 'charge' in result and result['charge'] not in (None, ''):
                try:
                    update_fields['provider_charge_usd'] = float(result['charge'])
                except (TypeError, ValueError):
                    pass

            if provider_status == 'completed':
                update_fields['status'] = 'completed'
            elif provider_status in ('canceled', 'cancelled'):
                update_fields['status'] = 'failed'
                _refund_htg(db, order, now, 'founisè anile lòd la')
            elif provider_status == 'partial':
                update_fields['status'] = 'partial'
            # 'pending', 'in progress', 'processing' → rete 'processing'

            db.table('smm_orders').update(update_fields).eq('id', order['id']).execute()

        logger.info(f'[SMM] Cycle fini: {len(pending)} nouvo lòd, {len(processing)} verifye.')

    except Exception as e:
        logger.error(f'[Scheduler][SMM] Error: {e}')


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        distribute_monthly_profits,
        trigger='interval',
        days=30,
        id='monthly_profits',
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    _scheduler.add_job(
        process_smm_orders,
        trigger='interval',
        minutes=Config.SMM_CHECK_INTERVAL_MINUTES,
        id='smm_orders',
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    _scheduler.start()
    logger.info('[Scheduler] Started.')
