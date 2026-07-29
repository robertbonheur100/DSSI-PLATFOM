import logging
import requests
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from config import Config

logger    = logging.getLogger(__name__)
_scheduler = None


def distribute_daily_profits():
    try:
        from utils.supabase_client import get_admin_supabase
        db     = get_admin_supabase()
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        result      = db.table('investments').select('*').eq('status', 'active').execute()
        investments = result.data or []
        paid        = 0
        for inv in investments:
            last_paid = inv.get('last_profit_date')
            if last_paid:
                last_paid_dt = datetime.fromisoformat(last_paid.replace('Z', '+00:00'))
                if last_paid_dt > cutoff:
                    continue
            profit  = round(inv['amount'] * 0.02, 2)
            user_id = inv['user_id']
            prof_res = db.table('profiles').select('balance').eq('id', user_id).execute()
            if not prof_res.data:
                continue
            new_balance = round((prof_res.data[0].get('balance') or 0) + profit, 2)
            db.table('profiles').update({'balance': new_balance}).eq('id', user_id).execute()
            db.table('investments').update({
                'last_profit_date': now.isoformat(),
                'total_earned':     round((inv.get('total_earned') or 0) + profit, 2)
            }).eq('id', inv['id']).execute()
            db.table('transactions').insert({
                'user_id':     user_id,
                'type':        'daily_profit',
                'amount':      profit,
                'description': f"Daily 2% on ${inv['amount']} ({inv.get('plan_name','Plan')})",
                'status':      'completed',
                'created_at':  now.isoformat(),
            }).execute()
            paid += 1
        logger.info(f'[Scheduler] Paid profits to {paid} investment(s).')
    except Exception as e:
        logger.error(f'[Scheduler] Error: {e}')


# ─────────────────────────────────────────────────────────────
# SMM PANEL — smmzio.com API client
# ─────────────────────────────────────────────────────────────

def smmzio_request(payload: dict) -> dict:
    """
    Voye yon requèt POST bay smmzio.com API v2.
    payload dwe gen 'action' + paramèt aksyon an mande.
    Retounen JSON response la kòm dict, oswa {'error': '...'} si li echwe.
    """
    if not Config.SMMZIO_API_KEY:
        return {'error': 'SMMZIO_API_KEY pa konfigire (mete l kòm environment variable).'}

    data = {'key': Config.SMMZIO_API_KEY}
    data.update(payload)

    try:
        resp = requests.post(Config.SMMZIO_API_URL, data=data, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f'[SMMZIO] API error: {e}')
        return {'error': str(e)}


def smmzio_add_order(provider_service_id: str, link: str, quantity: int) -> dict:
    """Kreye yon lòd kay founisè a. Retounen dict ak 'order' (ID) si sikse."""
    return smmzio_request({
        'action':  'add',
        'service': provider_service_id,
        'link':    link,
        'quantity': quantity,
    })


def smmzio_get_status(provider_order_id: str) -> dict:
    """Tcheke statis yon lòd kay founisè a."""
    return smmzio_request({
        'action': 'status',
        'order':  provider_order_id,
    })


def process_smm_orders():
    """
    Job ki woule chak SMM_CHECK_INTERVAL_MINUTES minit:
    1) Pran lòd ki 'pending' → soumèt yo bay smmzio.com → mete yo 'processing'
    2) Pran lòd ki 'processing' → tcheke statis yo → mete ajou 'completed'/'failed'/'partial'
    """
    try:
        from utils.supabase_client import get_admin_supabase
        db  = get_admin_supabase()
        now = datetime.now(timezone.utc).isoformat()

        # ── 1) Soumèt lòd 'pending' bay founisè a ──
        pending = db.table('smm_orders').select('*').eq('status', 'pending').execute().data or []
        for order in pending:
            service = db.table('smm_services').select('*').eq('id', order['service_id']).execute().data
            if not service:
                db.table('smm_orders').update({
                    'status': 'failed', 'provider_status': 'service introuvable', 'updated_at': now,
                }).eq('id', order['id']).execute()
                continue
            service = service[0]

            result = smmzio_add_order(service['provider_service_id'], order['link'], order['quantity'])

            if result.get('error') or not result.get('order'):
                logger.error(f"[SMM] Order {order['id']} soumission echwe: {result}")
                # Ranbouse balans user a paske founisè a pa aksepte lòd la
                profile = db.table('profiles').select('balance_htg').eq('id', order['user_id']).execute().data
                if profile:
                    new_bal = round(float(profile[0].get('balance_htg') or 0) + order['price_htg'], 2)
                    db.table('profiles').update({'balance_htg': new_bal}).eq('id', order['user_id']).execute()
                    db.table('htg_transactions').insert({
                        'user_id':     order['user_id'],
                        'type':        'smm_refund',
                        'amount_htg':  order['price_htg'],
                        'description': f"Ranbousman lòd SMM #{order['id']} — founisè refize",
                        'status':      'completed',
                        'created_at':  now,
                    }).execute()
                db.table('smm_orders').update({
                    'status': 'failed',
                    'provider_status': str(result.get('error', 'unknown')),
                    'updated_at': now,
                }).eq('id', order['id']).execute()
                continue

            db.table('smm_orders').update({
                'provider_order_id': str(result['order']),
                'status':             'processing',
                'updated_at':         now,
            }).eq('id', order['id']).execute()
            logger.info(f"[SMM] Order {order['id']} soumèt kay founisè, provider_order_id={result['order']}")

        # ── 2) Tcheke statis lòd 'processing' yo ──
        processing = db.table('smm_orders').select('*').eq('status', 'processing').execute().data or []
        for order in processing:
            if not order.get('provider_order_id'):
                continue
            result = smmzio_get_status(order['provider_order_id'])
            if result.get('error'):
                continue

            provider_status = str(result.get('status', '')).lower()
            update_fields = {'provider_status': provider_status, 'updated_at': now}

            if provider_status in ('completed',):
                update_fields['status'] = 'completed'
            elif provider_status in ('canceled', 'cancelled'):
                update_fields['status'] = 'failed'
            elif provider_status in ('partial',):
                update_fields['status'] = 'partial'
            # 'pending', 'in progress', 'processing' → rete 'processing', jis mete ajou provider_status

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
        distribute_daily_profits,
        trigger='interval',
        hours=24,
        id='daily_profits',
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
