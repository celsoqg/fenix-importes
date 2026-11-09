import os
import sys
import time
import json
import math
import logging
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from typing import Any

import numpy as np
import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SniperHFTEngine")

USD_BRL_RATE = float(os.getenv("USD_BRL_RATE", "5.38"))
MEMORY_FILE_PATH = os.getenv("OMNI_MEMORY_PATH", "/tmp/omni_market_memory_v50.json")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "sniper_apex_0x397a16").strip()

GATEWAY_LOCK = threading.RLock()
LOG_BUFFER: deque = deque(maxlen=160)


def send_mobile_alert(title: str, message: str, priority: str = "high", tags: str = "chart_with_upwards_trend"):
    def _worker():
        if NTFY_TOPIC:
            try:
                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=message.encode("utf-8"),
                    headers={
                        "Title": title.encode("utf-8"),
                        "Priority": priority,
                        "Tags": tags,
                    },
                    timeout=4.0,
                )
            except Exception:
                pass
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                tg_text = f"*{title}*\n{message}"
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": tg_text,
                        "parse_mode": "Markdown",
                    },
                    timeout=4.0,
                )
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()


# Cesta Alpha v40.0: BTC permanece como Bússola de Mercado (100% bloqueado para abrir ordens),
# enquanto AAVE e INJ entram como novos ativos de alta precisão ao lado das campeãs SUI, ETH, AVAX, HYPE, NEAR e DOGE!
GLOBAL_BASKET = [
    "BTC", "SUI", "AVAX", "ETH", "HYPE", "NEAR", "DOGE", "AAVE",
    "LTC", "BNB", "UNI", "XRP", "LINK", "ADA", "SOL", "TIA",
    "APT", "OP"
]
COMPASS_ONLY_COINS = {"BTC"}
# Moedas Campeãs Invictas (Tier-1): ETH, SUI, AVAX, HYPE, NEAR, DOGE, AAVE, LTC, XRP, LINK, ADA
# Moedas Ariscas / Alta Volatilidade (High-Beta): exigem extremo duplo (6%-11% / 89%-94%), Book >= 0.20 e pavio de rejeição!
HIGH_BETA_COINS = {"SOL", "TIA", "APT", "OP"}
ELITE_SQUAD_COINS = {"SUI", "AVAX", "ETH", "HYPE", "NEAR", "DOGE"}
CORE_WATCHLIST = ["SUI", "AVAX", "ETH", "HYPE", "NEAR", "DOGE", "AAVE", "LTC", "BNB"]


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def add_log(msg: str):
    ts = time.strftime("%H:%M:%S", time.gmtime())
    entry = f"[{ts} UTC] {msg}"
    LOG_BUFFER.appendleft(entry)
    logger.info(msg)


BOT_STATE: dict[str, Any] = {
    "version": "v50.0 — SOVEREIGN ANTI-FAKEOUT & REAL REVERSAL (Anti-Falso Pavio 1m • Book >= +0.14 • DNA >= 68% • Disparo Instantâneo)",
    "status": "INICIALIZANDO ANTI-FAKEOUT ENGINE v50.0...",
    "trading_enabled": True,
    "account_address": os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", "0x397a16b88f59dcc0ca5ab843842e6a6a6983365c").strip(),
    "agent_address": "N/A",
    # Patrimônio Completo (Perpétuos + Spot + Flutuante)
    "starting_equity_usdc": 0.0,
    "perp_equity_usdc": 0.0,
    "spot_equity_usdc": 0.0,
    "equity_usdc": 0.0,
    "equity_brl": 0.0,
    "free_margin_usdc": 0.0,
    "margin_used_usdc": 0.0,
    "floating_pnl_usdc": 0.0,
    # Estatísticas Reais On-Chain (via info.user_fills)
    "wins_total": 0,
    "losses_total": 0,
    "win_rate_pct": 0.0,
    "avg_win_usdc": 0.0,
    "avg_loss_usdc": 0.0,
    "payoff_ratio": 0.0,
    "realized_profit_usdc": 0.0,
    "realized_profit_brl": 0.0,
    "wins_24h": 0,
    "losses_24h": 0,
    "realized_24h_usdc": 0.0,
    "stats_reset_ts_ms": 0,
    "reset_mode_label": "ERA OMEGA v30+ (REDS ANTIGOS LIMPOS)",
    "daily_goal_usdc": float(os.getenv("DAILY_GOAL_USDC", "1.50")),
    "daily_progress_pct": 0.0,
    "daily_vault_active": False,
    "active_session_mode": "MAPEANDO SESSÃO GLOBAL...",
    "coin_performance_map": {},
    "top_coins_summary": "Aguardando trades do novo ciclo...",
    "recent_closed_trades": [],
    # Memória Global do Mercado Todo
    "market_brain": {
        "regime": "CAÇANDO EXTREMO REAL DA BANDA (<=15% BASE | >=85% TOPO)...",
        "regime_color": "#10b981",
        "allowed_direction": "COMPRA 6%-15% BANDA | VENDA 85%-94% BANDA (BTC = SÓ BÚSSOLA)",
        "breadth_bull_pct": 50.0,
        "breadth_bear_pct": 50.0,
        "btc_impulse_3m_pct": 0.0,
        "eth_impulse_3m_pct": 0.0,
        "top_mover_coin": "N/A",
        "top_mover_ret_3m": 0.0,
        "market_sync_score": 50.0,
        "snapshots_recorded": 0,
        "coins_tracked": len(GLOBAL_BASKET),
        "second_slot_status": "MODO 1 OPERAÇÃO POR VEZ (RISCO BLINDADO)",
        "summary": "BTC fixado como Bússola Exclusiva + AAVE & INJ ativas na cesta Alpha com proteção Anti-Violinada 180s!"
    },
    # Parâmetros de Execução Sniper Prime Elite
    "order_notional": 15.0,
    "leverage": 8,
    "max_positions": 1,                  # 1 única posição focada por vez para nunca tomar perda dupla!
    "round_trip_fee_pct": 0.0007,        # 0.07% taxa total Hyperliquid
    "micro_shield_trigger_pct": 0.0011,  # DEGRAU 0 (+0.11% move / +0.88% ROE) -> Corta o Stop pela metade (-0.05% / ~-$0.04)!
    "micro_shield_lock_pct": -0.0005,    # -0.05% move (Risco reduzido a centavos assim que anda +0.11% a favor!)
    "zero_risk_trigger_pct": 0.0014,     # DEGRAU 1 (+0.14% move / +1.12% ROE) -> Sobe o Stop p/ Entrada (+0.02%) com 0.12% de folga real p/ surfar!
    "zero_risk_lock_pct": 0.0002,        # +0.02% move (Zero-a-Zero na entrada com folga ampla p/ não fechar cedo!)
    "recovery_drawdown_pct": -0.0011,    # Só ativa Recuperação 0x0 se sofrer susto REAL (<= -0.11% move / -0.88% ROE), nunca em respiro de -0.07%!
    "recovery_exit_pct": 0.0003,         # +0.03% move (Sai no 0x0 apenas se sofreu susto real <= -0.11% e perdeu força!)
    "cash_in_band_move_pct": 0.0028,     # +0.28% move (+2.24% ROE) -> Embolsa Green cheio no pico sem deixar voltar!
    "breakeven_trigger_pct": 0.0022,     # DEGRAU 2 (+0.22% move / +1.76% ROE) -> Trava Green líquido positivo em +0.12% move (+0.96% ROE)!
    "breakeven_lock_pct": 0.0012,        # +0.12% move (+0.96% ROE garantido)
    "trail_step1_trigger_pct": 0.0032,   # Degrau 3 (+0.32% move / +2.56% ROE) -> Trava lucro forte (+0.22% move = +1.76% ROE garantido!)
    "trail_step1_dist_pct": 0.0010,
    "trail_step2_trigger_pct": 0.0044,   # Degrau 4 (+0.44% move / +3.52% ROE) -> Trailing aperta para 0.08% do pico!
    "trail_step2_dist_pct": 0.0008,
    "trail_step3_trigger_pct": 0.0058,   # Degrau 5 (+0.58% move / +4.64% ROE) -> Trailing cirúrgico a 0.06% do pico!
    "trail_step3_dist_pct": 0.0006,
    "partial_tp_trigger_pct": 0.0025,    # +0.25% move (+2.00% ROE) -> Realiza 50% no bolso e trava o restante no verde!
    "tp_move_pct": 0.0080,               # +0.80% move (+6.40% ROE) -> Take Profit Direto
    "sl_move_pct": 0.0012,               # -0.12% move (-0.96% ROE) -> STOP TÉCNICO APÓS 180s (Red máximo ~$0.10 USDC)
    "wick_absorption_sl_pct": 0.0020,    # -0.20% move -> Folga Anti-Agulhada nos primeiros 180s se o 15M continuar intacto!
    "watchlist": [
        "BTC", "SUI", "AVAX", "ETH", "HYPE", "NEAR", "DOGE", "AAVE",
        "LTC", "BNB", "UNI", "XRP", "LINK", "ADA", "SOL", "TIA",
        "APT", "OP"
    ],
    "open_positions": [],
    "peak_move_by_coin": {},
    "worst_move_by_coin": {},
    "partial_taken_by_coin": {},
    "notified_step_by_coin": {},
    "ntfy_topic": NTFY_TOPIC,
    "opened_ts_by_coin": {},
    "loss_quarantine_until": {},
    "global_long_lock_until": 0.0,
    "global_short_lock_until": 0.0,
    "global_any_lock_until": 0.0,
    "funding_by_coin": {},
    "open_interest_by_coin": {},
    "radar": {},
    "last_update": "N/A",
    "logs": []
}


class WholeMarketMemoryEngine:
    def __init__(self):
        self.price_tape: dict[str, deque] = {c: deque(maxlen=720) for c in GLOBAL_BASKET}
        self.kalman_state: dict[str, dict[str, float]] = {}
        self.snapshots_count: int = 0
        self.last_disk_save_ts: float = 0.0
        self._load_persisted_memory()

    def _load_persisted_memory(self):
        try:
            if os.path.exists(MEMORY_FILE_PATH):
                with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.snapshots_count = int(data.get("snapshots_count", 0))
                saved_tape = data.get("price_tape", {})
                now = time.time()
                for c, arr in saved_tape.items():
                    if c in self.price_tape and isinstance(arr, list):
                        for item in arr[-240:]:
                            if isinstance(item, list) and len(item) == 2:
                                ts_v = safe_float(item[0], 0.0)
                                px_v = safe_float(item[1], 0.0)
                                if px_v > 0 and (now - ts_v) < 7200:
                                    self.price_tape[c].append((ts_v, px_v))
                for k, v in data.get("peak_move_by_coin", {}).items():
                    BOT_STATE["peak_move_by_coin"][str(k)] = safe_float(v, 0.0)
                for k, v in data.get("worst_move_by_coin", {}).items():
                    BOT_STATE["worst_move_by_coin"][str(k)] = safe_float(v, 0.0)
                for k, v in data.get("partial_taken_by_coin", {}).items():
                    BOT_STATE["partial_taken_by_coin"][str(k)] = bool(v)
                for k, v in data.get("opened_ts_by_coin", {}).items():
                    BOT_STATE["opened_ts_by_coin"][str(k)] = safe_float(v, now)
                for k, v in data.get("loss_quarantine_until", {}).items():
                    qv = safe_float(v, 0.0)
                    if qv > now:
                        BOT_STATE["loss_quarantine_until"][str(k)] = qv
                BOT_STATE["stats_reset_ts_ms"] = int(safe_float(data.get("stats_reset_ts_ms", 0), 0))
                BOT_STATE["starting_equity_usdc"] = safe_float(data.get("starting_equity_usdc", 0.0), 0.0)
                BOT_STATE["global_long_lock_until"] = safe_float(data.get("global_long_lock_until", 0.0), 0.0)
                BOT_STATE["global_short_lock_until"] = safe_float(data.get("global_short_lock_until", 0.0), 0.0)
                BOT_STATE["global_any_lock_until"] = safe_float(data.get("global_any_lock_until", 0.0), 0.0)
        except Exception:
            pass

    def save_persisted_memory(self, force: bool = False):
        now = time.time()
        if not force and (now - self.last_disk_save_ts) < 25.0:
            return
        self.last_disk_save_ts = now
        try:
            serializable_tape = {
                c: [[round(ts, 1), px] for ts, px in list(dq)[-120:] if math.isfinite(px) and px > 0]
                for c, dq in self.price_tape.items()
                if len(dq) > 0
            }
            payload = {
                "snapshots_count": self.snapshots_count,
                "saved_at": now,
                "price_tape": serializable_tape,
                "peak_move_by_coin": BOT_STATE.get("peak_move_by_coin", {}),
                "worst_move_by_coin": BOT_STATE.get("worst_move_by_coin", {}),
                "partial_taken_by_coin": BOT_STATE.get("partial_taken_by_coin", {}),
                "opened_ts_by_coin": BOT_STATE.get("opened_ts_by_coin", {}),
                "loss_quarantine_until": BOT_STATE.get("loss_quarantine_until", {}),
                "stats_reset_ts_ms": BOT_STATE.get("stats_reset_ts_ms", 0),
                "starting_equity_usdc": BOT_STATE.get("starting_equity_usdc", 0.0),
                "global_long_lock_until": BOT_STATE.get("global_long_lock_until", 0.0),
                "global_short_lock_until": BOT_STATE.get("global_short_lock_until", 0.0),
                "global_any_lock_until": BOT_STATE.get("global_any_lock_until", 0.0),
            }
            with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def record_all_mids(self, all_mids: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        self.snapshots_count += 1
        up_real = 0
        down_real = 0
        valid_coins = 0
        top_mover_coin = "ETH"
        top_mover_ret = 0.0

        for coin in GLOBAL_BASKET:
            raw_px = all_mids.get(coin)
            if raw_px is None:
                continue
            px = safe_float(raw_px, 0.0)
            if px <= 0:
                continue
            dq = self.price_tape[coin]
            dq.append((now, px))
            self._update_kalman(coin, px, now)

            if coin in BOT_STATE["radar"]:
                BOT_STATE["radar"][coin]["price"] = px
                BOT_STATE["radar"][coin]["vel_1m_pct"] = self.kalman_state.get(coin, {}).get("v", 0.0)

            # Rastreamento Sub-Segundo de Pico/Fundo para Posição Aberta:
            for op in BOT_STATE.get("open_positions", []):
                if op.get("coin") == coin:
                    epx = safe_float(op.get("entry_px", 0.0), 0.0)
                    if epx > 0:
                        live_mv = ((px - epx) / epx) if op.get("side") == "LONG" else ((epx - px) / epx)
                        if live_mv > safe_float(BOT_STATE["peak_move_by_coin"].get(coin, 0.0), 0.0):
                            BOT_STATE["peak_move_by_coin"][coin] = live_mv
                        if live_mv < safe_float(BOT_STATE["worst_move_by_coin"].get(coin, 0.0), 0.0):
                            BOT_STATE["worst_move_by_coin"][coin] = live_mv

            ret_3m = self.get_return_pct(coin, 180.0)
            valid_coins += 1
            if abs(ret_3m) > abs(top_mover_ret):
                top_mover_ret = ret_3m
                top_mover_coin = coin

            r_entry = BOT_STATE["radar"].get(coin, {})
            htf_str = str(r_entry.get("htf_15m", ""))
            if htf_str == "ALTA 15M":
                up_real += 1
            elif htf_str == "BAIXA 15M":
                down_real += 1

        denom = max(1, valid_coins)
        breadth_bull = round((up_real / denom) * 100.0, 1)
        breadth_bear = round((down_real / denom) * 100.0, 1)

        btc_imp_3m = round(self.get_return_pct("BTC", 180.0), 3)
        eth_imp_3m = round(self.get_return_pct("ETH", 180.0), 3)

        long_lock_rem = max(0.0, BOT_STATE.get("global_long_lock_until", 0.0) - now)
        short_lock_rem = max(0.0, BOT_STATE.get("global_short_lock_until", 0.0) - now)
        any_lock_rem = max(0.0, BOT_STATE.get("global_any_lock_until", 0.0) - now)

        if any_lock_rem > 0:
            regime = f"🧊 PAUSA DE SEGURANÇA PÓS-STOP ({int(any_lock_rem // 60) + 1}m RESTANTES)"
            regime_color = "#f59e0b"
            allowed_dir = "PAUSA ANTI-CASCATA ATIVA"
            summary = "Aguardando a poeira do mercado baixar após o último Stop para não entrar em cascata!"
        elif long_lock_rem > 0:
            regime = f"🛡️ TRAVA ANTI-CASCATA EM LONG ({int(long_lock_rem // 60) + 1}m RESTANTES)"
            regime_color = "#f59e0b"
            allowed_dir = "SOMENTE SHORT NO TOPO (>= 85%)"
            summary = "Compras bloqueadas temporariamente após Stop em LONG — operando apenas SHORT no topo!"
        elif short_lock_rem > 0:
            regime = f"🛡️ TRAVA ANTI-CASCATA EM SHORT ({int(short_lock_rem // 60) + 1}m RESTANTES)"
            regime_color = "#f59e0b"
            allowed_dir = "SOMENTE LONG NO FUNDO (<= 15%)"
            summary = "Vendas bloqueadas temporariamente após Stop em SHORT — operando apenas LONG no fundo!"
        else:
            regime = "🎯 SNIPER ALPHA v40.0: COMPRA 6%-15% BANDA • VENDA 85%-94% BANDA (BTC = SÓ BÚSSOLA)"
            regime_color = "#10b981"
            allowed_dir = "EXTREMO REAL + VELA CONFIRMADA + MARÉ 15M"
            summary = "BTC fixado como Bússola Exclusiva — operando apenas as Altcoins campeãs (ETH, SUI, AVAX, HYPE, AAVE, INJ)!"

        brain = {
            "regime": regime,
            "regime_color": regime_color,
            "allowed_direction": allowed_dir,
            "breadth_bull_pct": breadth_bull,
            "breadth_bear_pct": breadth_bear,
            "btc_impulse_3m_pct": btc_imp_3m,
            "eth_impulse_3m_pct": eth_imp_3m,
            "top_mover_coin": top_mover_coin,
            "top_mover_ret_3m": round(top_mover_ret, 2),
            "market_sync_score": round(max(breadth_bull, breadth_bear), 1),
            "snapshots_recorded": self.snapshots_count,
            "coins_tracked": len(GLOBAL_BASKET),
            "second_slot_status": BOT_STATE["market_brain"].get("second_slot_status", "MODO FOCO ÚNICO"),
            "summary": summary,
        }
        BOT_STATE["market_brain"] = brain
        self.save_persisted_memory(force=False)
        return brain

    def _update_kalman(self, coin: str, price: float, now: float):
        st = self.kalman_state.get(coin)
        if not st or not math.isfinite(st.get("x", 0.0)) or not math.isfinite(st.get("v", 0.0)):
            self.kalman_state[coin] = {"x": price, "v": 0.0, "acc": 0.0, "ts": now}
            return
        dt = max(0.5, now - st.get("ts", now - 1.0))
        prev_x = st["x"]
        prev_v = st["v"]
        raw_vel_pct_per_min = (((price - prev_x) / max(1e-9, prev_x)) * 100.0) * (60.0 / max(1.0, dt))
        raw_vel_pct_per_min = float(np.clip(raw_vel_pct_per_min, -3.5, 3.5))
        new_x = prev_x + 0.45 * (price - prev_x)
        new_v = prev_v + 0.28 * (raw_vel_pct_per_min - prev_v)
        new_acc = new_v - prev_v
        self.kalman_state[coin] = {
            "x": new_x,
            "v": round(new_v, 4),
            "acc": round(new_acc, 4),
            "ts": now,
        }

    def get_return_pct(self, coin: str, lookback_sec: float) -> float:
        dq = self.price_tape.get(coin)
        if not dq or len(dq) < 2:
            return 0.0
        now_ts, now_px = dq[-1]
        target_ts = now_ts - lookback_sec
        base_px = dq[0][1]
        for ts, px in reversed(dq):
            base_px = px
            if ts <= target_ts:
                break
        if base_px <= 0 or not math.isfinite(base_px) or not math.isfinite(now_px):
            return 0.0
        return safe_float(((now_px - base_px) / base_px) * 100.0, 0.0)

    def get_kalman_telemetry(self, coin: str) -> dict[str, float]:
        st = self.kalman_state.get(coin, {})
        v = safe_float(st.get("v", 0.0), 0.0)
        acc = safe_float(st.get("acc", 0.0), 0.0)
        dq = self.price_tape.get(coin)
        live_px = safe_float(dq[-1][1], 0.0) if (dq and len(dq) > 0) else 0.0
        return {
            "live_px": live_px,
            "vel_1m_pct": round(v, 3),
            "acc_1m_pct": round(acc, 3),
            "ret_1m_pct": round(self.get_return_pct(coin, 60.0), 3),
            "ret_3m_pct": round(self.get_return_pct(coin, 180.0), 3),
            "ret_10m_pct": round(self.get_return_pct(coin, 600.0), 3),
        }


class QuantumOracleEngine:
    @staticmethod
    def get_session_and_regime(now: float) -> dict[str, Any]:
        gm = time.gmtime(now)
        is_weekend = gm.tm_wday in (5, 6)  # 5 = Sábado, 6 = Domingo
        hour_utc = gm.tm_hour
        if is_weekend:
            return {
                "is_weekend": True,
                "min_bb_width": 0.0042,       # Exige no mínimo 0.42% de largura de banda (garante espaço físico p/ bater +0.24% de lucro!)
                "cash_in_move": 0.0022,       # +0.22% move (+1.76% ROE) embolsa rápido no topo da banda no fim de semana
                "partial_tp_move": 0.0020,    # +0.20% move (+1.60% ROE) garante 50% no bolso mais cedo
                "label": "🌴 MODO FIM DE SEMANA AUTOMÁTICO (Só Moedas c/ Banda >=0.42% • Cash-In +1.8% ROE)",
            }
        elif 7 <= hour_utc <= 21:
            return {
                "is_weekend": False,
                "min_bb_width": 0.0045,       # 0.45% na Sessão Institucional Londres/NY
                "cash_in_move": 0.0028,       # +0.28% move (+2.24% ROE) para surfar volatilidade institucional
                "partial_tp_move": 0.0024,    # +0.24% move (+1.92% ROE)
                "label": "🏛️ SESSÃO INSTITUCIONAL LONDRES/NY (Banda >=0.45% • Alvo Cheio +2.2% ROE+)",
            }
        else:
            return {
                "is_weekend": False,
                "min_bb_width": 0.0042,       # 0.42% na Sessão Asiática / Madrugada
                "cash_in_move": 0.0024,       # +0.24% move (+1.92% ROE)
                "partial_tp_move": 0.0021,    # +0.21% move (+1.68% ROE)
                "label": "🌙 SESSÃO ASIÁTICA/NOTURNA AUTOMÁTICA (Banda >=0.42% • Alvo Calibrado +1.9% ROE)",
            }

    @staticmethod
    def compute_rsi(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        seed = deltas[:period]
        up = float(seed[seed >= 0].sum()) / period
        down = float(-seed[seed < 0].sum()) / period
        if down == 0:
            return 100.0 if up > 0 else 50.0
        for delta in deltas[period:]:
            upval = float(delta) if delta > 0 else 0.0
            downval = float(-delta) if delta < 0 else 0.0
            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
        rs = up / (down + 1e-9)
        return float(100.0 - (100.0 / (1.0 + rs)))

    @staticmethod
    def compute_ema(closes: np.ndarray, span: int) -> float:
        if len(closes) == 0:
            return 0.0
        alpha = 2.0 / (span + 1.0)
        ema = float(closes[0])
        for price in closes[1:]:
            ema = (float(price) - ema) * alpha + ema
        return ema

    @staticmethod
    def compute_atr_pct(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0045
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                float(highs[i] - lows[i]),
                abs(float(highs[i] - closes[i - 1])),
                abs(float(lows[i] - closes[i - 1])),
            )
            trs.append(tr)
        atr = float(np.mean(trs[-period:]))
        last_px = float(closes[-1])
        if last_px <= 0:
            return 0.0045
        return max(0.0020, min(0.0250, atr / last_px))

    @staticmethod
    def compute_vwap_and_vol_zscore(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray) -> tuple[float, float]:
        window = min(24, len(closes))
        typ = (highs[-window:] + lows[-window:] + closes[-window:]) / 3.0
        vols = volumes[-window:]
        tot_v = float(np.sum(vols))
        vwap = float(np.sum(typ * vols) / tot_v) if tot_v > 0 else float(np.mean(closes[-window:]))
        if len(volumes) >= 10:
            v_mean = float(np.mean(volumes[-20:-1])) if len(volumes) > 20 else float(np.mean(volumes[:-1]))
            v_std = float(np.std(volumes[-20:-1])) + 1e-9 if len(volumes) > 20 else float(np.std(volumes[:-1])) + 1e-9
            vol_z = float(np.clip((float(volumes[-1]) - v_mean) / v_std, -2.5, 4.5))
        else:
            vol_z = 0.0
        return vwap, vol_z

    @staticmethod
    def compute_tactical_dna(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> tuple[float, int, bool]:
        """
        SIMULADOR DE DNA TÁTICO CALIBRADO A FAVOR DA TENDÊNCIA (Últimas 45 velas de 5m):
        Testa apenas os toques na banda que ocorreram A FAVOR da tendência local (ou com vela de rejeição),
        para nunca penalizar uma moeda em tendência de alta quando ela toca no topo ou em tendência de baixa quando toca no fundo!
        Só reprova a moeda se os pullbacks a favor da tendência falharem repetidamente (< 50% com >= 3 falhas).
        """
        n = len(closes)
        if n < 26:
            return (85.0, 0, True)
        dna_wins = 0
        dna_losses = 0
        for i in range(20, n - 4):
            win_slice = closes[i - 19 : i + 1]
            sma_i = float(np.mean(win_slice))
            sma_prev = float(np.mean(closes[i - 20 : i]))
            std_i = float(np.std(win_slice)) + 1e-9
            l_bb_i = sma_i - 2.0 * std_i
            u_bb_i = sma_i + 2.0 * std_i
            bw_i = max(u_bb_i - l_bb_i, float(closes[i]) * 0.002)
            ep = max(1e-9, float(closes[i]))

            low_pos = (float(lows[i]) - l_bb_i) / bw_i
            high_pos = (float(highs[i]) - l_bb_i) / bw_i
            fut_high = float(np.max(highs[i + 1 : i + 5]))
            fut_low = float(np.min(lows[i + 1 : i + 5]))
            trend_up_local = sma_i >= sma_prev * 0.9995
            trend_dn_local = sma_i <= sma_prev * 1.0005

            # Avalia compra no fundo APENAS se a tendência local não estava desabando E houve reação no candle
            if low_pos <= 0.22 and trend_up_local and float(closes[i]) > float(lows[i]):
                bounce_up = (fut_high - ep) / ep
                drop_more = (ep - fut_low) / ep
                if bounce_up >= 0.0013 or fut_high >= (l_bb_i + 0.45 * bw_i):
                    dna_wins += 1
                elif drop_more >= 0.0024 and bounce_up < 0.0009:
                    dna_losses += 1
            # Avalia venda no topo APENAS se a tendência local não estava explodindo E houve rejeição no candle
            elif high_pos >= 0.78 and trend_dn_local and float(closes[i]) < float(highs[i]):
                pull_down = (ep - fut_low) / ep
                pump_more = (fut_high - ep) / ep
                if pull_down >= 0.0013 or fut_low <= (l_bb_i + 0.55 * bw_i):
                    dna_wins += 1
                elif pump_more >= 0.0024 and pull_down < 0.0009:
                    dna_losses += 1

        tot = dna_wins + dna_losses
        if tot == 0:
            return (85.0, 0, True)
        rate = round((dna_wins / tot) * 100.0, 0)
        approved = (rate >= 68.0) and not (dna_losses >= 3 and dna_wins == 0)
        return (rate, tot, approved)

    @classmethod
    def compute_macd_hist(cls, closes: np.ndarray) -> tuple[float, float]:
        if len(closes) < 26:
            return (0.0, 0.0)
        alpha12 = 2.0 / 13.0
        alpha26 = 2.0 / 27.0
        alpha9 = 2.0 / 10.0
        e12 = float(closes[0])
        e26 = float(closes[0])
        macd_series = []
        for px in closes:
            p = float(px)
            e12 = (p - e12) * alpha12 + e12
            e26 = (p - e26) * alpha26 + e26
            macd_series.append(e12 - e26)
        sig = macd_series[0]
        hist = []
        for m in macd_series:
            sig = (m - sig) * alpha9 + sig
            hist.append(m - sig)
        return (float(hist[-2]), float(hist[-1]))

    @classmethod
    def analyze_omni_intelligence(
        cls,
        coin: str,
        candles_5m: list,
        candles_15m: list,
        l2_obi: float,
        funding_rate: float,
        kalman_info: dict[str, float],
        market_brain: dict[str, Any],
    ) -> dict[str, Any]:
        now = time.time()
        if not candles_5m or len(candles_5m) < 25:
            return {
                "price": 0.0,
                "vwap": 0.0,
                "rsi": 50.0,
                "band_pos": 0.50,
                "trend": "NEUTRO",
                "htf_15m": "NEUTRO",
                "l2_obi": 0.0,
                "vol_z": 0.0,
                "vel_1m_pct": 0.0,
                "atr_pct": 0.0045,
                "room_pct": 0.75,
                "strategy": "AGUARDANDO DADOS",
                "score": 50.0,
                "signal": "AGUARDANDO DADOS",
                "updated_ts": now,
            }

        closes = np.array([float(c["c"]) for c in candles_5m], dtype=float)
        highs = np.array([float(c["h"]) for c in candles_5m], dtype=float)
        lows = np.array([float(c["l"]) for c in candles_5m], dtype=float)
        opens = np.array([float(c["o"]) for c in candles_5m], dtype=float)
        volumes = np.array([float(c.get("v", 1.0)) for c in candles_5m], dtype=float)

        # Fusão Tick-a-Tick em Tempo Real: injeta o preço mid ao vivo na vela atual antes de calcular RSI/Banda/MACD!
        live_tick_px = safe_float(kalman_info.get("live_px", 0.0), 0.0)
        if live_tick_px > 0:
            closes[-1] = live_tick_px
            if live_tick_px > highs[-1]:
                highs[-1] = live_tick_px
            if live_tick_px < lows[-1]:
                lows[-1] = live_tick_px

        price = float(closes[-1])
        rsi = cls.compute_rsi(closes, 14)
        prev_rsi = cls.compute_rsi(closes[:-1], 14)
        ema9_5m = cls.compute_ema(closes[-35:], 9)
        ema21_5m = cls.compute_ema(closes[-35:], 21)
        prev_mh, curr_mh = cls.compute_macd_hist(closes)
        atr_pct = cls.compute_atr_pct(highs, lows, closes, 14)
        vwap, vol_z = cls.compute_vwap_and_vol_zscore(highs, lows, closes, volumes)
        dna_rate_pct, dna_touches, dna_approved = cls.compute_tactical_dna(closes, highs, lows)

        htf_15m_state = "NEUTRO"
        htf_bull = False
        htf_bear = False
        if candles_15m and len(candles_15m) >= 15:
            c15 = np.array([float(c["c"]) for c in candles_15m], dtype=float)
            if live_tick_px > 0:
                c15[-1] = live_tick_px
            o15_curr = float(candles_15m[-1].get("o", c15[-1]))
            e9_15 = cls.compute_ema(c15, 9)
            e9_15_prev = cls.compute_ema(c15[:-1], 9)
            e21_15 = cls.compute_ema(c15, 21)
            rsi_15m = cls.compute_rsi(c15, 14)
            # Inclinação Obrigatória da EMA9 de 15M (e9_15_rising / e9_15_falling):
            # Na INJ, a EMA9 de 15M ainda estava abaixo da EMA21, mas JÁ ESTAVA SUBINDO rumo à TRANSIÇÃO 15M!
            # Agora: para ser ALTA 15M, a EMA9_15m não pode estar caindo; para ser BAIXA 15M, a EMA9_15m não pode estar subindo!
            e9_15_rising = e9_15 >= (e9_15_prev * 0.9985)
            e9_15_falling = e9_15 <= (e9_15_prev * 1.0015)
            htf_bull = (
                (e9_15 >= e21_15)
                and e9_15_rising
                and (price >= e21_15 * 0.9978)
                and (rsi_15m >= 46.5)
                and ((price - o15_curr) / max(1e-9, o15_curr) > -0.0035)
            )
            htf_bear = (
                (e9_15 < e21_15)
                and e9_15_falling
                and (price <= e21_15 * 1.0022)
                and (rsi_15m <= 53.5)
                and ((price - o15_curr) / max(1e-9, o15_curr) < 0.0035)
            )
            if htf_bull:
                htf_15m_state = "ALTA 15M"
            elif htf_bear:
                htf_15m_state = "BAIXA 15M"
            else:
                htf_15m_state = "TRANSIÇÃO 15M"

        sma20 = float(np.mean(closes[-20:]))
        std20 = float(np.std(closes[-20:])) + 1e-9
        lower_bb = sma20 - (2.0 * std20)
        upper_bb = sma20 + (2.0 * std20)
        bb_width = max(upper_bb - lower_bb, price * 0.002)
        bb_width_pct = (upper_bb - lower_bb) / max(1e-9, price)
        band_pos = float(np.clip((price - lower_bb) / bb_width, 0.0, 1.0))

        c_range = max(1e-9, float(highs[-1] - lows[-1]))
        # Anti-Falso Pavio de 1º Minuto v50.0: usa denominador mínimo de 0.16% do preço para que 1 único tick ($0.0001 na ADA)
        # em vela recém-aberta jamais simule 50%-100% de pavio falso!
        eff_c_range = max(c_range, price * 0.0016)
        lower_wick_ratio = (min(float(opens[-1]), price) - float(lows[-1])) / eff_c_range
        upper_wick_ratio = (float(highs[-1]) - max(float(opens[-1]), price)) / eff_c_range
        rebound_from_low_pct = (price - float(lows[-1])) / max(1e-9, price)
        pullback_from_high_pct = (float(highs[-1]) - price) / max(1e-9, price)

        is_bull_5m = ema9_5m >= ema21_5m
        vel_1m = safe_float(kalman_info.get("vel_1m_pct", 0.0), 0.0)
        ret_3m = safe_float(kalman_info.get("ret_3m_pct", 0.0), 0.0)
        l2_obi = safe_float(l2_obi, 0.0)

        is_compass_only = coin in COMPASS_ONLY_COINS
        quarantine_rem = BOT_STATE.get("loss_quarantine_until", {}).get(coin, 0.0) - now
        in_quarantine = quarantine_rem > 0
        gm_now = time.gmtime(now)
        is_hour_turn = (gm_now.tm_min >= 58 or gm_now.tm_min <= 2)
        long_locked_global = now < BOT_STATE.get("global_long_lock_until", 0.0) or now < BOT_STATE.get("global_any_lock_until", 0.0)
        short_locked_global = now < BOT_STATE.get("global_short_lock_until", 0.0) or now < BOT_STATE.get("global_any_lock_until", 0.0)

        trend_label = f"{'🟢 ALTA 5M' if is_bull_5m else '🔴 BAIXA 5M'} ({htf_15m_state})"
        macd_rising = curr_mh >= prev_mh
        macd_falling = curr_mh <= prev_mh

        # PILAR 1: Regime Automático Seg-Sex / Fim de Semana / Sessão NY-Londres-Ásia
        session_cfg = cls.get_session_and_regime(now)
        BOT_STATE["active_session_mode"] = session_cfg["label"]
        BOT_STATE["cash_in_band_move_pct"] = session_cfg["cash_in_move"]
        BOT_STATE["partial_tp_trigger_pct"] = session_cfg["partial_tp_move"]
        min_bb_allowed = session_cfg["min_bb_width"]

        # PILAR 2: Memória de Auto-Aprendizado por Moeda (aperta filtro se a moeda tiver derrota recente e dá bônus às campeãs!)
        perf_map = BOT_STATE.get("coin_performance_map", {})
        c_perf = perf_map.get(coin, {"w": 0, "l": 0, "net": 0.0})
        c_wins = int(c_perf.get("w", 0))
        c_losses = int(c_perf.get("l", 0))
        c_net = float(c_perf.get("net", 0.0))
        is_proven_champion = (c_wins >= 1 and c_losses == 0 and c_net > 0.0)
        has_recent_loss_caution = (c_losses >= 1 and c_net < 0.0)
        auto_banned_by_ai = (c_losses >= 2 and c_wins == 0) or (c_net <= -0.25)

        is_high_beta = (coin in HIGH_BETA_COINS) or has_recent_loss_caution
        curr_candle_pct = c_range / max(1e-9, price)
        max_bb_allowed = 0.0210 if is_high_beta else 0.0245
        # Espaço REAL sem piso artificial: mede exatamente quantos % existem entre o preço atual e a banda oposta!
        room_to_upper_pct = max(0.0, (upper_bb - price) / max(1e-9, price))
        room_to_lower_pct = max(0.0, (price - lower_bb) / max(1e-9, price))
        has_safe_band_width = (min_bb_allowed <= bb_width_pct <= max_bb_allowed) and (curr_candle_pct <= 0.0110)
        band_too_wide = (bb_width_pct > max_bb_allowed) or (curr_candle_pct > 0.0110)
        band_too_narrow = bb_width_pct < min_bb_allowed

        body_pct = abs(price - float(opens[-1])) / max(1e-9, price)
        prev_candle_green = float(closes[-2]) >= float(opens[-2])
        prev_candle_red = float(closes[-2]) <= float(opens[-2])

        ret_1m = safe_float(kalman_info.get("ret_1m_pct", 0.0), 0.0)
        pierced_lower_band = float(lows[-1]) < lower_bb
        pierced_upper_band = float(highs[-1]) > upper_bb

        safe_from_bottom_wick = (not pierced_lower_band) or (band_pos >= 0.09 and ret_1m >= 0.005 and l2_obi >= 0.14)
        safe_from_top_wick = (not pierced_upper_band) or (band_pos <= 0.91 and ret_1m <= -0.005 and l2_obi <= -0.14)

        no_waterfall_down = (ret_3m > -0.14) or (ret_1m >= 0.01 and vel_1m >= 0.005)
        no_waterfall_up = (ret_3m < 0.14) or (ret_1m <= -0.01 and vel_1m <= -0.005)

        # Confirmação de Reação Real da Vela de 5m v50.0 (Exige reação física >= 0.08% do fundo/topo, bloqueando 1-tick de ruído!):
        candle_turning_up = (
            price > float(opens[-1])
            and safe_from_bottom_wick
            and no_waterfall_down
            and rebound_from_low_pct >= 0.0008
            and (body_pct >= 0.0006 or lower_wick_ratio >= 0.24 or (prev_candle_green and body_pct >= 0.0004))
        )
        candle_turning_down = (
            price < float(opens[-1])
            and safe_from_top_wick
            and no_waterfall_up
            and pullback_from_high_pct >= 0.0008
            and (body_pct >= 0.0006 or upper_wick_ratio >= 0.24 or (prev_candle_red and body_pct >= 0.0004))
        )

        # Calibragem Sweet-Spot v43.5:
        # Moedas Tier-1 Campeãs (ETH, SUI, AVAX, HYPE, NEAR, DOGE, AAVE, LTC, XRP, LINK, ADA): 6%-22% LONG e 78%-94% SHORT!
        # Moedas High-Beta (SOL, INJ, ARB, TIA, APT, OP): 6%-15% LONG e 85%-94% SHORT!
        max_long_band = 0.15 if is_high_beta else 0.22
        min_short_band = 0.85 if is_high_beta else 0.78
        in_safe_long_zone = 0.06 <= band_pos <= max_long_band
        in_safe_short_zone = min_short_band <= band_pos <= 0.94
        outside_band_bottom = band_pos < 0.06
        outside_band_top = band_pos > 0.94

        btc_imp_3m = safe_float(market_brain.get("btc_impulse_3m_pct", 0.0), 0.0)
        eth_imp_3m = safe_float(market_brain.get("eth_impulse_3m_pct", 0.0), 0.0)
        breadth_bull = safe_float(market_brain.get("breadth_bull_pct", 50.0), 50.0)
        breadth_bear = safe_float(market_brain.get("breadth_bear_pct", 50.0), 50.0)
        coins_crashing_0pct = sum(1 for r in BOT_STATE.get("radar", {}).values() if safe_float(r.get("band_pos", 0.5), 0.5) <= 0.03)
        coins_pumping_100pct = sum(1 for r in BOT_STATE.get("radar", {}).values() if safe_float(r.get("band_pos", 0.5), 0.5) >= 0.97)

        eth_radar = BOT_STATE.get("radar", {}).get("ETH", {})
        leaders_pumping_bull = (
            str(eth_radar.get("htf_15m", "")) == "ALTA 15M"
            and safe_float(eth_radar.get("band_pos", 0.5), 0.5) >= 0.80
            and eth_imp_3m >= 0.08
        )
        leaders_dumping_bear = (
            str(eth_radar.get("htf_15m", "")) == "BAIXA 15M"
            and safe_float(eth_radar.get("band_pos", 0.5), 0.5) <= 0.20
            and eth_imp_3m <= -0.08
        )

        market_allows_long = (breadth_bear < 55.0) and (coins_crashing_0pct <= 3) and (not leaders_dumping_bear)
        market_allows_short = (breadth_bull < 55.0) and (coins_pumping_100pct <= 3) and (not leaders_pumping_bull)

        # Destrava do Pullback: durante um recuo normal p/ dar compra, o BTC 3m oscila entre -0.03% e -0.08%.
        # Só bloqueia se o BTC/ETH estiverem despejando (> -0.10%)!
        btc_allows_long = (
            market_allows_long
            and (btc_imp_3m > -0.18)
            and (eth_imp_3m > -0.18)
        )
        btc_allows_short = (
            market_allows_short
            and (btc_imp_3m < 0.18)
            and (eth_imp_3m < 0.18)
        )

        strategy_name = "🔍 MONITORANDO ZONA DE PREÇO"
        signal = "NEUTRO"
        score = 58.0

        min_obi_req = 0.18 if is_high_beta else 0.14

        is_bear_5m = not is_bull_5m
        btc_band_now = safe_float(BOT_STATE.get("radar", {}).get("BTC", {}).get("band_pos", 0.50), 0.50)
        eth_band_now = safe_float(eth_radar.get("band_pos", 0.50), 0.50)

        isolated_outlier_pump = (band_pos >= 0.85) and (btc_band_now <= 0.15 and eth_band_now <= 0.15)
        isolated_outlier_dump = (band_pos <= 0.15) and (btc_band_now >= 0.85 and eth_band_now >= 0.85)

        vwap_dist_pct = ((price - vwap) / max(1e-9, vwap)) if vwap > 0 else 0.0
        # Correção Crítica v50.0: Se o 5M virou para BAIXA 5M (como na ADA às 16:21), NUNCA compra no meio da queda (12%-24%);
        # se 5M estiver em baixa contra o 15M, exige exaustão extrema na base (<= 10% da banda), RSI <= 41 e Book >= +0.18!
        breakout_against_short = is_bull_5m and (vwap_dist_pct > 0.0080 or ret_3m > 0.18 or band_pos < 0.90)
        breakdown_against_long = is_bear_5m and (vwap_dist_pct < -0.0080 or ret_3m < -0.18 or band_pos > 0.10)

        # 1) GATILHOS SNIPER LONG — SWEET-SPOT (6% a 18% Tier-1 c/ 5M Alta | 6% a 10% se 5M recuando)
        max_long_band = 0.14 if is_high_beta else (0.18 if is_bull_5m else 0.10)
        min_short_band = 0.86 if is_high_beta else (0.82 if is_bear_5m else 0.90)
        in_safe_long_zone = 0.06 <= band_pos <= max_long_band
        in_safe_short_zone = min_short_band <= band_pos <= 0.94

        rsi_rebounding_up = (rsi >= prev_rsi) or (rebound_from_low_pct >= 0.0012 and lower_wick_ratio >= 0.28 and ret_1m >= 0.008)
        rsi_rejecting_down = (rsi <= prev_rsi) or (pullback_from_high_pct >= 0.0012 and upper_wick_ratio >= 0.28 and ret_1m <= -0.008)

        long_base_pullback = (
            not is_compass_only
            and not auto_banned_by_ai
            and dna_approved
            and not in_quarantine
            and not is_hour_turn
            and not long_locked_global
            and not isolated_outlier_dump
            and not breakdown_against_long
            and btc_allows_long
            and htf_bull
            and is_bull_5m
            and has_safe_band_width
            and in_safe_long_zone
            and 24.0 <= rsi <= 45.5
            and rsi_rebounding_up
            and candle_turning_up
            and (macd_rising or (lower_wick_ratio >= 0.26 and l2_obi >= 0.20))
            and l2_obi >= min_obi_req
            and vel_1m >= 0.003
            and funding_rate < 0.0008
        )
        long_extreme_spring = (
            not is_compass_only
            and not auto_banned_by_ai
            and dna_approved
            and not in_quarantine
            and not is_hour_turn
            and not long_locked_global
            and not isolated_outlier_dump
            and btc_allows_long
            and htf_bull
            and has_safe_band_width
            and 0.06 <= band_pos <= 0.11
            and rsi <= 40.5
            and rsi_rebounding_up
            and candle_turning_up
            and lower_wick_ratio >= 0.28
            and l2_obi >= max(0.18, min_obi_req)
            and vel_1m >= 0.004
        )

        # 2) GATILHOS SNIPER SHORT — SWEET-SPOT (82% a 94% Tier-1 c/ 5M Baixa | 90% a 94% se 5M subindo)
        short_top_rally = (
            not is_compass_only
            and not auto_banned_by_ai
            and dna_approved
            and not in_quarantine
            and not is_hour_turn
            and not short_locked_global
            and not isolated_outlier_pump
            and not breakout_against_short
            and btc_allows_short
            and htf_bear
            and is_bear_5m
            and has_safe_band_width
            and in_safe_short_zone
            and 54.5 <= rsi <= 76.0
            and rsi_rejecting_down
            and candle_turning_down
            and (macd_falling or (upper_wick_ratio >= 0.26 and l2_obi <= -0.20))
            and l2_obi <= -min_obi_req
            and vel_1m <= -0.003
            and funding_rate > -0.0008
        )
        short_extreme_upthrust = (
            not is_compass_only
            and not auto_banned_by_ai
            and dna_approved
            and not in_quarantine
            and not is_hour_turn
            and not short_locked_global
            and not isolated_outlier_pump
            and btc_allows_short
            and htf_bear
            and has_safe_band_width
            and 0.89 <= band_pos <= 0.94
            and rsi >= 59.5
            and rsi_rejecting_down
            and candle_turning_down
            and upper_wick_ratio >= 0.28
            and l2_obi <= -max(0.18, min_obi_req)
            and vel_1m <= -0.004
        )

        is_elite_squad = coin in ELITE_SQUAD_COINS
        dna_bonus = 1.5 if dna_rate_pct >= 80.0 else 0.0
        elite_bonus = 1.8 if is_elite_squad else 0.0
        champion_bonus = (2.2 if is_proven_champion else (0.0 if not has_recent_loss_caution else -1.5)) + dna_bonus + elite_bonus
        if in_safe_long_zone and htf_bull and not is_compass_only:
            dist_from_sweet = abs(band_pos - 0.10)
            score += max(0.0, (0.16 - dist_from_sweet) * 60.0) + max(0.0, l2_obi * 18.0) + champion_bonus
        elif in_safe_short_zone and htf_bear and not is_compass_only:
            dist_from_sweet = abs(band_pos - 0.90)
            score += max(0.0, (0.16 - dist_from_sweet) * 60.0) + max(0.0, -l2_obi * 18.0) + champion_bonus

        if is_compass_only:
            signal = "BÚSSOLA"
            strategy_name = f"🧭 BÚSSOLA DO MERCADO (BTC 3m: {btc_imp_3m:+.2f}% — SOMENTE LEITURA)"
            score = 50.0
        elif long_extreme_spring:
            signal = "SNIPER LONG"
            strategy_name = f"💎 FUNDO FORTRESS ({int(band_pos*100)}%) + ALTA 15M"
            score = max(score, 94.5 + min(4.5, l2_obi * 10.0))
        elif long_base_pullback:
            signal = "SNIPER LONG"
            strategy_name = f"🟢 COMPRA FORTRESS ({int(band_pos*100)}%) + ALTA 15M"
            score = max(score, 92.0 + min(5.0, l2_obi * 9.0))
        elif short_extreme_upthrust:
            signal = "SNIPER SHORT"
            strategy_name = f"💎 TOPO FORTRESS ({int(band_pos*100)}%) + BAIXA 15M"
            score = max(score, 94.5 + min(4.5, -l2_obi * 10.0))
        elif short_top_rally:
            signal = "SNIPER SHORT"
            strategy_name = f"🔴 VENDA FORTRESS ({int(band_pos*100)}%) + BAIXA 15M"
            score = max(score, 92.0 + min(5.0, -l2_obi * 9.0))
        else:
            if auto_banned_by_ai:
                strategy_name = f"🧠 AUTO-APRENDIZADO: BLOQUEADA NO CICLO ({c_wins}W/{c_losses}L | ${c_net:+.2f})"
                score = 40.0
            elif not dna_approved:
                strategy_name = f"🧬 DNA TÁTICO REPROVADO ({dna_rate_pct:.0f}% NAS ÚLTIMAS 4H — ROMPENDO CANAL)"
                score = 42.0
            elif in_quarantine:
                strategy_name = f"🧊 QUARENTENA PÓS-STOP ({int(quarantine_rem // 60) + 1}m)"
                score = 45.0
            elif is_hour_turn:
                strategy_name = "🛡️ VIRADA DE HORA INSTITUCIONAL (:58-:02 UTC — FILTRO ATIVO)"
                score = 50.0
            elif band_too_wide:
                strategy_name = f"🛡️ BLOQUEADO (VOLATILIDADE DE PAVIO {bb_width_pct*100:.2f}% > {max_bb_allowed*100:.2f}%)"
                score = 52.0
            elif band_too_narrow:
                strategy_name = f"⏳ CANAL ESTREITO ({bb_width_pct*100:.2f}% < {min_bb_allowed*100:.2f}%) — AGUARDANDO EXPANSÃO"
                score = 54.0
            elif htf_bull and not market_allows_long:
                if leaders_dumping_bear:
                    strategy_name = "🛡️ LONG BLOQUEADO (LÍDERES ETH/SOL EM BAIXA 15M PUXANDO MERCADO)"
                else:
                    strategy_name = f"🛡️ LONG BLOQUEADO (MARÉ: {breadth_bear:.0f}% DO MERCADO EM BAIXA 15M)"
                score = 50.0
            elif htf_bull and not btc_allows_long:
                strategy_name = f"🛡️ LONG BLOQUEADO (BTC {btc_imp_3m:+.2f}% / ETH {eth_imp_3m:+.2f}% RECUANDO)"
                score = 55.0
            elif htf_bear and not market_allows_short:
                if leaders_pumping_bull:
                    strategy_name = "🛡️ SHORT BLOQUEADO (LÍDERES ETH/SOL EM ALTA 15M PUXANDO MERCADO)"
                else:
                    strategy_name = f"🛡️ SHORT BLOQUEADO (MARÉ: {breadth_bull:.0f}% DO MERCADO EM ALTA 15M)"
                score = 50.0
            elif htf_bear and not btc_allows_short:
                strategy_name = f"🛡️ SHORT BLOQUEADO (BTC {btc_imp_3m:+.2f}% / ETH {eth_imp_3m:+.2f}% SUBINDO)"
                score = 55.0
            elif outside_band_bottom:
                strategy_name = f"⏳ FORA DA BANDA ({int(band_pos*100)}%) — ESPERANDO VOLTAR >= 6%"
                score = 72.0
            elif outside_band_top:
                strategy_name = f"⏳ FORA DA BANDA ({int(band_pos*100)}%) — ESPERANDO VOLTAR <= 94%"
                score = 72.0
            elif htf_bear and breakout_against_short:
                strategy_name = f"🛡️ SHORT BLOQUEADO (ROMPIMENTO 5M FORTE RSI {rsi:.1f} — EVITANDO VIOLINADA)"
                score = 54.0
            elif htf_bull and breakdown_against_long:
                strategy_name = f"🛡️ LONG BLOQUEADO (QUEDA 5M FORTE RSI {rsi:.1f} — EVITANDO FACA CAINDO)"
                score = 54.0
            elif isolated_outlier_pump:
                strategy_name = "🛡️ SHORT BLOQUEADO (MOEDA DESGARRADA SUBINDO CONTRA BTC/ETH NO FUNDO)"
                score = 51.0
            elif isolated_outlier_dump:
                strategy_name = "🛡️ LONG BLOQUEADO (MOEDA DESGARRADA CAINDO CONTRA BTC/ETH NO TOPO)"
                score = 51.0
            elif htf_bull and band_pos > max_long_band:
                strategy_name = f"🚫 COMPRA BLOQUEADA (BANDA {int(band_pos*100)}% > {int(max_long_band*100)}%)"
                score = min(score, 62.0)
            elif htf_bear and band_pos < min_short_band:
                strategy_name = f"🚫 VENDA BLOQUEADA (BANDA {int(band_pos*100)}% < {int(min_short_band*100)}%)"
                score = min(score, 62.0)
            elif htf_bull and in_safe_long_zone and (not candle_turning_up or rsi <= prev_rsi or vel_1m < 0.004):
                strategy_name = f"⏳ FUNDO ({int(band_pos*100)}%) — AGUARDANDO VELA & MACD VIRAREM"
                score = min(score, 82.0)
            elif htf_bear and in_safe_short_zone and (not candle_turning_down or rsi >= prev_rsi or vel_1m > -0.004):
                strategy_name = f"⏳ TOPO ({int(band_pos*100)}%) — AGUARDANDO VELA & MACD VIRAREM"
                score = min(score, 82.0)
            elif htf_bull and l2_obi < min_obi_req:
                strategy_name = f"⏳ FUNDO ({int(band_pos*100)}%) — AGUARDANDO BOOK >= +{min_obi_req:.2f}"
                score = min(score, 78.0)
            elif htf_bear and l2_obi > -min_obi_req:
                strategy_name = f"⏳ TOPO ({int(band_pos*100)}%) — AGUARDANDO BOOK <= -{min_obi_req:.2f}"
                score = min(score, 78.0)
            else:
                strategy_name = "🔍 AGUARDANDO FUNDO/TOPO CIRÚRGICO (6%-15% OU 85%-94%)"

        active_room = room_to_upper_pct if htf_bull else room_to_lower_pct

        return {
            "price": price,
            "vwap": round(vwap, 4),
            "rsi": round(rsi, 1),
            "band_pos": round(band_pos, 2),
            "ema_fast": ema9_5m,
            "ema_slow": ema21_5m,
            "trend": trend_label,
            "htf_15m": htf_15m_state,
            "htf_bull": htf_bull,
            "htf_bear": htf_bear,
            "tf_conflict": False,
            "l2_obi": round(l2_obi, 2),
            "vol_z": round(vol_z, 2),
            "vel_1m_pct": round(vel_1m, 3),
            "ret_3m_pct": round(ret_3m, 2),
            "atr_pct": round(atr_pct, 4),
            "room_pct": round(active_room * 100.0, 2),
            "dna_rate_pct": dna_rate_pct,
            "dna_approved": dna_approved,
            "strategy": strategy_name,
            "score": round(min(99.0, score), 1),
            "signal": signal,
            "updated_ts": now,
        }


class HyperliquidDeFiGateway:
    def __init__(self, memory_engine: WholeMarketMemoryEngine):
        self.memory = memory_engine
        self.account_address = BOT_STATE["account_address"].lower()
        raw_key = os.getenv(
            "HYPERLIQUID_AGENT_KEY",
            "0xdb66798e5ade2d8e35a57a9b833e21ac02a01ce9a9f908ede16c8a61312ba9ee"
        ).strip()
        if not raw_key:
            raise ValueError("HYPERLIQUID_AGENT_KEY ausente nas variáveis de ambiente!")
        if not raw_key.startswith("0x"):
            raw_key = "0x" + raw_key
        self.agent_wallet: LocalAccount = Account.from_key(raw_key)
        BOT_STATE["agent_address"] = self.agent_wallet.address
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(
            wallet=self.agent_wallet,
            base_url=constants.MAINNET_API_URL,
            account_address=self.account_address
        )
        self.meta = self.info.meta()
        self.sz_decimals = {asset["name"]: asset["szDecimals"] for asset in self.meta["universe"]}
        self.cooldowns: dict[str, float] = {}
        self.configured_leverage: dict[str, int] = {}
        self.cache_5m: dict[str, tuple[float, list]] = {}
        self.cache_15m: dict[str, tuple[float, list]] = {}
        self.cache_l2: dict[str, tuple[float, float]] = {}
        self.last_ctx_sync_ts: float = 0.0
        self.last_fills_sync_ts: float = 0.0
        add_log(
            f"🎯 Sovereign Compass & Alpha v40.0 Conectado | Conta: {self.account_address[:8]}... | "
            f"BTC = Bússola + AAVE & INJ Ativas + Anti-Violinada 180s!"
        )
        threading.Thread(target=self.preconfigure_watchlist_leverage, daemon=True).start()

    def _hl_coin(self, coin: str) -> str:
        if coin in self.sz_decimals:
            return coin
        k_sym = f"k{coin}"
        if k_sym in self.sz_decimals:
            return k_sym
        return coin

    def preconfigure_watchlist_leverage(self):
        lev = BOT_STATE["leverage"]
        for coin in BOT_STATE["watchlist"]:
            if coin in COMPASS_ONLY_COINS:
                continue
            if self.configured_leverage.get(coin) == lev:
                continue
            try:
                hl_c = self._hl_coin(coin)
                with GATEWAY_LOCK:
                    self.exchange.update_leverage(lev, hl_c, is_cross=True)
                self.configured_leverage[coin] = lev
            except Exception:
                pass
            time.sleep(0.15)

    def sync_global_market_tape(self) -> dict[str, Any]:
        try:
            all_mids = self.info.all_mids()
            if isinstance(all_mids, dict):
                if "PEPE" not in all_mids and "kPEPE" in all_mids:
                    all_mids["PEPE"] = all_mids["kPEPE"]
                return self.memory.record_all_mids(all_mids)
        except Exception as e:
            logger.debug(f"Aviso ao gravar fita global all_mids: {e}")
        return BOT_STATE["market_brain"]

    def can_open_next_position(self, open_positions: list, effective_max_pos: int) -> tuple[bool, str]:
        now = time.time()
        any_rem = BOT_STATE.get("global_any_lock_until", 0.0) - now
        if any_rem > 0:
            BOT_STATE["market_brain"]["second_slot_status"] = f"🧊 PAUSA PÓS-STOP ({int(any_rem // 60) + 1}m RESTANTES)"
            return (False, "POST_STOP_PAUSE")

        if len(open_positions) == 0:
            BOT_STATE["market_brain"]["second_slot_status"] = "SLOT ÚNICO LIVRE (CAÇANDO EXTREMO 6%-15% OU 85%-94%)"
            return (True, "SLOT_1_OPEN")
        else:
            p0 = open_positions[0]
            BOT_STATE["market_brain"]["second_slot_status"] = f"🔒 FOCADO 100% EM {p0['coin']} (PROIBIDO ABRIR 2ª POSIÇÃO)"
            return (False, "SINGLE_FOCUS_MODE")

    def sync_onchain_trade_history(self, force: bool = False):
        now = time.time()
        if not force and (now - self.last_fills_sync_ts) < 20.0:
            return
        try:
            fills = self.info.user_fills(self.account_address)
            self.last_fills_sync_ts = now
            if not isinstance(fills, list):
                return

            wins_all = 0
            losses_all = 0
            sum_wins_usdc = 0.0
            sum_losses_usdc = 0.0
            net_pnl_all = 0.0
            wins_24h = 0
            losses_24h = 0
            net_pnl_24h = 0.0
            cutoff_24h_ms = int((now - 86400) * 1000)

            grouped_by_oid: dict[Any, dict[str, Any]] = {}
            for f in fills:
                closed_pnl = float(f.get("closedPnl", 0.0))
                if abs(closed_pnl) < 1e-7:
                    continue
                oid = f.get("oid") or f"{f.get('coin')}_{f.get('time')}"
                fee = float(f.get("fee", 0.0))
                net_fill = closed_pnl - fee
                t_ms = int(f.get("time", 0))
                raw_c = str(f.get("coin", "?"))
                coin = "PEPE" if raw_c == "kPEPE" and "PEPE" in GLOBAL_BASKET else raw_c
                px = float(f.get("px", 0.0))
                sz = float(f.get("sz", 0.0))
                dir_str = str(f.get("dir", f.get("side", "")))

                if oid not in grouped_by_oid:
                    grouped_by_oid[oid] = {
                        "time_ms": t_ms,
                        "coin": coin,
                        "px": px,
                        "sz": sz,
                        "net_usdc": net_fill,
                        "dir": dir_str,
                    }
                else:
                    grouped_by_oid[oid]["net_usdc"] += net_fill
                    grouped_by_oid[oid]["sz"] += sz
                    grouped_by_oid[oid]["time_ms"] = max(grouped_by_oid[oid]["time_ms"], t_ms)

            all_events = sorted(grouped_by_oid.values(), key=lambda x: x["time_ms"], reverse=True)

            # Consolida fills do mesmo fechamento (janela de 12s na mesma moeda)
            merged_events: list[dict[str, Any]] = []
            for ev in all_events:
                if (
                    merged_events
                    and merged_events[-1]["coin"] == ev["coin"]
                    and abs(merged_events[-1]["time_ms"] - ev["time_ms"]) <= 12000
                ):
                    merged_events[-1]["net_usdc"] += ev["net_usdc"]
                    merged_events[-1]["sz"] += ev["sz"]
                else:
                    merged_events.append(dict(ev))

            reset_ts_ms = int(BOT_STATE.get("stats_reset_ts_ms", 0))
            if reset_ts_ms <= 0 and len(merged_events) > 2:
                # Mantém desde o início da Era v30+ por padrão se não foi zerado manualmente
                reset_ts_ms = 0

            filtered_events = [
                ev for ev in merged_events
                if (reset_ts_ms <= 0 or ev["time_ms"] >= reset_ts_ms)
            ]

            coin_stats: dict[str, dict[str, float]] = {}
            recent_formatted = []

            for ev in filtered_events:
                net_v = round(float(ev["net_usdc"]), 4)
                c_sym = ev["coin"]
                is_scratch_breakeven = (-0.045 <= net_v < 0.0)

                if c_sym not in coin_stats:
                    coin_stats[c_sym] = {"w": 0, "l": 0, "net": 0.0}
                coin_stats[c_sym]["net"] += net_v

                if net_v >= 0:
                    wins_all += 1
                    sum_wins_usdc += net_v
                    coin_stats[c_sym]["w"] += 1
                    res_label = "🏆 VITÓRIA (GREEN)"
                elif is_scratch_breakeven:
                    res_label = "🛡️ ZERO-A-ZERO (TAXA)"
                else:
                    losses_all += 1
                    sum_losses_usdc += abs(net_v)
                    coin_stats[c_sym]["l"] += 1
                    res_label = "🔴 DERROTA (RED)"

                net_pnl_all += net_v
                if ev["time_ms"] >= cutoff_24h_ms:
                    net_pnl_24h += net_v
                    if net_v >= 0:
                        wins_24h += 1
                    elif not is_scratch_breakeven:
                        losses_24h += 1

                if len(recent_formatted) < 18:
                    dt_str = time.strftime("%d/%m %H:%M:%S", time.gmtime(ev["time_ms"] / 1000.0))
                    recent_formatted.append({
                        "time_str": dt_str,
                        "coin": c_sym,
                        "result": res_label,
                        "px": ev["px"],
                        "net_usdc": round(net_v, 2),
                        "net_brl": round(net_v * USD_BRL_RATE, 2),
                        "is_win": net_v >= 0,
                        "is_scratch": is_scratch_breakeven,
                    })

            tot_decisions = wins_all + losses_all
            win_rate = (wins_all / tot_decisions * 100.0) if tot_decisions > 0 else 0.0
            avg_win = (sum_wins_usdc / wins_all) if wins_all > 0 else 0.0
            avg_loss = (sum_losses_usdc / losses_all) if losses_all > 0 else 0.0
            payoff = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 1.0)

            BOT_STATE["wins_total"] = wins_all
            BOT_STATE["losses_total"] = losses_all
            BOT_STATE["win_rate_pct"] = round(win_rate, 1)
            BOT_STATE["avg_win_usdc"] = round(avg_win, 2)
            BOT_STATE["avg_loss_usdc"] = round(avg_loss, 2)
            BOT_STATE["payoff_ratio"] = round(payoff, 2)
            BOT_STATE["realized_profit_usdc"] = round(net_pnl_all, 2)
            BOT_STATE["realized_profit_brl"] = round(net_pnl_all * USD_BRL_RATE, 2)
            BOT_STATE["wins_24h"] = wins_24h
            BOT_STATE["losses_24h"] = losses_24h
            BOT_STATE["realized_24h_usdc"] = round(net_pnl_24h, 2)

            goal_u = max(0.10, float(BOT_STATE.get("daily_goal_usdc", 1.50)))
            prog_pct = max(0.0, min(100.0, (net_pnl_all / goal_u) * 100.0))
            BOT_STATE["daily_progress_pct"] = round(prog_pct, 1)
            BOT_STATE["daily_vault_active"] = (net_pnl_all >= goal_u) or (net_pnl_24h >= goal_u)
            BOT_STATE["coin_performance_map"] = coin_stats

            if coin_stats:
                sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1]["net"], reverse=True)
                parts = []
                for cn, st in sorted_coins:
                    tot_c = int(st["w"] + st["l"])
                    wr_c = int(round((st["w"] / tot_c) * 100)) if tot_c > 0 else 100
                    parts.append(f"{cn}: {int(st['w'])}W/{int(st['l'])}L ({wr_c}% | ${st['net']:+.2f})")
                BOT_STATE["top_coins_summary"] = " • ".join(parts)
            else:
                BOT_STATE["top_coins_summary"] = "Placar zerado — aguardando o 1º trade do novo ciclo!"

            BOT_STATE["recent_closed_trades"] = recent_formatted
        except Exception as e:
            logger.debug(f"Aviso ao sincronizar histórico user_fills: {e}")

    def refresh_funding_and_open_interest(self):
        now = time.time()
        if (now - self.last_ctx_sync_ts) < 60.0:
            return
        try:
            meta_ctx = self.info.meta_and_asset_ctxs()
            self.last_ctx_sync_ts = now
            if isinstance(meta_ctx, list) and len(meta_ctx) >= 2:
                universe = meta_ctx[0].get("universe", [])
                ctxs = meta_ctx[1]
                for idx, asset_info in enumerate(universe):
                    c_name = asset_info.get("name")
                    norm_name = "PEPE" if c_name == "kPEPE" and "PEPE" in GLOBAL_BASKET else c_name
                    if norm_name in GLOBAL_BASKET and idx < len(ctxs):
                        ctx = ctxs[idx]
                        BOT_STATE["funding_by_coin"][norm_name] = float(ctx.get("funding", 0.0))
                        BOT_STATE["open_interest_by_coin"][norm_name] = float(ctx.get("openInterest", 0.0))
        except Exception:
            pass

    def fetch_l2_obi_cached(self, coin: str, ttl_sec: float = 20.0) -> float:
        now = time.time()
        cached = self.cache_l2.get(coin)
        if cached and (now - cached[0]) < ttl_sec:
            return cached[1]
        try:
            snap = self.info.l2_snapshot(self._hl_coin(coin))
            levels = snap.get("levels", [])
            if len(levels) >= 2:
                bids = levels[0][:15]
                asks = levels[1][:15]
                bid_vol = sum(float(b.get("sz", 0.0)) * (1.5 if i < 5 else 1.0) for i, b in enumerate(bids))
                ask_vol = sum(float(a.get("sz", 0.0)) * (1.5 if i < 5 else 1.0) for i, a in enumerate(asks))
                tot = bid_vol + ask_vol
                if tot > 0:
                    val = round((bid_vol - ask_vol) / tot, 2)
                    self.cache_l2[coin] = (now, val)
                    return val
        except Exception:
            pass
        return cached[1] if cached else 0.0

    def fetch_candles_cached(self, coin: str, interval: str = "5m", count: int = 45, ttl_override: float | None = None) -> list:
        now = time.time()
        if interval == "15m":
            ttl = ttl_override if ttl_override is not None else 150.0
            cached_15 = self.cache_15m.get(coin)
            if cached_15 and (now - cached_15[0]) < ttl:
                return cached_15[1]
            now_ms = int(now * 1000)
            start_ms = now_ms - (count * 15 * 60 * 1000)
            data = self.info.candles_snapshot(self._hl_coin(coin), "15m", start_ms, now_ms)
            if data:
                self.cache_15m[coin] = (now, data)
            return data or (cached_15[1] if cached_15 else [])
        else:
            ttl = ttl_override if ttl_override is not None else 20.0
            cached_5 = self.cache_5m.get(coin)
            if cached_5 and (now - cached_5[0]) < ttl:
                return cached_5[1]
            now_ms = int(now * 1000)
            start_ms = now_ms - (count * 5 * 60 * 1000)
            data = self.info.candles_snapshot(self._hl_coin(coin), "5m", start_ms, now_ms)
            if data:
                self.cache_5m[coin] = (now, data)
            return data or (cached_5[1] if cached_5 else [])

    def sync_portfolio(self):
        try:
            now = time.time()
            user_state = self.info.user_state(self.account_address)
            margin_summary = user_state.get("marginSummary", {})
            cross_summary = user_state.get("crossMarginSummary", {})
            perp_equity = max(
                float(margin_summary.get("accountValue", 0.0)),
                float(cross_summary.get("accountValue", 0.0)),
            )
            total_margin_used = max(
                float(margin_summary.get("totalMarginUsed", 0.0)),
                float(cross_summary.get("totalMarginUsed", 0.0)),
            )
            withdrawable = float(user_state.get("withdrawable", 0.0))

            spot_usdc = 0.0
            try:
                spot_state = self.info.spot_user_state(self.account_address)
                for bal in spot_state.get("balances", []):
                    if bal.get("coin") == "USDC":
                        spot_usdc = float(bal.get("total", 0.0))
                        break
            except Exception:
                pass

            open_pos = []
            active_symbols_now = set()
            floating_sum = 0.0
            pos_margin_sum = 0.0
            peak_upgraded = False

            for pos in user_state.get("assetPositions", []):
                item = pos.get("position", {})
                szi = float(item.get("szi", 0.0))
                if szi != 0:
                    raw_pos_c = item.get("coin")
                    coin = "PEPE" if raw_pos_c == "kPEPE" and "PEPE" in GLOBAL_BASKET else raw_pos_c
                    active_symbols_now.add(coin)
                    if coin not in BOT_STATE["opened_ts_by_coin"]:
                        BOT_STATE["opened_ts_by_coin"][coin] = now
                    entry_px = float(item.get("entryPx", 0.0))
                    pnl = float(item.get("unrealizedPnl", 0.0))
                    margin_used_pos = float(item.get("marginUsed", 0.0))
                    floating_sum += pnl
                    pos_margin_sum += margin_used_pos
                    side = "LONG" if szi > 0 else "SHORT"
                    pos_val = abs(szi) * entry_px
                    eff_lev = max(1.0, round(pos_val / margin_used_pos, 1)) if margin_used_pos > 0 else float(BOT_STATE["leverage"])

                    oracle_move_pct = (pnl / pos_val) if pos_val > 0 else 0.0
                    dq_live = self.memory.price_tape.get(coin)
                    if dq_live and len(dq_live) > 0 and (now - dq_live[-1][0]) < 8.0 and entry_px > 0:
                        live_mid = float(dq_live[-1][1])
                        live_move = ((live_mid - entry_px) / entry_px) if side == "LONG" else ((entry_px - live_mid) / entry_px)
                        move_pct = live_move
                        pnl = round(move_pct * pos_val, 4)
                    else:
                        move_pct = oracle_move_pct

                    eff_lev = float(BOT_STATE["leverage"])
                    roe_pct = move_pct * eff_lev * 100.0

                    coin_atr = BOT_STATE["radar"].get(coin, {}).get("atr_pct", 0.0045)
                    dyn_tp_move = max(0.0070, min(BOT_STATE["tp_move_pct"], coin_atr * 2.10))
                    dyn_sl_move = BOT_STATE["sl_move_pct"]

                    prev_peak = safe_float(BOT_STATE["peak_move_by_coin"].get(coin, 0.0), 0.0)
                    peak_move = max(prev_peak, move_pct)
                    prev_worst = safe_float(BOT_STATE["worst_move_by_coin"].get(coin, 0.0), 0.0)
                    worst_move = min(prev_worst, move_pct)
                    if peak_move > prev_peak + 0.0004 or worst_move < prev_worst - 0.0004:
                        peak_upgraded = True
                    BOT_STATE["peak_move_by_coin"][coin] = peak_move
                    BOT_STATE["worst_move_by_coin"][coin] = worst_move
                    peak_roe = peak_move * eff_lev * 100.0
                    partial_done = BOT_STATE["partial_taken_by_coin"].get(coin, False)

                    current_step = 0
                    if peak_move >= BOT_STATE["trail_step3_trigger_pct"]:
                        current_step = 4
                        dyn_stop_move = max(0.0058, peak_move - BOT_STATE["trail_step3_dist_pct"])
                        shield_tag = f"💎 DEGRAU 4 CIRÚRGICO (+{dyn_stop_move * eff_lev * 100:.1f}% ROE GARANTIDO)"
                    elif peak_move >= BOT_STATE["trail_step2_trigger_pct"]:
                        current_step = 3
                        dyn_stop_move = max(0.0044, peak_move - BOT_STATE["trail_step2_dist_pct"])
                        shield_tag = f"🔥 DEGRAU 3 APERTADO (+{dyn_stop_move * eff_lev * 100:.1f}% ROE GARANTIDO)"
                    elif peak_move >= BOT_STATE["trail_step1_trigger_pct"]:
                        current_step = 2
                        dyn_stop_move = max(BOT_STATE["breakeven_lock_pct"], peak_move - BOT_STATE["trail_step1_dist_pct"])
                        shield_tag = f"🚀 DEGRAU 2 SURFANDO (+{dyn_stop_move * eff_lev * 100:.1f}% ROE GARANTIDO)"
                    elif peak_move >= BOT_STATE["breakeven_trigger_pct"] or partial_done:
                        current_step = 1
                        dyn_stop_move = BOT_STATE["breakeven_lock_pct"]
                        shield_tag = f"🟢 DEGRAU 1 LUCRO TRAVADO (+{dyn_stop_move * eff_lev * 100:.1f}% ROE)"
                    elif peak_move >= BOT_STATE["zero_risk_trigger_pct"]:
                        current_step = 1
                        dyn_stop_move = BOT_STATE["zero_risk_lock_pct"]
                        shield_tag = f"🛡️ PROTEÇÃO ZERO-PERDA ATIVA (Stop na Entrada +{dyn_stop_move * eff_lev * 100:.1f}% ROE — Proibido dar Red!)"
                    elif peak_move >= BOT_STATE["micro_shield_trigger_pct"]:
                        current_step = 0
                        dyn_stop_move = BOT_STATE["micro_shield_lock_pct"]
                        shield_tag = f"🛡️ MICRO-ESCUDO ATIVO (Stop Cortado p/ {dyn_stop_move * eff_lev * 100:.1f}% ROE — Risco Mínimo!)"
                    elif worst_move <= BOT_STATE["recovery_drawdown_pct"]:
                        dyn_stop_move = -dyn_sl_move
                        shield_tag = f"🛟 MODO RECUPERAÇÃO 0x0 ATIVO (Sai no Preço de Entrada assim que voltar!)"
                    else:
                        dyn_stop_move = -dyn_sl_move
                        shield_tag = f"🛡️ SL TÉCNICO ({dyn_stop_move * eff_lev * 100:.1f}% ROE | Anti-Agulhada 180s Ativo)"

                    prev_notified_step = int(BOT_STATE["notified_step_by_coin"].get(coin, 0))
                    if current_step > prev_notified_step:
                        BOT_STATE["notified_step_by_coin"][coin] = current_step
                        est_fee_usd = pos_val * BOT_STATE["round_trip_fee_pct"]
                        net_pnl_now = max(0.01, pnl - est_fee_usd)
                        pnl_brl_now = net_pnl_now * USD_BRL_RATE
                        locked_roe = dyn_stop_move * eff_lev * 100.0
                        if current_step == 1:
                            step_desc = "🛡️ Risco 100% Zerado (com folga anti-violinada) — deixando subir até o alvo de +2.7% ROE+!"
                        else:
                            step_desc = f"🔥 Lucro Gordo Travado em +{locked_roe:.1f}% ROE garantido — surfando o topo!"
                        send_mobile_alert(
                            f"🚀 {coin} ({side}) SUBINDO — DEGRAU {current_step} ATIVO!",
                            f"A operação em {coin} ({side} {eff_lev:.0f}x) bateu +{roe_pct:.2f}% ROE (Líquido ~+${net_pnl_now:.2f} USDC / R$ +{pnl_brl_now:.2f} já descontando taxa)!"
                            f"{step_desc}",
                            priority="high",
                            tags="rocket,moneybag",
                        )

                    open_pos.append({
                        "coin": coin,
                        "size": szi,
                        "pos_val_usd": round(pos_val, 2),
                        "margin_used": round(margin_used_pos, 2),
                        "eff_lev": eff_lev,
                        "entry_px": entry_px,
                        "pnl": pnl,
                        "move_pct": move_pct,
                        "peak_move_pct": peak_move,
                        "worst_move_pct": worst_move,
                        "peak_roe_pct": peak_roe,
                        "tp_target_move_pct": dyn_tp_move,
                        "sl_limit_move_pct": dyn_sl_move,
                        "dynamic_stop_move_pct": dyn_stop_move,
                        "partial_done": partial_done,
                        "opened_ts": BOT_STATE["opened_ts_by_coin"].get(coin, now),
                        "shield_tag": shield_tag,
                        "roe_pct": roe_pct,
                        "side": side
                    })

            effective_margin_used = max(total_margin_used, pos_margin_sum)
            # Sistema de Fallback de Leitura de Saldo da Conta Unificada Hyperliquid (Intacto!)
            if spot_usdc > 0 and perp_equity > 0 and abs(spot_usdc - perp_equity) > 2.0:
                total_equity = max(perp_equity, spot_usdc + floating_sum)
            elif perp_equity > 0:
                total_equity = perp_equity
            else:
                total_equity = max(withdrawable, spot_usdc)

            if BOT_STATE["starting_equity_usdc"] <= 0.0 and total_equity > 0.0:
                BOT_STATE["starting_equity_usdc"] = total_equity

            BOT_STATE["perp_equity_usdc"] = round(perp_equity, 2)
            BOT_STATE["spot_equity_usdc"] = round(spot_usdc, 2)
            BOT_STATE["equity_usdc"] = round(total_equity, 2)
            BOT_STATE["equity_brl"] = round(total_equity * USD_BRL_RATE, 2)
            BOT_STATE["margin_used_usdc"] = round(effective_margin_used, 2)
            BOT_STATE["free_margin_usdc"] = round(max(0.0, total_equity - effective_margin_used), 2)
            BOT_STATE["floating_pnl_usdc"] = round(floating_sum, 2)

            calculated_notional = max(13.5, total_equity * 0.38 * BOT_STATE["leverage"])
            BOT_STATE["order_notional"] = round(calculated_notional, 2)

            state_changed = peak_upgraded
            for old_c in list(BOT_STATE["peak_move_by_coin"].keys()):
                if old_c not in active_symbols_now:
                    BOT_STATE["peak_move_by_coin"].pop(old_c, None)
                    BOT_STATE["worst_move_by_coin"].pop(old_c, None)
                    BOT_STATE["partial_taken_by_coin"].pop(old_c, None)
                    BOT_STATE["opened_ts_by_coin"].pop(old_c, None)
                    BOT_STATE["notified_step_by_coin"].pop(old_c, None)
                    state_changed = True
            if state_changed:
                self.memory.save_persisted_memory(force=True)

            BOT_STATE["open_positions"] = open_pos
            BOT_STATE["last_update"] = time.strftime("%H:%M:%S UTC", time.gmtime())
            BOT_STATE["status"] = "OPERACIONAL — SNIPER ALPHA v40 CAÇANDO 6%-15% / 85%-94% (BTC = BÚSSOLA)" if BOT_STATE["trading_enabled"] else "PAUSADO PELO OPERADOR"

            self.sync_onchain_trade_history()
            return total_equity, open_pos
        except Exception as e:
            err_str = str(e)
            if "429" in err_str:
                time.sleep(10.0)
            else:
                add_log(f"⚠️ Aviso na leitura L1: {err_str[:80]}")
            return BOT_STATE["equity_usdc"], BOT_STATE["open_positions"]

    def execute_partial_take_profit(self, pos: dict):
        coin = pos["coin"]
        if BOT_STATE["partial_taken_by_coin"].get(coin, False):
            return
        if pos.get("pos_val_usd", 0.0) < 24.0:
            BOT_STATE["partial_taken_by_coin"][coin] = True
            return

        with GATEWAY_LOCK:
            try:
                hl_c = self._hl_coin(coin)
                decimals = self.sz_decimals.get(hl_c, self.sz_decimals.get(coin, 2))
                abs_sz = abs(float(pos["size"]))
                half_sz = round(abs_sz * 0.5, decimals)
                if half_sz <= 0 or half_sz >= abs_sz:
                    BOT_STATE["partial_taken_by_coin"][coin] = True
                    return
                res = self.exchange.market_close(hl_c, sz=half_sz)
                BOT_STATE["partial_taken_by_coin"][coin] = True
                self.memory.save_persisted_memory(force=True)
                add_log(
                    f"💰 PARCIAL 50% REDUCE-ONLY em {coin} (+{pos['roe_pct']:.1f}% ROE)! "
                    f"Metade no bolso ({half_sz} {coin}) e restante protegido! ({str(res)[:70]})"
                )
                self.sync_onchain_trade_history(force=True)
                send_mobile_alert(
                    f"💰 PARCIAL 50% NO BOLSO: {coin} (+{pos['roe_pct']:.1f}% ROE)",
                    f"Metade do lote realizada com lucro (+{pos['roe_pct']:.1f}% ROE)! Restante 100% blindado no Zero-Loss (+0.96% ROE garantido) surfando o alvo!",
                    priority="high",
                    tags="money_mouth_face,chart_with_upwards_trend",
                )
            except Exception as e:
                BOT_STATE["partial_taken_by_coin"][coin] = True
                logger.warning(f"Aviso ao executar parcial em {coin}: {e}")

    def audit_and_protect_positions(self, open_positions: list):
        brain = BOT_STATE.get("market_brain", {})

        for p in open_positions:
            coin = p["coin"]
            try:
                c_5m = self.fetch_candles_cached(coin, "5m", 45, ttl_override=12.0)
                c_15m = self.fetch_candles_cached(coin, "15m", 35, ttl_override=90.0)
                c_obi = self.fetch_l2_obi_cached(coin, ttl_sec=10.0)
                c_fund = BOT_STATE["funding_by_coin"].get(coin, 0.0)
                k_info = self.memory.get_kalman_telemetry(coin)
                BOT_STATE["radar"][coin] = QuantumOracleEngine.analyze_omni_intelligence(
                    coin, c_5m, c_15m, c_obi, c_fund, k_info, brain
                )
            except Exception:
                pass

            side = p["side"]
            move = p["move_pct"]
            peak_move = p.get("peak_move_pct", move)
            worst_move = p.get("worst_move_pct", move)
            tp_target = p.get("tp_target_move_pct", BOT_STATE["tp_move_pct"])
            sl_limit = p.get("sl_limit_move_pct", BOT_STATE["sl_move_pct"])
            dyn_stop = p.get("dynamic_stop_move_pct", -sl_limit)

            now_audit = time.time()
            age_sec = now_audit - safe_float(p.get("opened_ts", now_audit), now_audit)
            radar_info = BOT_STATE["radar"].get(coin, {})
            band_pos = safe_float(radar_info.get("band_pos", 0.50), 0.50)
            rsi_now = safe_float(radar_info.get("rsi", 50.0), 50.0)
            l2_obi = safe_float(radar_info.get("l2_obi", 0.0), 0.0)
            vel_1m = safe_float(radar_info.get("vel_1m_pct", 0.0), 0.0)

            # 1) SAÍDA DE RECUPERAÇÃO 0x0 APENAS EM SUSTO REAL (<= -0.11% move após >= 180s E somente se o fluxo/15M enfraquecer!):
            # Jamais fecha cedo em respiro normal de -0.07%/-0.08% como foi na NEAR ($3.7066 -> $3.7208) e AVAX ($8.1650 -> $8.1927)!
            htf_15m_now = str(radar_info.get("htf_15m", ""))
            if age_sec >= 180.0 and worst_move <= BOT_STATE["recovery_drawdown_pct"] and move >= BOT_STATE["recovery_exit_pct"]:
                trend_still_strong = (
                    (side == "LONG" and htf_15m_now == "ALTA 15M" and (l2_obi >= 0.05 or vel_1m >= 0.003))
                    or (side == "SHORT" and htf_15m_now == "BAIXA 15M" and (l2_obi <= -0.05 or vel_1m <= -0.003))
                )
                if trend_still_strong:
                    # Reseta o susto antigo para deixar a moeda surfar até o Green cheio!
                    BOT_STATE["worst_move_by_coin"][coin] = 0.0
                else:
                    add_log(
                        f"🛟 SAÍDA DE RECUPERAÇÃO 0x0 BLINDADA em {coin} ({p['roe_pct']:+.2f}% ROE / ${p['pnl']:+.2f})! "
                        f"Operação recuperou de susto forte ({worst_move*100:.2f}%) sem força — saindo no 0x0!"
                    )
                    self.close_position(coin, is_loss=False, side_closed=side)
                    continue

            # 2) CASH-IN DIRETO NO PICO OU NA BANDA OPOSTA (>= +0.18% move quando já bateu >=75% / <=25% da banda!):
            reached_full_cashin = (move >= BOT_STATE["cash_in_band_move_pct"]) and (
                (side == "LONG" and (band_pos >= 0.60 or rsi_now >= 57.5 or vel_1m <= 0.002))
                or (side == "SHORT" and (band_pos <= 0.40 or rsi_now <= 42.5 or vel_1m >= -0.002))
            )
            reached_opposite_band_green = (move >= 0.0018) and (
                (side == "LONG" and band_pos >= 0.75 and (vel_1m <= 0.002 or l2_obi <= 0.0))
                or (side == "SHORT" and band_pos <= 0.25 and (vel_1m >= -0.002 or l2_obi >= 0.0))
            )
            if reached_full_cashin or reached_opposite_band_green:
                add_log(
                    f"💰 CASH-IN NO PICO DO CANAL em {coin} (+{p['roe_pct']:.2f}% ROE / +${p['pnl']:.2f} bruto | Banda {int(band_pos*100)}%)! "
                    f"Green cheio trancado no topo antes de devolver qualquer centavo!"
                )
                self.close_position(coin, is_loss=False, side_closed=side)
                continue

            # 3) DEFESA DE INVERSÃO REAL DO 15M (Só após 180s se o 15M virar contra):
            if age_sec >= 180.0 and move <= -0.0011:
                trend_flipped_against_long = (side == "LONG") and (
                    htf_15m_now == "BAIXA 15M" and l2_obi <= -0.10 and vel_1m <= -0.005
                )
                trend_flipped_against_short = (side == "SHORT") and (
                    htf_15m_now == "ALTA 15M" and l2_obi >= 0.10 and vel_1m >= 0.005
                )
                if trend_flipped_against_long or trend_flipped_against_short:
                    add_log(
                        f"🛡️ DEFESA IRON SHIELD 15M em {coin} ({p['roe_pct']:.2f}% ROE)! "
                        f"Tendência de 15M inverteu contra ({htf_15m_now}, Book {l2_obi:+.2f}) — abortando antes do stop cheio!"
                    )
                    self.close_position(coin, is_loss=True, side_closed=side)
                    continue

            # 3.5) TIME-STOP ANTI-ZUMBI (15 minutos / 900s — PROIBIDO FECHAR NO VERMELHO!):
            # No ETH às 14:01 UTC, o Time-Stop antigo fechou com -0.63% ROE (-$0.08), fabricando um Red desnecessário!
            # Na v46.0, o Time-Stop SÓ encerra se a operação estiver POSITIVA (move >= +0.0004, cobrindo a taxa no 0x0/Verde)!
            if age_sec >= 900.0 and (0.0004 <= move < BOT_STATE["zero_risk_trigger_pct"]):
                is_stagnant = (abs(vel_1m) <= 0.002) or (0.38 <= band_pos <= 0.62)
                if is_stagnant:
                    add_log(
                        f"⏱️ TIME-STOP ANTI-ZUMBI NO VERDE em {coin} (+{p['roe_pct']:.2f}% ROE | {int(age_sec//60)}m aberta)! "
                        f"Operação lenta encerrada no positivo sem prejuízo!"
                    )
                    self.close_position(coin, is_loss=False, side_closed=side)
                    continue

            # 4) Parcial de 50% no bolso aos +0.25% move (+2.00% ROE)
            if move >= BOT_STATE["partial_tp_trigger_pct"] and not p.get("partial_done", False):
                self.execute_partial_take_profit(p)

            # 5) Take Profit Cheio, Escada de Lucro (Degraus 0 a 4) e Stop Loss c/ Absorção de Agulhada 180s
            if move >= tp_target:
                add_log(f"🎯 TAKE PROFIT ATINGIDO em {coin} (+{p['roe_pct']:.2f}% ROE / +${p['pnl']:.2f})! Fechando a mercado...")
                self.close_position(coin, is_loss=False, side_closed=side)
            elif peak_move >= BOT_STATE["trail_step1_trigger_pct"] and move <= dyn_stop:
                add_log(
                    f"🔥 ESCADA DE LUCRO ACIONADA em {coin} (+{p['roe_pct']:.2f}% ROE | Pico foi +{p['peak_roe_pct']:.1f}% ROE)! "
                    f"Embolsando +${p['pnl']:.2f}..."
                )
                self.close_position(coin, is_loss=False, side_closed=side)
            elif peak_move >= BOT_STATE["breakeven_trigger_pct"] and move <= dyn_stop:
                add_log(
                    f"🟢 DEGRAU 1 (GREEN TRAVADO) em {coin} (+{p['roe_pct']:.2f}% ROE)! "
                    f"Operação encerrada no lucro após atingir +{p['peak_roe_pct']:.1f}% ROE..."
                )
                self.close_position(coin, is_loss=False, side_closed=side)
            elif peak_move >= BOT_STATE["zero_risk_trigger_pct"] and move <= dyn_stop:
                add_log(
                    f"🛡️ PROTEÇÃO ZERO-PERDA ACIONADA em {coin} (+{p['roe_pct']:.2f}% ROE)! "
                    f"Operação bateu +{p['peak_roe_pct']:.1f}% ROE e foi encerrada no Zero-a-Zero antes de virar Red!"
                )
                self.close_position(coin, is_loss=False, side_closed=side)
            elif peak_move >= BOT_STATE["micro_shield_trigger_pct"] and move <= dyn_stop:
                add_log(
                    f"🛡️ MICRO-ESCUDO ACIONADO em {coin} ({p['roe_pct']:.2f}% ROE | Pico foi +{p['peak_roe_pct']:.1f}% ROE)! "
                    f"Operação recuou após subir e foi encerrada com micro-stop reduzido (~-$0.04)!"
                )
                self.close_position(coin, is_loss=False, side_closed=side)
            elif move <= -sl_limit:
                # Proteção Anti-Fechamento em 14s no Spread de Abertura:
                # Nos primeiros 75 segundos, absorve o spread inicial até -0.17% para não estopar na abertura!
                htf_and_book_intact = (
                    (side == "LONG" and htf_15m_now == "ALTA 15M" and l2_obi >= 0.08)
                    or (side == "SHORT" and htf_15m_now == "BAIXA 15M" and l2_obi <= -0.08)
                )
                # Absorção Anti-Agulhada 180s v50.0: Em moedas de centavos (ex: ADA a $0.18), 4 ticks são -0.22%.
                # Se nos primeiros 180s a tendência de 15M e o Book L2 continuarem compradores/vendedores firmes (>= 0.08),
                # absorve até -0.24% sem estopar na mínima do pavio!
                if (age_sec < 75.0 and move > -0.0018) or (age_sec < 180.0 and htf_and_book_intact and move > -0.0024):
                    pass
                else:
                    add_log(
                        f"🛡️ STOP LOSS TÉCNICO em {coin} ({p['roe_pct']:.2f}% ROE)! "
                        f"Ativando Disjuntor Anti-Cascata (20m de trava em {side} + 5m de pausa geral)..."
                    )
                    self.close_position(coin, is_loss=True, side_closed=side)

    def open_sniper_order(self, coin: str, is_buy: bool, strategy_label: str = "", score: float = 90.0) -> bool:
        if coin in COMPASS_ONLY_COINS:
            return False
        now = time.time()
        if now - self.cooldowns.get(coin, 0) < 1800:
            return False
        gm_order = time.gmtime(now)
        if gm_order.tm_min >= 58 or gm_order.tm_min <= 2:
            return False
        if now < BOT_STATE.get("loss_quarantine_until", {}).get(coin, 0.0):
            return False
        if now < BOT_STATE.get("global_any_lock_until", 0.0):
            return False
        if is_buy and now < BOT_STATE.get("global_long_lock_until", 0.0):
            return False
        if (not is_buy) and now < BOT_STATE.get("global_short_lock_until", 0.0):
            return False

        new_side = "LONG" if is_buy else "SHORT"
        if len(BOT_STATE["open_positions"]) >= 1:
            return False

        with GATEWAY_LOCK:
            try:
                lev = BOT_STATE["leverage"]
                hl_coin = self._hl_coin(coin)
                if self.configured_leverage.get(coin) != lev:
                    self.exchange.update_leverage(lev, hl_coin, is_cross=True)
                    self.configured_leverage[coin] = lev

                # CONFIRMAÇÃO DUPLA L2 AO VIVO NO MILISSEGUNDO DO GATILHO (Evita preço atrasado de 4s do loop!):
                snap_now = self.info.l2_snapshot(hl_coin)
                levels_now = snap_now.get("levels", [])
                if len(levels_now) < 2 or not levels_now[0] or not levels_now[1]:
                    return False
                best_bid = float(levels_now[0][0].get("px", 0.0))
                best_ask = float(levels_now[1][0].get("px", 0.0))
                if best_bid <= 0 or best_ask <= 0:
                    return False
                mid_px = (best_bid + best_ask) * 0.5
                spread_pct = (best_ask - best_bid) / mid_px
                # Bloqueia se o spread Bid-Ask estiver largo (> 0.06%) para não já nascer negativo!
                if spread_pct > 0.0008:
                    add_log(f"🛡️ Disparo cancelado em {coin}: Spread L2 largo ({spread_pct*100:.3f}% > 0.06%)")
                    return False

                bids_15 = levels_now[0][:15]
                asks_15 = levels_now[1][:15]
                b_vol = sum(float(b.get("sz", 0.0)) * (1.5 if i < 5 else 1.0) for i, b in enumerate(bids_15))
                a_vol = sum(float(a.get("sz", 0.0)) * (1.5 if i < 5 else 1.0) for i, a in enumerate(asks_15))
                live_obi_now = ((b_vol - a_vol) / (b_vol + a_vol)) if (b_vol + a_vol) > 0 else 0.0
                req_obi_now = 0.18 if (coin in HIGH_BETA_COINS) else 0.14
                if is_buy and live_obi_now < req_obi_now:
                    add_log(f"🛡️ Disparo LONG cancelado em {coin}: Book L2 fraco/virou antes da ordem ({live_obi_now:+.2f} < +{req_obi_now:.2f})")
                    return False
                if (not is_buy) and live_obi_now > -req_obi_now:
                    add_log(f"🛡️ Disparo SHORT cancelado em {coin}: Book L2 fraco/virou antes da ordem ({live_obi_now:+.2f} > -{req_obi_now:.2f})")
                    return False

                decimals = self.sz_decimals.get(hl_coin, self.sz_decimals.get(coin, 2))
                notional = BOT_STATE["order_notional"]
                size = round(notional / mid_px, decimals)
                if size <= 0:
                    return False
                add_log(
                    f"⚡ SNIPER OMNI v43 DISPARANDO {new_side} ({lev}x) em {coin} [{strategy_label} | Book Ao Vivo {live_obi_now:+.2f} | Score {score:.1f}] | "
                    f"Qtd: {size} (~${notional}) @ ${mid_px:.4f}"
                )
                res = self.exchange.market_open(hl_coin, is_buy, size, mid_px, 0.0025)
                res_str = str(res)
                if "error" in res_str.lower() and "filled" not in res_str.lower():
                    add_log(f"⚠️ Ordem rejeitada pela L1 em {coin}: {res_str[:110]}")
                    self.cooldowns[coin] = now - 180.0
                    return False

                self.cooldowns[coin] = now
                BOT_STATE["peak_move_by_coin"][coin] = 0.0
                BOT_STATE["worst_move_by_coin"][coin] = 0.0
                BOT_STATE["partial_taken_by_coin"][coin] = False
                BOT_STATE["notified_step_by_coin"][coin] = 0
                BOT_STATE["opened_ts_by_coin"][coin] = now
                self.memory.save_persisted_memory(force=True)
                add_log(f"✅ Execução Confirmada L1 {coin}: {res_str[:100]}")

                # PILAR 5: Grava Ordem de Stop de Emergência Catastrófico Direto na Blockchain L1 (-0.28% move)
                # Caso o servidor perca conexão, a posição já tem um paraquedas nativo dentro da Hyperliquid!
                try:
                    px_digits = max(0, 6 - decimals) if mid_px < 10.0 else (2 if mid_px < 1000.0 else 1)
                    hard_sl_px = round(mid_px * (1.0 - 0.0028) if is_buy else mid_px * (1.0 + 0.0028), px_digits)
                    if hard_sl_px > 0:
                        self.exchange.order(
                            hl_coin,
                            not is_buy,
                            size,
                            hard_sl_px,
                            {"trigger": {"triggerPx": hard_sl_px, "isMarket": True, "tpsl": "sl"}},
                            reduce_only=True,
                        )
                        add_log(f"🛡️ Hard Stop On-Chain L1 gravado na Hyperliquid para {coin} @ ${hard_sl_px}")
                except Exception:
                    pass
                send_mobile_alert(
                    f"⚡ NOVA ENTRADA: {new_side} ({lev}x) em {coin}",
                    f"🎯 Estratégia: {strategy_label} (Score {score:.1f})"
                    f"💵 Preço de Entrada: ${mid_px:.4f} | Lote: ~${notional:.2f} ({size} {coin})"
                    f"💰 Banca Atual: ${BOT_STATE['equity_usdc']:.2f} USDC (R$ {BOT_STATE['equity_brl']:.2f})",
                    priority="high",
                    tags="zap,chart_with_upwards_trend",
                )
                return True
            except Exception as e:
                add_log(f"❌ Erro ao abrir ordem em {coin}: {e}")
                return False

    def close_position(self, coin: str, is_loss: bool = False, side_closed: str = ""):
        with GATEWAY_LOCK:
            try:
                pos_snap = next((p for p in BOT_STATE.get("open_positions", []) if p.get("coin") == coin), None)
                est_pnl = float(pos_snap["pnl"]) if pos_snap else 0.0
                est_roe = float(pos_snap["roe_pct"]) if pos_snap else 0.0

                hl_c = self._hl_coin(coin)
                res = None
                # PILAR 3: Se for saída no LUCRO (is_loss=False e est_pnl > 0), tenta primeiro execução Limit IOC/Topo do Livro
                # para economizar spread/taxa e capturar preço melhor, com Fallback Imediato a Mercado em 0.4s (100% garantido)!
                if not is_loss and est_pnl > 0.02 and pos_snap:
                    try:
                        snap_c = self.info.l2_snapshot(hl_c)
                        lv_c = snap_c.get("levels", [])
                        if len(lv_c) >= 2 and lv_c[0] and lv_c[1]:
                            b_bid = float(lv_c[0][0].get("px", 0.0))
                            b_ask = float(lv_c[1][0].get("px", 0.0))
                            close_is_buy = (pos_snap.get("side") == "SHORT")
                            best_px = b_bid if close_is_buy else b_ask
                            abs_sz = abs(float(pos_snap.get("size", 0.0)))
                            if best_px > 0 and abs_sz > 0:
                                lim_res = self.exchange.order(
                                    hl_c, close_is_buy, abs_sz, best_px, {"limit": {"tif": "Ioc"}}, reduce_only=True
                                )
                                if "filled" in str(lim_res).lower():
                                    res = lim_res
                                    add_log(f"💎 Saída Otimizada no Topo do Livro L2 em {coin} @ ${best_px}!")
                    except Exception:
                        pass

                # Garantia Absoluta de Fechamento (fecha qualquer saldo remanescente a mercado):
                res_mkt = self.exchange.market_close(hl_c)
                if res is None:
                    res = res_mkt

                # Remove qualquer Hard Stop On-Chain pendente da moeda encerrada:
                try:
                    open_ords = self.info.open_orders(self.account_address)
                    if isinstance(open_ords, list):
                        for o in open_ords:
                            if o.get("coin") in (coin, hl_c) and "oid" in o:
                                self.exchange.cancel(hl_c, int(o["oid"]))
                except Exception:
                    pass

                now = time.time()
                self.cooldowns[coin] = now
                # REGRA ANTI-REENTRADA NA MESMA MOEDA (Evita o que aconteceu na PEPE às 22:20 -> 22:30):
                # Toda moeda operada entra em quarentena mínima de 35m (2100s) se voltou no 0x0/Degrau 1 curto (< $0.06),
                # ou 45m (2700s) se deu Stop Loss, proibindo insistir no mesmo ativo em seguida!
                if is_loss:
                    BOT_STATE["loss_quarantine_until"][coin] = now + 2700.0
                    BOT_STATE["global_any_lock_until"] = now + 300.0
                    if side_closed == "LONG":
                        BOT_STATE["global_long_lock_until"] = now + 1200.0
                    elif side_closed == "SHORT":
                        BOT_STATE["global_short_lock_until"] = now + 1200.0
                elif est_pnl < 0.06:
                    BOT_STATE["loss_quarantine_until"][coin] = now + 2100.0
                BOT_STATE["peak_move_by_coin"].pop(coin, None)
                BOT_STATE["worst_move_by_coin"].pop(coin, None)
                BOT_STATE["partial_taken_by_coin"].pop(coin, None)
                BOT_STATE["notified_step_by_coin"].pop(coin, None)
                BOT_STATE["opened_ts_by_coin"].pop(coin, None)
                self.memory.save_persisted_memory(force=True)
                add_log(f"🔒 Posição encerrada em {coin}: {str(res)[:90]}")
                self.sync_onchain_trade_history(force=True)

                recent = BOT_STATE.get("recent_closed_trades", [])
                net_u = recent[0]["net_usdc"] if (recent and recent[0].get("coin") == coin) else round(est_pnl, 2)
                net_b = round(net_u * USD_BRL_RATE, 2)
                w_tot = BOT_STATE.get("wins_total", 0)
                l_tot = BOT_STATE.get("losses_total", 0)
                wr = BOT_STATE.get("win_rate_pct", 0.0)

                if not is_loss and net_u >= 0:
                    send_mobile_alert(
                        f"🏆 VITÓRIA GREEN EM {coin}: +${net_u:.2f} USDC (R$ +{net_b:.2f})",
                        f"✅ Lucro Líquido no Bolso: +${net_u:.2f} USDC (R$ +{net_b:.2f} | {est_roe:+.2f}% ROE)"
                        f"🏆 Placar On-Chain: {w_tot} Vitórias x {l_tot} Derrotas ({wr:.1f}%)"
                        f"💰 Banca Atual: ${BOT_STATE['equity_usdc']:.2f} USDC (R$ {BOT_STATE['equity_brl']:.2f})",
                        priority="high",
                        tags="trophy,money_with_wings",
                    )
                elif not is_loss and net_u >= -0.045:
                    send_mobile_alert(
                        f"🛡️ ZERO-A-ZERO PROTEGIDO EM {coin} (${net_u:+.2f} taxa)",
                        f"⚖️ Posição encerrada no preço de entrada em {coin} (Zero perda de gráfico, apenas ${abs(net_u):.2f} de taxa da corretora)."
                        f"🏆 Placar Mantido: {w_tot} Vitórias x {l_tot} Derrotas ({wr:.1f}%) | Banca: ${BOT_STATE['equity_usdc']:.2f} USDC",
                        priority="default",
                        tags="shield",
                    )
                else:
                    send_mobile_alert(
                        f"🛑 SAÍDA DE PROTEÇÃO (RED) EM {coin}: ${net_u:+.2f} USDC",
                        f"🛡️ Posição encerrada em {coin} ({net_u:+.2f} USDC / R$ {net_b:+.2f})."
                        f"🧊 Moeda {coin} em quarentena por 45m + Disjuntor Geral (5m pausa + 20m na direção)."
                        f"🏆 Placar: {w_tot}W x {l_tot}L ({wr:.1f}%) | Banca: ${BOT_STATE['equity_usdc']:.2f} USDC",
                        priority="high",
                        tags="shield,warning",
                    )
            except Exception as e:
                add_log(f"❌ Erro ao encerrar {coin}: {e}")


GLOBAL_GATEWAY: HyperliquidDeFiGateway | None = None


class SovereignWebServer(BaseHTTPRequestHandler):
    def do_GET(self):
        global GLOBAL_GATEWAY
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            BOT_STATE["logs"] = list(LOG_BUFFER)
            self.wfile.write(json.dumps(BOT_STATE).encode("utf-8"))
            return

        if parsed.path == "/api/action":
            qs = parse_qs(parsed.query)
            cmd = qs.get("cmd", [""])[0]
            coin = qs.get("coin", [""])[0]
            if cmd == "toggle_bot":
                BOT_STATE["trading_enabled"] = not BOT_STATE["trading_enabled"]
                add_log(f"Operador alterou status do robô para: {'ATIVO' if BOT_STATE['trading_enabled'] else 'PAUSADO'}")
            elif cmd == "test_alert":
                send_mobile_alert(
                    "🔔 TESTE DE ALERTA NO CELULAR — SNIPER v40.0",
                    f"🏆 Placar: {BOT_STATE['wins_total']} Vitórias x {BOT_STATE['losses_total']} Derrotas ({BOT_STATE['win_rate_pct']:.1f}%)\n"
                    f"💰 Banca Atual: ${BOT_STATE['equity_usdc']:.2f} USDC (R$ {BOT_STATE['equity_brl']:.2f})",
                    priority="high",
                    tags="bell,white_check_mark",
                )
                add_log("🔔 Alerta de teste enviado para o aplicativo ntfy no celular!")
            elif cmd == "reset_stats" and GLOBAL_GATEWAY is not None:
                now_ms = int(time.time() * 1000)
                BOT_STATE["stats_reset_ts_ms"] = now_ms
                BOT_STATE["reset_mode_label"] = f"ZERADO EM {time.strftime('%d/%m %H:%M UTC', time.gmtime())}"
                BOT_STATE["wins_total"] = 0
                BOT_STATE["losses_total"] = 0
                BOT_STATE["win_rate_pct"] = 0.0
                BOT_STATE["avg_win_usdc"] = 0.0
                BOT_STATE["avg_loss_usdc"] = 0.0
                BOT_STATE["realized_profit_usdc"] = 0.0
                BOT_STATE["realized_profit_brl"] = 0.0
                BOT_STATE["wins_24h"] = 0
                BOT_STATE["losses_24h"] = 0
                BOT_STATE["realized_24h_usdc"] = 0.0
                BOT_STATE["daily_progress_pct"] = 0.0
                BOT_STATE["daily_vault_active"] = False
                BOT_STATE["coin_performance_map"] = {}
                BOT_STATE["top_coins_summary"] = "Placar zerado — aguardando o 1º trade do novo ciclo!"
                BOT_STATE["recent_closed_trades"] = []
                GLOBAL_GATEWAY.memory.save_persisted_memory(force=True)
                add_log("🆕 Placar de Vitórias/Derrotas, Lucro Acumulado, Histórico e Logs ZERADOS pelo operador!")
            elif cmd == "era_v30" and GLOBAL_GATEWAY is not None:
                BOT_STATE["stats_reset_ts_ms"] = 0
                BOT_STATE["reset_mode_label"] = "ERA OMEGA v30+ (HISTÓRICO COMPLETO)"
                GLOBAL_GATEWAY.sync_onchain_trade_history(force=True)
                GLOBAL_GATEWAY.memory.save_persisted_memory(force=True)
                add_log("💎 Histórico completo restaurado pelo operador!")
            elif cmd == "clear_quarantine" and GLOBAL_GATEWAY is not None:
                BOT_STATE["loss_quarantine_until"].clear()
                BOT_STATE["global_long_lock_until"] = 0.0
                BOT_STATE["global_short_lock_until"] = 0.0
                BOT_STATE["global_any_lock_until"] = 0.0
                GLOBAL_GATEWAY.cooldowns.clear()
                GLOBAL_GATEWAY.memory.save_persisted_memory(force=True)
                add_log("🔓 Todas as quarentenas e travas pós-stop foram limpas pelo operador!")
            elif cmd == "close" and coin and GLOBAL_GATEWAY is not None:
                threading.Thread(target=GLOBAL_GATEWAY.close_position, args=(coin, False, ""), daemon=True).start()

            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        pos_rows = ""
        for p in BOT_STATE["open_positions"]:
            c_col = "#10b981" if p["pnl"] >= 0 else "#ef4444"
            pos_rows += f"""
            <tr>
                <td><b>{p['coin']}</b> <span style="color:#94a3b8;font-size:11px;">({p['eff_lev']:.0f}x)</span></td>
                <td style="color:{'#10b981' if p['side']=='LONG' else '#ef4444'};font-weight:bold;">{p['side']}</td>
                <td>{p['size']} <span style="color:#94a3b8;font-size:11px;">(${p['pos_val_usd']:.2f})</span></td>
                <td>${p['entry_px']:.4f}</td>
                <td style="color:{c_col};font-weight:bold;">
                    ${p['pnl']:+.4f} ({p['roe_pct']:+.2f}% ROE)<br>
                    <span style="font-size:11px;color:#fbbf24;">{p['shield_tag']}</span>
                </td>
                <td><a href="/api/action?cmd=close&coin={p['coin']}" style="background:#ef4444;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">Fechar L1</a></td>
            </tr>"""
        if not pos_rows:
            pos_rows = "<tr><td colspan='6' style='text-align:center;color:#94a3b8;padding:12px;'>Aguardando moeda tocar no EXTREMO REAL da banda (6%-15% p/ LONG ou 85%-94% p/ SHORT) com vela virando...</td></tr>"

        radar_rows = ""
        sorted_radar = sorted(
            BOT_STATE["radar"].items(),
            key=lambda kv: (kv[0] in COMPASS_ONLY_COINS, -safe_float(kv[1].get("score", 0.0), 0.0))
        )
        for c_sym, r in sorted_radar:
            obi_val = safe_float(r.get("l2_obi", 0.0), 0.0)
            obi_col = "#10b981" if obi_val > 0 else ("#ef4444" if obi_val < 0 else "#94a3b8")
            sig_str = str(r.get("signal", "NEUTRO"))
            sig_col = "#10b981" if "LONG" in sig_str else ("#ef4444" if "SHORT" in sig_str else ("#38bdf8" if sig_str == "BÚSSOLA" else "#94a3b8"))
            b_pct = int(safe_float(r.get("band_pos", 0.5), 0.5) * 100)
            radar_rows += f"""
            <tr>
                <td><b>{c_sym}</b></td>
                <td>${safe_float(r.get('price', 0.0)):.4f}<br><span style="font-size:10.5px;color:#64748b;">VWAP ${safe_float(r.get('vwap', 0.0)):.4f}</span></td>
                <td>RSI {safe_float(r.get('rsi', 50.0)):.1f} <b>(Banda {b_pct}%)</b><br><span style="font-size:10.5px;color:#38bdf8;">Espaço: +{safe_float(r.get('room_pct', 0.0)):.2f}% | 🧬 DNA: {safe_float(r.get('dna_rate_pct', 80.0)):.0f}%</span></td>
                <td style="color:{obi_col};font-weight:bold;">Book {obi_val:+.2f}<br><span style="font-size:10.5px;color:#94a3b8;">Vel: {safe_float(r.get('vel_1m_pct', 0.0)):+.3f}%/m</span></td>
                <td>{r.get('trend', 'NEUTRO')}<br><span style="font-size:10.5px;color:#94a3b8;">{r.get('strategy', '')}</span></td>
                <td style="color:{sig_col};font-weight:bold;">{sig_str} ({safe_float(r.get('score', 50.0)):.1f})</td>
            </tr>"""

        hist_rows = ""
        for h in BOT_STATE.get("recent_closed_trades", []):
            h_col = "#10b981" if h.get("is_win") else ("#38bdf8" if h.get("is_scratch") else "#ef4444")
            hist_rows += f"""
            <tr>
                <td>{h['time_str']}</td>
                <td><b>{h['coin']}</b></td>
                <td style="color:{h_col};font-weight:bold;">{h['result']}</td>
                <td>${h['px']:.4f}</td>
                <td style="color:{h_col};font-weight:bold;">${h['net_usdc']:+.2f} USDC (R$ {h['net_brl']:+.2f})</td>
            </tr>"""
        if not hist_rows:
            hist_rows = "<tr><td colspan='5' style='text-align:center;color:#94a3b8;padding:10px;'>Sincronizando histórico de trades da blockchain...</td></tr>"

        mb = BOT_STATE.get("market_brain", {})
        reg_col = mb.get("regime_color", "#10b981")
        realized_u = BOT_STATE["realized_profit_usdc"]
        realized_b = BOT_STATE["realized_profit_brl"]
        float_u = BOT_STATE["floating_pnl_usdc"]
        float_b = round(float_u * USD_BRL_RATE, 2)
        pnl_col = "#10b981" if realized_u >= 0 else "#ef4444"
        fl_col = "#10b981" if float_u >= 0 else "#ef4444"
        logs_txt = "\n".join(LOG_BUFFER)

        html = f"""<!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="4">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{BOT_STATE['version']}</title>
            <style>
                body {{ background:#060911; color:#f8fafc; font-family:Inter,system-ui,sans-serif; margin:0; padding:12px; }}
                .card {{ background:#0d1322; border:1px solid #1e293b; border-radius:10px; padding:12px; margin-bottom:12px; }}
                .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; margin-bottom:12px; }}
                .kpi-box {{ background:#0d1322; border:1px solid #1e293b; border-radius:10px; padding:12px; }}
                .kpi-title {{ font-size:11px; color:#94a3b8; text-transform:uppercase; margin-bottom:4px; }}
                .kpi-big {{ font-size:20px; font-weight:800; margin-bottom:4px; }}
                .kpi-sub {{ font-size:11.5px; color:#cbd5e1; }}
                table {{ width:100%; border-collapse:collapse; font-size:12px; }}
                th, td {{ padding:8px 6px; text-align:left; border-bottom:1px solid #1e293b; }}
                th {{ color:#94a3b8; font-size:11px; text-transform:uppercase; }}
                pre {{ background:#04070d; padding:10px; border-radius:8px; font-size:11px; color:#10b981; overflow-x:auto; max-height:220px; }}
            </style>
        </head>
        <body>
        <div class="card" style="border-color:#10b981;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <div>
              <h2 style="margin:0;font-size:15px;color:#10b981;">🎯 {BOT_STATE['version']}</h2>
              <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
                <a href="/api/action?cmd=reset_stats" style="background:#ef4444;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🆕 Zerar Placar &amp; Histórico (0x0)</a>
                <a href="/api/action?cmd=era_v30" style="background:#8b5cf6;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">💎 Só Era v30</a>
                <a href="/api/action?cmd=test_alert" style="background:#10b981;color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🔔 Testar Aviso</a>
                <a href="/api/action?cmd=clear_quarantine" style="background:#38bdf8;color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🔓 Limpar Quarentenas</a>
                <a href="/api/action?cmd=toggle_bot" style="background:#f59e0b;color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">{'⏸️ Pausar Novas Entradas' if BOT_STATE['trading_enabled'] else '▶️ Retomar Entradas'}</a>
              </div>
              <div style="font-size:11px;color:#94a3b8;margin-top:6px;">
                Status: <b style="color:#10b981;">{BOT_STATE['status']}</b> | Atualizado: {BOT_STATE['last_update']} | App <b>ntfy</b> no Celular: <code>{BOT_STATE['ntfy_topic']}</code>
              </div>
            </div>
          </div>
        </div>

        <div class="kpi-grid">
          <div class="kpi-box" style="border-color:#38bdf8;">
            <div class="kpi-title">💰 Quanto a Banca Está Agora</div>
            <div class="kpi-big" style="color:#38bdf8;">${BOT_STATE['equity_usdc']:.2f} USDC</div>
            <div class="kpi-sub">≈ <b>R$ {BOT_STATE['equity_brl']:.2f}</b> | Em Uso: ${BOT_STATE['margin_used_usdc']:.2f} | Livre: <b style="color:#10b981;">${BOT_STATE['free_margin_usdc']:.2f}</b></div>
          </div>

          <div class="kpi-box" style="border-color:#10b981;">
            <div class="kpi-title">🏆 Placar de Vitórias x Derrotas</div>
            <div class="kpi-big">
              <span style="color:#10b981;">{BOT_STATE['wins_total']} Vitórias</span>
              <span style="color:#64748b;font-size:15px;"> x </span>
              <span style="color:#ef4444;">{BOT_STATE['losses_total']} Derrotas</span>
            </div>
            <div class="kpi-sub">Acerto: <b style="color:#10b981;">{BOT_STATE['win_rate_pct']:.1f}%</b> | Média W: <b style="color:#10b981;">+${BOT_STATE['avg_win_usdc']:.2f}</b> vs L: <b style="color:#ef4444;">-${BOT_STATE['avg_loss_usdc']:.2f}</b></div>
          </div>

          <div class="kpi-box" style="border-color:{pnl_col};">
            <div class="kpi-title">💵 Quanto Ganhamos (Realizado + Aberto)</div>
            <div class="kpi-big" style="color:{pnl_col};">${realized_u:+.2f} USDC <span style="font-size:14px;">(R$ {realized_b:+.2f})</span></div>
            <div class="kpi-sub">Em Aberto Agora: <b style="color:{fl_col};">${float_u:+.2f} (R$ {float_b:+.2f})</b> | 24h: <b>${BOT_STATE['realized_24h_usdc']:+.2f}</b></div>
          </div>

          <div class="kpi-box" style="border-color:#8b5cf6;">
            <div class="kpi-title">🛡️ Extremo Real &amp; Greens Cheios</div>
            <div class="kpi-big" style="color:#f59e0b;">${BOT_STATE['order_notional']:.2f} <span style="font-size:13px;color:#94a3b8;">({BOT_STATE['leverage']}x)</span></div>
            <div class="kpi-sub">Trava Zero-Perda: <b>+0.13%</b> | Alvo: <b>+0.28%+</b> | Stop: <b>-0.12%</b></div>
          </div>
        </div>

        <!-- PAINEL DO CÉREBRO GLOBAL -->
        <div class="card" style="border-color:{reg_col};background:#09101f;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:6px;">
            <h3 style="margin:0;font-size:13.5px;color:{reg_col};">🌐 {mb.get('regime', 'MAPEANDO...')}</h3>
            <span style="font-size:11px;background:#1e293b;padding:4px 8px;border-radius:5px;color:#e2e8f0;">
              Regra: <b>{mb.get('allowed_direction', 'EXTREMO REAL')}</b>
            </span>
          </div>
          <div style="font-size:12px;color:#cbd5e1;">
            📊 <b>Tendência 15m Intacta ({len(GLOBAL_BASKET)} Moedas):</b> <span style="color:#10b981;font-weight:bold;">{mb.get('breadth_bull_pct', 50):.0f}% em Alta 15m</span> vs <span style="color:#ef4444;font-weight:bold;">{mb.get('breadth_bear_pct', 50):.0f}% em Baixa 15m</span>
            &nbsp;|&nbsp; ⚡ <b>BTC 3m (Bússola):</b> <b>{mb.get('btc_impulse_3m_pct', 0.0):+.2f}%</b> • <b>ETH 3m:</b> <b>{mb.get('eth_impulse_3m_pct', 0.0):+.2f}%</b><br>
            🛡️ <b>Modo Foco Único:</b> <b style="color:#38bdf8;">{mb.get('second_slot_status', 'ATIVO')}</b> &nbsp;|&nbsp; 🌐 <b>Sessão Ativa:</b> <b style="color:#10b981;">{BOT_STATE.get('active_session_mode', 'AUTOMÁTICA')}</b> &nbsp;|&nbsp; 🔒 <b>Cofre Diário:</b> <b style="color:{'#10b981' if BOT_STATE.get('daily_vault_active') else '#94a3b8'};">{'META BATIDA (SÓ SCORE >=95)' if BOT_STATE.get('daily_vault_active') else 'CAÇANDO META DO DIA'}</b>
          </div>
        </div>

        <div class="card"><h3 style="margin-top:0;font-size:13.5px;color:#38bdf8;">🎯 POSIÇÃO PERPÉTUA ATIVA (ALVO BANDA OPOSTA +2.6% ROE+ • ANTI-VIOLINADA 180s)</h3>
        <table><thead><tr><th>Ativo</th><th>Lado</th><th>Qtd (Valor)</th><th>Entrada</th><th>Lucro Aberto / ROE &amp; Escudo</th><th>Ação</th></tr></thead><tbody>{pos_rows}</tbody></table></div>

        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
            <h3 style="margin:0;font-size:13.5px;color:#10b981;">📊 HISTÓRICO DO CICLO ATUAL ({BOT_STATE.get('reset_mode_label', 'ERA OMEGA v30+')})</h3>
            <span style="font-size:11px;background:#1e293b;padding:4px 8px;border-radius:5px;color:#38bdf8;">
              🎯 <b>Meta do Ciclo (+${BOT_STATE.get('daily_goal_usdc', 1.50):.2f} USDC):</b> <b style="color:#10b981;">{BOT_STATE.get('daily_progress_pct', 0.0):.1f}% Concluída</b>
            </span>
          </div>
          <div style="background:#1e293b;border-radius:6px;height:8px;width:100%;margin-bottom:8px;overflow:hidden;">
            <div style="background:linear-gradient(90deg,#10b981,#38bdf8);height:100%;width:{BOT_STATE.get('daily_progress_pct', 0.0)}%;"></div>
          </div>
          <div style="font-size:11.5px;color:#cbd5e1;margin-bottom:10px;">
            🏅 <b>Taxa de Vitória/Derrota por Moeda neste Ciclo:</b> <span style="color:#a78bfa;font-weight:bold;">{BOT_STATE.get('top_coins_summary', '')}</span>
          </div>
          <table><thead><tr><th>Data / Hora (UTC)</th><th>Moeda</th><th>Resultado</th><th>Preço Saída</th><th>Lucro / Prejuízo Líquido</th></tr></thead><tbody>{hist_rows}</tbody></table>
        </div>

        <div class="card"><h3 style="margin-top:0;font-size:13.5px;color:#a78bfa;">📡 RADAR SNIPER ALPHA v40 (COMPRA 6%-15% BANDA • VENDA 85%-94% BANDA • BTC = BÚSSOLA)</h3>
        <table><thead><tr><th>Ativo</th><th>Preço &amp; VWAP</th><th>RSI &amp; Posição na Banda</th><th>Fluxo L2 &amp; Kalman</th><th>Tendência &amp; Filtro de Zona</th><th>Sinal &amp; Score</th></tr></thead><tbody>{radar_rows}</tbody></table></div>

        <div class="card"><h3 style="margin-top:0;font-size:13.5px;color:#94a3b8;">📜 LOGS DE EXECUÇÃO ON-CHAIN</h3><pre>{logs_txt}</pre></div>
        </body></html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        return


def autonomous_sniper_loop():
    global GLOBAL_GATEWAY
    time.sleep(2)
    memory_engine = WholeMarketMemoryEngine()
    while True:
        try:
            gw = HyperliquidDeFiGateway(memory_engine)
            GLOBAL_GATEWAY = gw

            gw.sync_global_market_tape()
            gw.refresh_funding_and_open_interest()
            gw.sync_onchain_trade_history(force=True)
            for init_coin in BOT_STATE["watchlist"]:
                try:
                    c_5m = gw.fetch_candles_cached(init_coin, "5m", 45)
                    c_15m = gw.fetch_candles_cached(init_coin, "15m", 35)
                    c_obi = gw.fetch_l2_obi_cached(init_coin)
                    c_fund = BOT_STATE["funding_by_coin"].get(init_coin, 0.0)
                    k_info = memory_engine.get_kalman_telemetry(init_coin)
                    BOT_STATE["radar"][init_coin] = QuantumOracleEngine.analyze_omni_intelligence(
                        init_coin, c_5m, c_15m, c_obi, c_fund, k_info, BOT_STATE["market_brain"]
                    )
                except Exception:
                    pass
                time.sleep(0.15)

            while True:
                now_loop = time.time()
                brain_state = gw.sync_global_market_tape()

                equity, open_positions = gw.sync_portfolio()
                gw.audit_and_protect_positions(open_positions)
                active_coins = {p["coin"] for p in open_positions}

                gw.refresh_funding_and_open_interest()

                for idx_c, coin in enumerate(BOT_STATE["watchlist"]):
                    try:
                        c_5m = gw.fetch_candles_cached(coin, "5m", 45)
                        c_15m = gw.fetch_candles_cached(coin, "15m", 35)
                        c_obi = gw.fetch_l2_obi_cached(coin)
                        c_fund = BOT_STATE["funding_by_coin"].get(coin, 0.0)
                        k_info = memory_engine.get_kalman_telemetry(coin)
                        analysis = QuantumOracleEngine.analyze_omni_intelligence(
                            coin, c_5m, c_15m, c_obi, c_fund, k_info, brain_state
                        )
                        BOT_STATE["radar"][coin] = analysis
                        # Disparo Instantâneo Zero-Delay v50.0: não espera terminar as 18 moedas (~2.7s) quando acha gatilho Sniper!
                        if (
                            BOT_STATE["trading_enabled"]
                            and equity >= 3.5
                            and len(open_positions) == 0
                            and coin not in COMPASS_ONLY_COINS
                            and analysis.get("signal") in ("SNIPER LONG", "SNIPER SHORT")
                        ):
                            can_now, _ = gw.can_open_next_position(open_positions, 1)
                            sc_now = safe_float(analysis.get("score", 0.0), 0.0)
                            vault_ok = (not BOT_STATE.get("daily_vault_active", False)) or (sc_now >= 95.0)
                            if can_now and vault_ok and sc_now >= 92.5:
                                is_b = analysis["signal"] == "SNIPER LONG"
                                if gw.open_sniper_order(coin, is_buy=is_b, strategy_label=analysis.get("strategy", "ELITE"), score=sc_now):
                                    equity, open_positions = gw.sync_portfolio()
                                    active_coins = {p["coin"] for p in open_positions}
                    except Exception as ce:
                        if "429" in str(ce):
                            time.sleep(6.0)
                        else:
                            logger.warning(f"Aviso ao analisar {coin}: {ce}")
                    time.sleep(0.15)

                    if open_positions and (idx_c + 1) % 4 == 0:
                        brain_state = gw.sync_global_market_tape()
                        equity, open_positions = gw.sync_portfolio()
                        gw.audit_and_protect_positions(open_positions)
                        active_coins = {p["coin"] for p in open_positions}

                can_enter, slot_reason = gw.can_open_next_position(open_positions, 1)

                if (
                    BOT_STATE["trading_enabled"]
                    and equity >= 3.5
                    and can_enter
                ):
                    candidates = []
                    for r_coin, r_data in BOT_STATE["radar"].items():
                        if r_coin in active_coins or r_coin in COMPASS_ONLY_COINS:
                            continue
                        if (now_loop - safe_float(r_data.get("updated_ts", 0.0), 0.0)) > 45.0:
                            continue
                        if r_data.get("signal") in ("SNIPER LONG", "SNIPER SHORT"):
                            if BOT_STATE.get("daily_vault_active", False) and safe_float(r_data.get("score", 0.0), 0.0) < 95.0:
                                continue
                            k_now = memory_engine.get_kalman_telemetry(r_coin)
                            v_now = safe_float(k_now.get("vel_1m_pct", 0.0), 0.0)
                            if r_data["signal"] == "SNIPER LONG" and v_now >= 0.002:
                                candidates.append((safe_float(r_data.get("score", 0.0), 0.0), r_coin, True, r_data))
                            elif r_data["signal"] == "SNIPER SHORT" and v_now <= -0.002:
                                candidates.append((safe_float(r_data.get("score", 0.0), 0.0), r_coin, False, r_data))

                    if candidates:
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        for best_score, best_coin, best_is_buy, best_data in candidates:
                            opened_ok = gw.open_sniper_order(
                                best_coin,
                                is_buy=best_is_buy,
                                strategy_label=best_data.get("strategy", "ELITE"),
                                score=best_score,
                            )
                            if opened_ok:
                                active_coins.add(best_coin)
                                break

                time.sleep(2.0)
        except Exception as e:
            BOT_STATE["status"] = f"RECONECTANDO: {str(e)[:45]}"
            add_log(f"⚠️ Erro no loop principal: {e}")
            time.sleep(10)


if __name__ == "__main__":
    worker = threading.Thread(target=autonomous_sniper_loop, daemon=True)
    worker.start()
    port = int(os.getenv("PORT", 8080))
    add_log(f"Painel Web HTML v40.0 Sovereign Compass & Alpha Basket ativo na porta {port}")
    server = ThreadingHTTPServer(("0.0.0.0", port), SovereignWebServer)
    server.serve_forever()
