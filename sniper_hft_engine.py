import os
import re
import sys
import time
import json
import math
import random
import sqlite3
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

# =========================================================================================
# 1. SEGURANÇA CRÍTICA (ZERO HARDCODE + FILTRO DE MASCARAMENTO HEXADECIMAL)
# =========================================================================================
HEX_SECRET_PATTERN = re.compile(r"\b(?:0x)?[a-fA-F0-9]{24,}\b")


def mask_sensitive_hex(text: Any) -> str:
    raw = str(text)

    def _repl(match: re.Match) -> str:
        token = match.group(0)
        if len(token) <= 12:
            return "***"
        return f"{token[:6]}...{token[-4:]}"

    return HEX_SECRET_PATTERN.sub(_repl, raw)


class HexMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            try:
                formatted = record.getMessage()
                record.msg = mask_sensitive_hex(formatted)
                record.args = ()
            except Exception:
                record.msg = mask_sensitive_hex(record.msg)
                record.args = ()
        else:
            record.msg = mask_sensitive_hex(record.msg)
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SniperHFTEngine")
logger.addFilter(HexMaskingFilter())
for _h in logging.getLogger().handlers:
    _h.addFilter(HexMaskingFilter())


def validate_required_credentials() -> tuple[str, str]:
    account_addr = os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", "").strip()
    agent_key = os.getenv("HYPERLIQUID_AGENT_KEY", "").strip()
    if not account_addr or not agent_key:
        raise ValueError(
            "ERRO CRÍTICO DE SEGURANÇA: As variáveis de ambiente 'HYPERLIQUID_ACCOUNT_ADDRESS' "
            "e 'HYPERLIQUID_AGENT_KEY' são obrigatórias e não possuem valores padrão hardcoded."
        )
    if not agent_key.startswith("0x"):
        agent_key = "0x" + agent_key
    return account_addr.lower(), agent_key


USD_BRL_RATE = float(os.getenv("USD_BRL_RATE", "5.38"))
def resolve_data_dir() -> str:
    env_dir = os.getenv("DATA_DIR", "").strip()
    candidates = [env_dir] if env_dir else ["/data", "./data", "/tmp/sniper_data"]
    for cand in candidates:
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            test_f = os.path.join(cand, ".write_test")
            with open(test_f, "w", encoding="utf-8") as tf:
                tf.write("ok")
            os.remove(test_f)
            return cand
        except Exception:
            continue
    return "/tmp"


DATA_DIR = resolve_data_dir()
MEMORY_FILE_PATH = os.getenv("OMNI_MEMORY_PATH", os.path.join(DATA_DIR, "omni_market_memory.json"))
QUANT_DB_PATH = os.path.join(DATA_DIR, "quant_brain.db")
LEGACY_MEMORY_FILE_PATH = "/tmp/omni_market_memory_v71.json"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "sniper_apex_hft").strip()

GATEWAY_LOCK = threading.RLock()
WS_BOOK_LOCK = threading.RLock()
LOG_BUFFER: deque = deque(maxlen=160)


def send_mobile_alert(title: str, message: str, priority: str = "high", tags: str = "chart_with_upwards_trend"):
    safe_title = mask_sensitive_hex(title)
    safe_message = mask_sensitive_hex(message)

    def _worker():
        if NTFY_TOPIC:
            try:
                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=safe_message.encode("utf-8"),
                    headers={
                        "Title": safe_title.encode("utf-8"),
                        "Priority": priority,
                        "Tags": tags,
                    },
                    timeout=4.0,
                )
            except Exception:
                pass
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                tg_text = f"*{safe_title}*\n{safe_message}"
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


# =========================================================================================
# 2. CESTA ALPHA SINCRONIZADA (19 ATIVOS: BTC = BÚSSOLA + 18 ALTCOINS COM INJ & AAVE)
# =========================================================================================
GLOBAL_BASKET = [
    "BTC", "SUI", "AVAX", "ETH", "HYPE", "NEAR", "DOGE", "AAVE", "INJ",
    "LTC", "BNB", "UNI", "XRP", "LINK", "ADA", "SOL", "TIA",
    "APT", "OP"
]
COMPASS_ONLY_COINS = {"BTC"}
HIGH_BETA_COINS = {"SOL", "TIA", "APT", "OP"}
ELITE_SQUAD_COINS = {"SUI", "AVAX", "ETH", "HYPE", "NEAR", "DOGE", "AAVE", "INJ"}

# Escala real de velocidade no filtro de Kalman (em % por minuto: 0.030 = 0.030%/m)
MIN_ENTRY_VEL_1M_PCT = 0.025
LEADER_MAX_ADVERSE_VEL_1M_PCT = 0.12
LEADER_MAX_ADVERSE_3M_PCT = 0.08


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def add_log(msg: str):
    ts = time.strftime("%H:%M:%S", time.gmtime())
    clean_msg = mask_sensitive_hex(msg)
    entry = f"[{ts} UTC] {clean_msg}"
    LOG_BUFFER.appendleft(entry)
    logger.info(clean_msg)



class QuantBrainDB:
    """
    Banco de Experiência Quantitativa em SQLite (modo WAL) + Otimizador Thompson Sampling
    (3 Braços de Saída: SCALP_RAPIDO, SWING_ATR, RUNNER_TENDENCIA) + Kelly Fracionado.
    """
    EXIT_ARMS = {
        "SCALP_RAPIDO": {"tp_move": 0.0028, "zero_risk": 0.0015, "zero_lock": 0.00110, "trail_dist": 0.0007},
        "SWING_ATR": {"tp_move": 0.0040, "zero_risk": 0.0016, "zero_lock": 0.00110, "trail_dist": 0.0009},
        "RUNNER_TENDENCIA": {"tp_move": 0.0068, "zero_risk": 0.0017, "zero_lock": 0.00115, "trail_dist": 0.0011},
    }

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.RLock()
        self._ram_experiences: list[dict[str, Any]] = []
        self._ram_bandits: dict[tuple[str, str], list[float]] = {}
        self._init_db()
        self._load_ram_cache()

    def _load_ram_cache(self):
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT coin, side, is_win, net_usdc FROM experiences ORDER BY id DESC LIMIT 120"
                    ).fetchall()
                    self._ram_experiences = [
                        {"coin": str(r[0]), "side": str(r[1]), "is_win": int(r[2]), "net_usdc": float(r[3])}
                        for r in rows
                    ]
                    b_rows = conn.execute("SELECT regime, arm, alpha, beta FROM bandit_arms").fetchall()
                    for reg, arm, a_val, b_val in b_rows:
                        self._ram_bandits[(str(reg), str(arm))] = [float(a_val), float(b_val)]
            except Exception:
                pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS experiences (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            ts REAL,
                            mode TEXT,
                            coin TEXT,
                            side TEXT,
                            regime TEXT,
                            tactic TEXT,
                            exit_arm TEXT,
                            kaufman_er REAL,
                            band_pos REAL,
                            rsi REAL,
                            l2_obi REAL,
                            shallow_obi REAL,
                            microprice_dev REAL,
                            vel_1m REAL,
                            btc_3m REAL,
                            net_usdc REAL,
                            is_win INTEGER
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS bandit_arms (
                            regime TEXT,
                            arm TEXT,
                            alpha REAL,
                            beta REAL,
                            PRIMARY KEY (regime, arm)
                        )
                        """
                    )
                    for reg in ("RANGING", "TRENDING", "BREAKOUT"):
                        for arm in self.EXIT_ARMS:
                            conn.execute(
                                "INSERT OR IGNORE INTO bandit_arms (regime, arm, alpha, beta) VALUES (?, ?, 2.0, 2.0)",
                                (reg, arm),
                            )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Aviso ao inicializar SQLite QuantBrainDB: {e}")

    def predict_win_probability(
        self,
        coin: str,
        side: str,
        wf_rate_pct: float,
        dna_rate_pct: float,
        l2_obi: float,
        shallow_obi: float,
        microprice_dev_pct: float,
    ) -> float:
        base_prob = 0.55 * (wf_rate_pct / 100.0) + 0.45 * (dna_rate_pct / 100.0)
        flow_strength = abs(l2_obi) * 0.12 + abs(shallow_obi) * 0.10 + min(0.05, abs(microprice_dev_pct) * 2.5)
        prior_prob = min(0.92, max(0.30, base_prob + flow_strength * 0.35))
        with self.lock:
            try:
                coin_rows = [
                    r for r in self._ram_experiences if r["coin"] == coin and r["side"] == side
                ][:12]
                global_rows = [
                    r for r in self._ram_experiences if r["side"] == side
                ][:25]
                alpha = prior_prob * 6.0
                beta = (1.0 - prior_prob) * 6.0
                for r in coin_rows:
                    if r["is_win"] == 1:
                        alpha += 1.25
                    else:
                        beta += 1.60
                for r in global_rows[:10]:
                    if r["is_win"] == 1:
                        alpha += 0.35
                    else:
                        beta += 0.40
                post_prob = (alpha / max(1e-6, alpha + beta)) * 100.0
                return round(float(np.clip(post_prob, 25.0, 96.0)), 1)
            except Exception:
                return round(float(np.clip(prior_prob * 100.0, 25.0, 96.0)), 1)

    def select_exit_arm(self, regime: str) -> str:
        reg = regime if regime in ("RANGING", "TRENDING", "BREAKOUT") else "RANGING"
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT arm, alpha, beta FROM bandit_arms WHERE regime = ?", (reg,)
                    ).fetchall()
                if rows:
                    best_arm = "SWING_ATR"
                    best_sample = -1.0
                    for arm, alpha, beta in rows:
                        sample = random.betavariate(max(0.5, float(alpha)), max(0.5, float(beta)))
                        if sample > best_sample:
                            best_sample = sample
                            best_arm = arm
                    return best_arm
            except Exception:
                pass
        return "RUNNER_TENDENCIA" if reg in ("TRENDING", "BREAKOUT") else "SCALP_RAPIDO"

    def record_outcome(self, exp: dict[str, Any]):
        reg = exp.get("regime", "RANGING")
        if reg not in ("RANGING", "TRENDING", "BREAKOUT"):
            reg = "RANGING"
        arm = exp.get("exit_arm", "SWING_ATR")
        if arm not in self.EXIT_ARMS:
            arm = "SWING_ATR"
        net_u = safe_float(exp.get("net_usdc", 0.0), 0.0)
        is_win = 1 if net_u >= 0 else 0
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO experiences (
                            ts, mode, coin, side, regime, tactic, exit_arm,
                            kaufman_er, band_pos, rsi, l2_obi, shallow_obi,
                            microprice_dev, vel_1m, btc_3m, net_usdc, is_win
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            time.time(),
                            exp.get("mode", "PAPER"),
                            exp.get("coin", ""),
                            exp.get("side", ""),
                            reg,
                            exp.get("tactic", ""),
                            arm,
                            safe_float(exp.get("kaufman_er", 0.0)),
                            safe_float(exp.get("band_pos", 0.5)),
                            safe_float(exp.get("rsi", 50.0)),
                            safe_float(exp.get("l2_obi", 0.0)),
                            safe_float(exp.get("shallow_obi", 0.0)),
                            safe_float(exp.get("microprice_dev", 0.0)),
                            safe_float(exp.get("vel_1m", 0.0)),
                            safe_float(exp.get("btc_3m", 0.0)),
                            net_u,
                            is_win,
                        ),
                    )
                    if is_win:
                        conn.execute(
                            "UPDATE bandit_arms SET alpha = alpha + ? WHERE regime = ? AND arm = ?",
                            (1.0 + min(1.0, net_u * 4.0), reg, arm),
                        )
                    else:
                        conn.execute(
                            "UPDATE bandit_arms SET beta = beta + 1.0 WHERE regime = ? AND arm = ?",
                            (reg, arm),
                        )
                    conn.commit()
                self._ram_experiences.insert(
                    0, {"coin": str(exp.get("coin", "")), "side": str(exp.get("side", "")), "is_win": is_win, "net_usdc": net_u}
                )
                self._ram_experiences = self._ram_experiences[:120]
            except Exception as e:
                logger.debug(f"Aviso ao gravar experiência no SQLite: {e}")

    def get_kelly_multiplier_and_count(self) -> tuple[float, int]:
        with self.lock:
            try:
                with self._connect() as conn:
                    tot_row = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
                    total_n = int(tot_row[0]) if tot_row else 0
                    rows = conn.execute(
                        "SELECT net_usdc, is_win FROM experiences ORDER BY id DESC LIMIT 30"
                    ).fetchall()
                if len(rows) < 6:
                    return 1.0, total_n
                wins = [float(r[0]) for r in rows if int(r[1]) == 1]
                losses = [abs(float(r[0])) for r in rows if int(r[1]) == 0]
                if not losses:
                    return 1.00, total_n
                if not wins:
                    return 0.75, total_n
                p = len(wins) / len(rows)
                avg_w = sum(wins) / len(wins)
                avg_l = sum(losses) / len(losses)
                b = avg_w / max(0.01, avg_l)
                kelly_f = p - ((1.0 - p) / max(0.1, b))
                # Half-Kelly limitado entre 0.70x e 1.30x
                mult = max(0.75, min(1.05, 1.0 + kelly_f * 0.35))
                return round(mult, 2), total_n
            except Exception:
                return 1.0, 0


QUANT_BRAIN = QuantBrainDB(QUANT_DB_PATH)

BOT_STATE: dict[str, Any] = {
    "version": "v82.0 — SOVEREIGN INSTITUTIONAL 5-FACTOR CONFLUENCE & ZERO-429 ENGINE (RSI <=39.5/>=60.5 • Extremo <=20%/>=80% • WS Leve Zero-429 • Ejeção 180s)",
    "status": "INICIALIZANDO MOTOR HFT WEBSOCKET v72.0...",
    "trading_enabled": True,
    "paper_mode": os.getenv("PAPER_MODE", "true").strip().lower() != "false",
    "paper_equity_usdc": 20.00,
    "paper_wins": 0,
    "paper_losses": 0,
    "paper_realized_usdc": 0.0,
    "paper_closed_trades": [],
    "paper_open_positions": [],
    "quant_db_count": 0,
    "kelly_mult": 1.0,
    "kill_switch_active": False,
    "kill_switch_reason": "",
    "current_drawdown_pct": 0.0,
    "active_exit_arm_by_coin": {},
    "account_address": mask_sensitive_hex(os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", "").strip()),
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
    "coin_ai_brain": {},
    "top_coins_summary": "Aguardando trades do novo ciclo...",
    "recent_closed_trades": [],
    # Memória Global do Mercado Todo
    "market_brain": {
        "regime": "CAÇANDO EXTREMO REAL DA BANDA (<=24% BASE | >=76% TOPO)...",
        "regime_color": "#10b981",
        "allowed_direction": "EXTREMO REAL + MICROPRICE L2 + DNA APROVADO (BTC = SÓ BÚSSOLA)",
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
        "summary": "WebSockets allMids + l2Book ativos em tempo real com Microprice e DNA Tático!"
    },
    # Parâmetros de Execução Sniper Prime Elite
    "order_notional": 15.0,
    "leverage": 8,
    "max_positions": 1,
    "round_trip_fee_pct": 0.0007,
    "micro_shield_trigger_pct": 0.0099,   # Desativado p/ não sufocar o trade em ruído de 1 vela (-0.04%)
    "micro_shield_lock_pct": -0.0004,     # -0.04% move (Aciona quarentena e disjuntor se fechar negativo)
    "zero_risk_trigger_pct": 0.0016,      # DEGRAU 1 (+0.14% move / +1.12% ROE) -> Trava 0x0 com folga anti-ruído!
    "zero_risk_lock_pct": 0.00110,        # +0.060% move (+0.48% ROE, cobre 100% da taxa no 0x0!)
    "recovery_drawdown_pct": -0.0009,     # -0.09% move (-0.72% ROE) -> Só ativa Recuperação após susto real
    "recovery_exit_pct": 0.0004,          # +0.04% move
    "cash_in_band_move_pct": 0.0028,      # +0.28% move (atualizado dinamicamente conforme sessão ativa)
    "breakeven_trigger_pct": 0.0022,      # DEGRAU 2 (+0.22% move / +1.76% ROE) -> Trava Green Positivo (+1.04% ROE)
    "breakeven_lock_pct": 0.00130,
    "trail_step1_trigger_pct": 0.0038,    # DEGRAU 3 (+0.38% move / +3.04% ROE) -> Trailing a 0.12% do pico
    "trail_step1_dist_pct": 0.0012,
    "trail_step2_trigger_pct": 0.0050,    # DEGRAU 4 (+0.50% move / +4.00% ROE) -> Trailing a 0.09% do pico
    "trail_step2_dist_pct": 0.0009,
    "trail_step3_trigger_pct": 0.0065,    # DEGRAU 5 (+0.65% move / +5.20% ROE) -> Trailing a 0.07% do pico
    "trail_step3_dist_pct": 0.0007,
    "partial_tp_trigger_pct": 0.0095,
    "tp_move_pct": 0.0085,                # +0.85% move (+6.80% ROE) -> Take Profit Direto
    "sl_move_pct": 0.0011,                # -0.11% move (-0.88% ROE) -> Stop Curto Máx -$0.10 USDC
    "hard_sl_move_pct": 0.0028,           # -0.28% move (-2.24% ROE) -> Hard Stop On-Chain L1 (Paraquedas de emergência)
    "max_entry_spread_pct": 0.0006,       # 0.06% spread máximo permitido para disparo
    "min_top3_liquidity_mult": 3.0,       # Liquidez mínima de 3x o tamanho da ordem nos 3 primeiros níveis L2
    "watchlist": list(GLOBAL_BASKET),
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
    "ws_connected": False,
    "ws_last_tick_age_sec": 0.0,
    "radar": {},
    "last_update": "N/A",
    "logs": []
}



class MsgType:
    MARKET_DATA = "MARKET_DATA"
    SIGNAL = "SIGNAL"
    KILL_SWITCH = "KILL_SWITCH"
    HEARTBEAT = "HEARTBEAT"


KILL_SWITCH_EVENT = threading.Event()


class SovereignRiskManagerShield:
    """
    Escudo Independente de Alta Prioridade (RiskManager + Kill Switch):
    Monitora continuamente a perda máxima diária/ciclo (Drawdown) a cada 0.5s em thread dedicada.
    Se o prejuízo líquido do ciclo atingir o limite de segurança (-4.5% da banca ou -$0.85 USDC),
    aciona o KILL_SWITCH imediatamente, encerra posições abertas, cancela ordens órfãs e trava novas entradas.
    """
    def __init__(self, max_dd_pct: float = 0.045, max_dd_usdc: float = 0.85):
        self.max_dd_pct = max_dd_pct
        self.max_dd_usdc = max_dd_usdc
        self.kill_triggered = False

    def start_background_guardian(self):
        threading.Thread(target=self._guardian_loop, name="RISK_MANAGER_SHIELD", daemon=True).start()

    def reset_kill_switch(self):
        self.kill_triggered = False
        KILL_SWITCH_EVENT.clear()
        BOT_STATE["kill_switch_active"] = False
        BOT_STATE["kill_switch_reason"] = ""

    def _guardian_loop(self):
        while True:
            try:
                is_paper = bool(BOT_STATE.get("paper_mode", True))
                if is_paper:
                    eq = max(10.0, safe_float(BOT_STATE.get("paper_equity_usdc", 20.0), 20.0))
                    realized = safe_float(BOT_STATE.get("paper_realized_usdc", 0.0), 0.0)
                else:
                    eq = max(10.0, safe_float(BOT_STATE.get("starting_equity_usdc", 19.42), 19.42))
                    realized = safe_float(BOT_STATE.get("realized_profit_usdc", 0.0), 0.0)

                floating = safe_float(BOT_STATE.get("floating_pnl_usdc", 0.0), 0.0)
                total_cycle_pnl = realized + floating
                dd_pct = abs(min(0.0, total_cycle_pnl)) / eq
                dd_usdc = abs(min(0.0, total_cycle_pnl))
                BOT_STATE["current_drawdown_pct"] = round(dd_pct * 100.0, 2)

                if total_cycle_pnl < 0 and (dd_pct >= self.max_dd_pct or dd_usdc >= self.max_dd_usdc):
                    if not self.kill_triggered:
                        self.kill_triggered = True
                        KILL_SWITCH_EVENT.set()
                        BOT_STATE["trading_enabled"] = False
                        BOT_STATE["kill_switch_active"] = True
                        reason = f"KILL SWITCH ATIVADO: Drawdown de -${dd_usdc:.2f} ({dd_pct*100:.2f}%) atingiu o limite diário!"
                        BOT_STATE["kill_switch_reason"] = reason
                        BOT_STATE["status"] = f"🛑 {reason}"
                        add_log(f"🛑 [RISK_MANAGER] {reason} Pausando entradas e protegendo a banca!")
                        if GLOBAL_GATEWAY is not None:
                            for op in list(BOT_STATE.get("open_positions", [])):
                                c_open = op.get("coin")
                                if c_open:
                                    GLOBAL_GATEWAY.close_position(c_open, is_loss=True, side_closed=op.get("side", ""))
                        send_mobile_alert(
                            "🛑 KILL SWITCH DE RISCO ACIONADO!",
                            f"{reason}\nO robô pausou novas entradas automaticamente para proteger sua banca.",
                            priority="high",
                            tags="rotating_light,shield",
                        )
            except Exception:
                pass
            time.sleep(0.5)


RISK_SHIELD = SovereignRiskManagerShield()

class WholeMarketMemoryEngine:
    def __init__(self):
        self.price_tape: dict[str, deque] = {c: deque(maxlen=720) for c in GLOBAL_BASKET}
        self.kalman_state: dict[str, dict[str, float]] = {}
        self.snapshots_count: int = 0
        self.last_disk_save_ts: float = 0.0
        self._load_persisted_memory()

    def _load_persisted_memory(self):
        try:
            target_path = MEMORY_FILE_PATH
            if not os.path.exists(target_path) and os.path.exists(LEGACY_MEMORY_FILE_PATH):
                target_path = LEGACY_MEMORY_FILE_PATH
            if os.path.exists(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
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
                if isinstance(data.get("coin_ai_brain"), dict):
                    BOT_STATE["coin_ai_brain"] = data["coin_ai_brain"]
                if "paper_equity_usdc" in data:
                    BOT_STATE["paper_equity_usdc"] = safe_float(data.get("paper_equity_usdc", 20.0), 20.0)
                if "paper_wins" in data:
                    BOT_STATE["paper_wins"] = int(safe_float(data.get("paper_wins", 0), 0))
                if "paper_losses" in data:
                    BOT_STATE["paper_losses"] = int(safe_float(data.get("paper_losses", 0), 0))
                if "paper_realized_usdc" in data:
                    BOT_STATE["paper_realized_usdc"] = safe_float(data.get("paper_realized_usdc", 0.0), 0.0)
                if isinstance(data.get("paper_closed_trades"), list):
                    BOT_STATE["paper_closed_trades"] = data["paper_closed_trades"][:18]
                if isinstance(data.get("paper_open_positions"), list):
                    BOT_STATE["paper_open_positions"] = data["paper_open_positions"][:1]
        except Exception as e:
            logger.warning(f"Aviso ao carregar memória persistida: {e}")

    def save_persisted_memory(self, force: bool = False):
        """
        Persistência Atômica em Disco: grava primeiro em um arquivo temporário (.tmp)
        com flush + fsync e executa os.replace() atômico para impedir corrupção de JSON.
        """
        now = time.time()
        if not force and (now - self.last_disk_save_ts) < 25.0:
            return
        self.last_disk_save_ts = now
        tmp_path = f"{MEMORY_FILE_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            parent_dir = os.path.dirname(MEMORY_FILE_PATH)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
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
                "coin_ai_brain": BOT_STATE.get("coin_ai_brain", {}),
                "paper_equity_usdc": BOT_STATE.get("paper_equity_usdc", 20.0),
                "paper_wins": BOT_STATE.get("paper_wins", 0),
                "paper_losses": BOT_STATE.get("paper_losses", 0),
                "paper_realized_usdc": BOT_STATE.get("paper_realized_usdc", 0.0),
                "paper_closed_trades": BOT_STATE.get("paper_closed_trades", []),
                "paper_open_positions": BOT_STATE.get("paper_open_positions", []),
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, MEMORY_FILE_PATH)
        except Exception as e:
            logger.debug(f"Aviso ao salvar memória atômica: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
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
            allowed_dir = "SOMENTE SHORT NO TOPO (>= 76%)"
            summary = "Compras bloqueadas temporariamente após Stop em LONG — operando apenas SHORT no topo!"
        elif short_lock_rem > 0:
            regime = f"🛡️ TRAVA ANTI-CASCATA EM SHORT ({int(short_lock_rem // 60) + 1}m RESTANTES)"
            regime_color = "#f59e0b"
            allowed_dir = "SOMENTE LONG NO FUNDO (<= 24%)"
            summary = "Vendas bloqueadas temporariamente após Stop em SHORT — operando apenas LONG no fundo!"
        else:
            regime = "🎯 SNIPER HFT v72.0: COMPRA <=24% BANDA • VENDA >=76% BANDA (WEBSOCKETS + MICROPRICE + DNA)"
            regime_color = "#10b981"
            allowed_dir = "EXTREMO REAL + VELA & VEL KALMAN + MICROPRICE L2 + DNA APROVADO"
            summary = "BTC fixado como Bússola Exclusiva — 18 Altcoins (incluindo AAVE e INJ) monitoradas via WebSocket!"

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
        dt = now - st.get("ts", now - 1.0)
        prev_x = st["x"]
        prev_v = st["v"]
        new_x = prev_x + 0.35 * (price - prev_x)
        # Calcula velocidade real de 1 minuto pela janela real do price_tape (imune à frequência de ticks do WebSocket!)
        ret_60s = self.get_return_pct(coin, 60.0)
        ret_20s = self.get_return_pct(coin, 20.0)
        true_vel_per_min = float(np.clip(0.65 * ret_60s + 0.35 * (ret_20s * 1.5), -0.85, 0.85))
        alpha_v = 0.30 if dt >= 0.8 else 0.12
        new_v = prev_v + alpha_v * (true_vel_per_min - prev_v)
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
        is_weekend = gm.tm_wday in (5, 6)
        hour_utc = gm.tm_hour
        if is_weekend:
            return {
                "is_weekend": True,
                "min_bb_width": 0.0042,
                "cash_in_move": 0.0028,
                "partial_tp_move": 0.0095,
                "label": "🌴 MODO FIM DE SEMANA PAYOFF 2:1 (Banda >=0.42% • Alvo +2.24% ROE+ vs Soft SL -0.96% ROE)",
            }
        elif 7 <= hour_utc <= 21:
            return {
                "is_weekend": False,
                "min_bb_width": 0.0045,
                "cash_in_move": 0.0030,
                "partial_tp_move": 0.0095,
                "label": "🏛️ SESSÃO LONDRES/NY PAYOFF 2:1 (Banda >=0.45% • Alvo +2.40% ROE+ vs Soft SL -0.96% ROE)",
            }
        else:
            return {
                "is_weekend": False,
                "min_bb_width": 0.0042,
                "cash_in_move": 0.0028,
                "partial_tp_move": 0.0095,
                "label": "🌙 SESSÃO ASIÁTICA PAYOFF 2:1 (Banda >=0.42% • Alvo +2.24% ROE+ vs Soft SL -0.96% ROE)",
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
    def compute_kaufman_er(closes: np.ndarray, period: int = 12) -> float:
        if len(closes) < period + 1:
            return 0.35
        net_change = abs(float(closes[-1] - closes[-1 - period]))
        sum_changes = float(np.sum(np.abs(np.diff(closes[-1 - period:]))))
        if sum_changes <= 1e-12:
            return 0.0
        return float(np.clip(net_change / sum_changes, 0.0, 1.0))

    @staticmethod
    def estimate_coin_tick_pct(price: float) -> float:
        if price <= 0:
            return 0.0005
        if price < 0.10:
            eff_tick = 0.00005
        elif price < 1.0:
            eff_tick = 0.0001
        elif price < 10.0:
            eff_tick = 0.001
        elif price < 100.0:
            eff_tick = 0.01
        elif price < 1000.0:
            eff_tick = 0.1
        else:
            eff_tick = 0.5
        return max(0.0001, min(0.0020, eff_tick / price))

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
    def compute_walk_forward_validation(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        opens: np.ndarray,
        is_bull_htf: bool,
    ) -> tuple[float, int, bool]:
        """
        VALIDADOR WALK-FORWARD DIRECCIONAL (<0.2ms, Zero Lag):
        Simula nas últimas 45 velas de 5m a estratégia exata na direção do 15M (Compra no fundo <=26% se ALTA 15M,
        Venda no topo >=74% se BAIXA 15M) exigindo que o ganho supere o stop + taxas reais.
        """
        n = len(closes)
        if n < 26:
            return (78.0, 0, True)
        wins = 0
        losses = 0
        for i in range(20, n - 4):
            win_slice = closes[i - 19 : i + 1]
            sma_i = float(np.mean(win_slice))
            std_i = float(np.std(win_slice)) + 1e-9
            l_bb_i = sma_i - 2.0 * std_i
            u_bb_i = sma_i + 2.0 * std_i
            bw_i = max(u_bb_i - l_bb_i, float(closes[i]) * 0.002)
            ep = max(1e-9, float(closes[i]))
            low_pos = (float(lows[i]) - l_bb_i) / bw_i
            high_pos = (float(highs[i]) - l_bb_i) / bw_i
            fut_high = float(np.max(highs[i + 1 : i + 5]))
            fut_low = float(np.min(lows[i + 1 : i + 5]))

            if is_bull_htf:
                if low_pos <= 0.26 and float(closes[i]) > float(opens[i]):
                    gain = (fut_high - ep) / ep
                    dd = (ep - fut_low) / ep
                    if gain >= 0.0018 and dd < 0.0016:
                        wins += 1
                    elif dd >= 0.0018 and gain < 0.0012:
                        losses += 1
            else:
                if high_pos >= 0.74 and float(closes[i]) < float(opens[i]):
                    gain = (ep - fut_low) / ep
                    dd = (fut_high - ep) / ep
                    if gain >= 0.0018 and dd < 0.0016:
                        wins += 1
                    elif dd >= 0.0018 and gain < 0.0012:
                        losses += 1
        tot = wins + losses
        if tot == 0:
            return (76.0, 0, True)
        rate = round((wins / tot) * 100.0, 0)
        approved = (rate >= 60.0) and not (losses >= 2 and wins == 0)
        return (rate, tot, approved)

    @staticmethod
    def compute_tactical_dna(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> tuple[float, int, bool]:
        """
        SIMULADOR DE DNA TÁTICO CALIBRADO A FAVOR DA TENDÊNCIA (Últimas 45 velas de 5m):
        Testa os toques na banda a favor da tendência local e reprova a moeda se o padrão
        de reversão recente falhar (< 60% de acerto ou >= 3 falhas sem vitória).
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

            if low_pos <= 0.22 and trend_up_local and float(closes[i]) > float(lows[i]):
                bounce_up = (fut_high - ep) / ep
                drop_more = (ep - fut_low) / ep
                if bounce_up >= 0.0013 or fut_high >= (l_bb_i + 0.45 * bw_i):
                    dna_wins += 1
                elif drop_more >= 0.0024 and bounce_up < 0.0009:
                    dna_losses += 1
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
        approved = (rate >= 60.0) and not (dna_losses >= 3 and dna_wins == 0)
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
        l2_metrics: dict[str, float],
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
                "shallow_obi": 0.0,
                "microprice": 0.0,
                "microprice_dev_pct": 0.0,
                "spread_pct": 0.0,
                "vol_z": 0.0,
                "vel_1m_pct": 0.0,
                "atr_pct": 0.0045,
                "room_pct": 0.75,
                "dna_rate_pct": 85.0,
                "dna_approved": True,
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
        kaufman_er = cls.compute_kaufman_er(closes, 12)
        coin_tick_pct = cls.estimate_coin_tick_pct(price)
        vwap, vol_z = cls.compute_vwap_and_vol_zscore(highs, lows, closes, volumes)
        dna_rate_pct, _, dna_approved = cls.compute_tactical_dna(closes, highs, lows)

        htf_bull = True
        htf_bear = False
        if candles_15m and len(candles_15m) >= 10:
            c15 = np.array([float(c["c"]) for c in candles_15m], dtype=float)
            if live_tick_px > 0:
                c15[-1] = live_tick_px
            o15_now = float(candles_15m[-1].get("o", c15[-1]))
            e9_15 = cls.compute_ema(c15, 9)
            e21_15 = cls.compute_ema(c15, 21)
            if price < e21_15 * 0.9985 and price < o15_now:
                htf_bull = False
            elif price > e21_15 * 1.0015 and price > o15_now:
                htf_bull = True
            else:
                htf_bull = bool(e9_15 >= e21_15)
            htf_bear = not htf_bull
        htf_15m_state = "ALTA 15M" if htf_bull else "BAIXA 15M"

        sma20 = float(np.mean(closes[-20:]))
        std20 = float(np.std(closes[-20:])) + 1e-9
        lower_bb = sma20 - (2.0 * std20)
        upper_bb = sma20 + (2.0 * std20)
        bb_width = max(upper_bb - lower_bb, price * 0.002)
        bb_width_pct = (upper_bb - lower_bb) / max(1e-9, price)
        band_pos = float(np.clip((price - lower_bb) / bb_width, 0.0, 1.0))

        c_range = max(1e-9, float(highs[-1] - lows[-1]))
        eff_c_range = max(c_range, price * 0.0012)
        lower_wick_ratio = (min(float(opens[-1]), price) - float(lows[-1])) / eff_c_range
        upper_wick_ratio = (float(highs[-1]) - max(float(opens[-1]), price)) / eff_c_range
        rebound_from_low_pct = (price - float(lows[-1])) / max(1e-9, price)
        pullback_from_high_pct = (float(highs[-1]) - price) / max(1e-9, price)

        is_bull_5m = ema9_5m >= ema21_5m
        vel_1m = safe_float(kalman_info.get("vel_1m_pct", 0.0), 0.0)
        ret_3m = safe_float(kalman_info.get("ret_3m_pct", 0.0), 0.0)

        l2_obi = safe_float(l2_metrics.get("l2_obi", 0.0), 0.0)
        shallow_obi = safe_float(l2_metrics.get("shallow_obi", 0.0), 0.0)
        microprice = safe_float(l2_metrics.get("microprice", price), price)
        microprice_dev_pct = safe_float(l2_metrics.get("microprice_dev_pct", 0.0), 0.0)
        spread_pct = safe_float(l2_metrics.get("spread_pct", 0.0), 0.0)

        is_compass_only = coin in COMPASS_ONLY_COINS
        quarantine_rem = BOT_STATE.get("loss_quarantine_until", {}).get(coin, 0.0) - now
        in_quarantine = quarantine_rem > 0
        long_locked_global = now < BOT_STATE.get("global_long_lock_until", 0.0) or now < BOT_STATE.get("global_any_lock_until", 0.0)
        short_locked_global = now < BOT_STATE.get("global_short_lock_until", 0.0) or now < BOT_STATE.get("global_any_lock_until", 0.0)

        trend_label = f"{'🟢 ALTA 5M' if is_bull_5m else '🔴 BAIXA 5M'} ({htf_15m_state})"
        macd_rising = curr_mh >= prev_mh
        macd_falling = curr_mh <= prev_mh

        session_cfg = cls.get_session_and_regime(now)
        BOT_STATE["active_session_mode"] = session_cfg["label"]
        BOT_STATE["cash_in_band_move_pct"] = session_cfg["cash_in_move"]
        BOT_STATE["partial_tp_trigger_pct"] = session_cfg["partial_tp_move"]
        min_bb_allowed = 0.0035

        perf_map = BOT_STATE.get("coin_performance_map", {})
        c_perf = perf_map.get(coin, {"w": 0, "l": 0, "net": 0.0})
        c_wins = int(c_perf.get("w", 0))
        c_losses = int(c_perf.get("l", 0))
        auto_banned_by_ai = c_losses >= 2

        is_high_beta = coin in HIGH_BETA_COINS
        room_to_upper_pct = max(0.0, (upper_bb - price) / max(1e-9, price))
        room_to_lower_pct = max(0.0, (price - lower_bb) / max(1e-9, price))
        has_safe_band_width = bb_width_pct >= min_bb_allowed
        band_too_narrow = bb_width_pct < min_bb_allowed

        body_pct = abs(price - float(opens[-1])) / max(1e-9, price)
        recent_low_2 = min(float(lows[-1]), float(lows[-2]))
        recent_high_2 = max(float(highs[-1]), float(highs[-2]))
        low_band_pos = float(np.clip((recent_low_2 - lower_bb) / bb_width, 0.0, 1.0))
        high_band_pos = float(np.clip((recent_high_2 - lower_bb) / bb_width, 0.0, 1.0))

        min_obi_req = 0.15 if is_high_beta else 0.12
        btc_radar_now = BOT_STATE.get("radar", {}).get("BTC", {})
        eth_radar_now = BOT_STATE.get("radar", {}).get("ETH", {})
        btc_vel_live = safe_float(btc_radar_now.get("vel_1m_pct", 0.0), 0.0)
        eth_vel_live = safe_float(eth_radar_now.get("vel_1m_pct", 0.0), 0.0)
        btc_3m_live = safe_float(market_brain.get("btc_impulse_3m_pct", 0.0), 0.0)
        eth_3m_live = safe_float(market_brain.get("eth_impulse_3m_pct", 0.0), 0.0)

        # Validação Walk-Forward Direcional + Auto-Aprendizagem Bayesiana no SQLite:
        wf_rate_pct, wf_touches, wf_approved = cls.compute_walk_forward_validation(
            closes, highs, lows, opens, is_bull_htf=htf_bull
        )
        dna_rate_pct = round(0.55 * wf_rate_pct + 0.45 * dna_rate_pct, 0)
        dna_approved = bool(dna_approved and wf_approved)
        target_side = "LONG" if htf_bull else "SHORT"
        win_prob_pct = QUANT_BRAIN.predict_win_probability(
            coin=coin,
            side=target_side,
            wf_rate_pct=wf_rate_pct,
            dna_rate_pct=dna_rate_pct,
            l2_obi=l2_obi,
            shallow_obi=shallow_obi,
            microprice_dev_pct=microprice_dev_pct,
        )
        ai_prob_approved = win_prob_pct >= 62.0

        # Classificador Autônomo de Regime (CHAOTIC / TRENDING / RANGING)
        is_chaotic_regime = (spread_pct > 0.0006) or (abs(vel_1m) > 0.65) or (atr_pct > 0.018)
        is_trending_regime = (not is_chaotic_regime) and (kaufman_er >= 0.30)
        regime_label = "CHAOTIC" if is_chaotic_regime else ("TRENDING" if is_trending_regime else "RANGING")

        # Escudo Rígido BTC/ETH: para vender SHORT, BTC e ETH NÃO podem estar subindo forte (> +0.06% em 3m);
        # para comprar LONG, BTC e ETH NÃO podem estar caindo forte (< -0.06% em 3m)!
        breadth_bull_now = safe_float(market_brain.get("breadth_bull_pct", 50.0), 50.0)
        breadth_bear_now = safe_float(market_brain.get("breadth_bear_pct", 50.0), 50.0)
        btc_htf_now = str(btc_radar_now.get("htf_15m", "NEUTRO"))
        min_obi_req = 0.22 if is_high_beta else 0.18

        # Alinhamento Macro Institucional v82.0:
        # Proíbe LONG se BTC/ETH 3m estiverem negativos (< 0.0%) ou se a maré de baixa for >= 50% ou BTC em BAIXA 15M!
        # Proíbe SHORT se BTC/ETH 3m estiverem positivos (> 0.0%) ou se a maré de alta for >= 50% ou BTC em ALTA 15M!
        leaders_not_dumping = (
            (btc_vel_live >= 0.0)
            and (eth_vel_live >= -0.02)
            and (btc_3m_live >= 0.0)
            and (eth_3m_live >= -0.01)
            and (breadth_bear_now < 50.0)
            and (btc_htf_now != "BAIXA 15M")
        )
        leaders_not_pumping = (
            (btc_vel_live <= 0.0)
            and (eth_vel_live <= 0.02)
            and (btc_3m_live <= 0.0)
            and (eth_3m_live <= 0.01)
            and (breadth_bull_now < 50.0)
            and (btc_htf_now != "ALTA 15M")
        )

        # Vela de Rejeição Institucional: exige corpo + pavio real (>=26%) ou repique >=0.09% da mínima/máxima + RSI virando!
        candle_turning_up = (
            (price > float(opens[-1]))
            and (lower_wick_ratio >= 0.26 or body_pct >= 0.0007)
            and (rebound_from_low_pct >= 0.0009)
            and (rsi > prev_rsi + 0.3)
            and (vel_1m >= 0.025)
            and leaders_not_dumping
        )

        candle_turning_down = (
            (price < float(opens[-1]))
            and (upper_wick_ratio >= 0.26 or body_pct >= 0.0007)
            and (pullback_from_high_pct >= 0.0009)
            and (rsi < prev_rsi - 0.3)
            and (vel_1m <= -0.025)
            and leaders_not_pumping
        )

        btc_imp_3m = safe_float(market_brain.get("btc_impulse_3m_pct", 0.0), 0.0)

        # ZONAS DE EXTREMO REAL v82.0 (Elimina compras em Banda 25%-27% c/ RSI 45.7 como AVAX/APT e vendas c/ RSI 54.7 como SUI!):
        # LONG exige Banda <= 20% (<= 16% High-Beta) E RSI <= 39.5 (sobrevenda genuína!)
        # SHORT exige Banda >= 80% (>= 84% High-Beta) E RSI >= 60.5 (sobrecompra genuína!)
        max_long_band = 0.16 if is_high_beta else 0.20
        min_short_band = 0.84 if is_high_beta else 0.80

        in_safe_long_zone = (
            (0.05 <= band_pos <= max_long_band)
            or (low_band_pos <= 0.12 and 0.05 <= band_pos <= (max_long_band + 0.02))
        ) and (room_to_upper_pct >= 0.0042)

        in_safe_short_zone = (
            (min_short_band <= band_pos <= 0.95)
            or (high_band_pos >= 0.88 and (min_short_band - 0.02) <= band_pos <= 0.95)
        ) and (room_to_lower_pct >= 0.0042)

        outside_band_bottom = band_pos < 0.05
        outside_band_top = band_pos > 0.95

        # Confirmação tripla de livro forte: OBI >= 0.18 + Shallow OBI Top-3 >= 0.12 + Microprice >= 0.008%
        long_book_confirmed = (l2_obi >= min_obi_req) and (shallow_obi >= 0.12) and (microprice_dev_pct >= 0.008)
        short_book_confirmed = (l2_obi <= -min_obi_req) and (shallow_obi <= -0.12) and (microprice_dev_pct <= -0.008)

        long_base_pullback = (
            not is_compass_only
            and not is_chaotic_regime
            and not auto_banned_by_ai
            and not in_quarantine
            and not long_locked_global
            and dna_approved
            and ai_prob_approved
            and htf_bull
            and has_safe_band_width
            and in_safe_long_zone
            and (20.0 <= rsi <= 39.5)
            and candle_turning_up
            and (macd_rising or lower_wick_ratio >= 0.28)
            and long_book_confirmed
        )
        long_extreme_spring = (
            not is_compass_only
            and not is_chaotic_regime
            and not auto_banned_by_ai
            and not in_quarantine
            and not long_locked_global
            and dna_approved
            and ai_prob_approved
            and htf_bull
            and has_safe_band_width
            and (0.05 <= band_pos <= 0.14)
            and (rsi <= 37.5)
            and candle_turning_up
            and long_book_confirmed
            and l2_obi >= max(0.22, min_obi_req)
        )

        short_top_rally = (
            not is_compass_only
            and not is_chaotic_regime
            and not auto_banned_by_ai
            and not in_quarantine
            and not short_locked_global
            and dna_approved
            and ai_prob_approved
            and htf_bear
            and has_safe_band_width
            and in_safe_short_zone
            and (60.5 <= rsi <= 80.0)
            and candle_turning_down
            and (macd_falling or upper_wick_ratio >= 0.28)
            and short_book_confirmed
        )
        short_extreme_upthrust = (
            not is_compass_only
            and not is_chaotic_regime
            and not auto_banned_by_ai
            and not in_quarantine
            and not short_locked_global
            and dna_approved
            and ai_prob_approved
            and htf_bear
            and has_safe_band_width
            and (0.86 <= band_pos <= 0.95)
            and (rsi >= 62.5)
            and candle_turning_down
            and short_book_confirmed
            and l2_obi <= -max(0.22, min_obi_req)
        )

        is_elite_squad = coin in ELITE_SQUAD_COINS
        dna_bonus = 1.5 if dna_rate_pct >= 75.0 else 0.0
        elite_bonus = 1.5 if is_elite_squad else 0.0

        target_side = "LONG" if htf_bull else "SHORT"
        if htf_bull:
            dist_to_zone_pct = max(0.0, (band_pos - max_long_band) * 100.0) if band_pos > max_long_band else 0.0
            book_ok = long_book_confirmed
            zone_ok = in_safe_long_zone
            candle_ok = candle_turning_up
            htf_ok = True
        else:
            dist_to_zone_pct = max(0.0, (min_short_band - band_pos) * 100.0) if band_pos < min_short_band else 0.0
            book_ok = short_book_confirmed
            zone_ok = in_safe_short_zone
            candle_ok = candle_turning_down
            htf_ok = True

        stage_tier = "WAIT"

        if is_compass_only:
            signal = "BÚSSOLA"
            stage_tier = "COMPASS"
            strategy_name = f"🧭 BÚSSOLA DO MERCADO (BTC 3m: {btc_imp_3m:+.2f}% — SOMENTE LEITURA)"
            score = 35.0
        elif long_extreme_spring:
            signal = "SNIPER LONG"
            stage_tier = "TRIGGER"
            strategy_name = f"💎 FUNDO FORTRESS ({int(band_pos*100)}% | RSI {rsi:.1f} | MicroPx {microprice_dev_pct:+.3f}%) + ALTA 15M"
            score = 95.0 + min(4.0, l2_obi * 10.0) + dna_bonus
        elif long_base_pullback:
            signal = "SNIPER LONG"
            stage_tier = "TRIGGER"
            strategy_name = f"🟢 COMPRA PULLBACK 15M (Banda {int(band_pos*100)}% | RSI {rsi:.1f} | MicroPx {microprice_dev_pct:+.3f}%)"
            score = 92.8 + min(5.0, l2_obi * 9.0) + dna_bonus
        elif short_extreme_upthrust:
            signal = "SNIPER SHORT"
            stage_tier = "TRIGGER"
            strategy_name = f"💎 TOPO FORTRESS ({int(band_pos*100)}% | RSI {rsi:.1f} | MicroPx {microprice_dev_pct:+.3f}%) + BAIXA 15M"
            score = 95.0 + min(4.0, -l2_obi * 10.0) + dna_bonus
        elif short_top_rally:
            signal = "SNIPER SHORT"
            stage_tier = "TRIGGER"
            strategy_name = f"🔴 VENDA REPIQUE 15M (Banda {int(band_pos*100)}% | RSI {rsi:.1f} | MicroPx {microprice_dev_pct:+.3f}%)"
            score = 92.8 + min(5.0, -l2_obi * 9.0) + dna_bonus
        else:
            if auto_banned_by_ai:
                signal = "BLOQUEADO"
                stage_tier = "BLOCKED"
                strategy_name = f"🧠 AUTO-APRENDIZADO: PAUSADA APÓS 2 DERROTAS NO CICLO ({c_wins}W/{c_losses}L)"
                score = 38.0
            elif not dna_approved:
                signal = "DNA REPROVADO"
                stage_tier = "BLOCKED"
                strategy_name = f"🧬 DNA TÁTICO REPROVADO ({dna_rate_pct:.0f}% < 60%) — Sem padrão limpo de reversão recente"
                score = 40.0
            elif in_quarantine:
                signal = "QUARENTENA"
                stage_tier = "BLOCKED"
                strategy_name = f"🧊 QUARENTENA PÓS-TRADE ({int(quarantine_rem // 60) + 1}m)"
                score = 42.0
            elif band_too_narrow:
                signal = "CANAL CURTO"
                stage_tier = "BLOCKED"
                strategy_name = f"⏳ CANAL MUITO CURTO ({bb_width_pct*100:.2f}% < 0.35%) — AGUARDANDO EXPANSÃO"
                score = 49.0
            elif htf_bull and in_safe_long_zone:
                signal = "🔥 PRÉ-LONG"
                stage_tier = "PRE_TRIGGER"
                missing_parts = []
                if not long_book_confirmed:
                    missing_parts.append(f"Book {l2_obi:+.2f}/Top3 {shallow_obi:+.2f}/MicroPx {microprice_dev_pct:+.3f}%")
                if price <= float(opens[-1]) or rsi <= prev_rsi:
                    missing_parts.append("Vela 5M virar verde c/ RSI subindo")
                if is_chaotic_regime:
                    missing_parts.append("Regime CHAOTIC (Modo Escudo ativo)")
                elif not leaders_not_dumping:
                    missing_parts.append(f"BTC/ETH 3m estabilizar ({btc_3m_live:+.2f}% / {eth_3m_live:+.2f}%)")
                elif vel_1m < MIN_ENTRY_VEL_1M_PCT:
                    missing_parts.append(f"Vel {vel_1m:+.3f}%/m >= +{MIN_ENTRY_VEL_1M_PCT:.3f}%/m")
                if rsi > 39.5:
                    missing_parts.append(f"RSI {rsi:.1f} <= 39.5")
                miss_txt = " + ".join(missing_parts) if missing_parts else "Confirmação no Livro L2"
                strategy_name = f"🔥 NA ZONA DE COMPRA 15M (Banda {int(band_pos*100)}%) — FALTA SÓ: {miss_txt}!"
                score = 84.0 + max(0.0, (max_long_band - band_pos) * 22.0) + (3.5 if book_ok else 0.0) + (2.5 if candle_turning_up else 0.0) + elite_bonus
            elif htf_bear and in_safe_short_zone:
                signal = "🔥 PRÉ-SHORT"
                stage_tier = "PRE_TRIGGER"
                missing_parts = []
                if not short_book_confirmed:
                    missing_parts.append(f"Book {l2_obi:+.2f}/Top3 {shallow_obi:+.2f}/MicroPx {microprice_dev_pct:+.3f}%")
                if price >= float(opens[-1]) or rsi >= prev_rsi:
                    missing_parts.append("Vela 5M virar vermelha c/ RSI caindo")
                if is_chaotic_regime:
                    missing_parts.append("Regime CHAOTIC (Modo Escudo ativo)")
                elif not leaders_not_pumping:
                    missing_parts.append(f"BTC/ETH 3m estabilizar ({btc_3m_live:+.2f}% / {eth_3m_live:+.2f}%)")
                elif vel_1m > -MIN_ENTRY_VEL_1M_PCT:
                    missing_parts.append(f"Vel {vel_1m:+.3f}%/m <= -{MIN_ENTRY_VEL_1M_PCT:.3f}%/m")
                if rsi < 60.5:
                    missing_parts.append(f"RSI {rsi:.1f} >= 60.5")
                miss_txt = " + ".join(missing_parts) if missing_parts else "Confirmação no Livro L2"
                strategy_name = f"🔥 NA ZONA DE VENDA 15M (Banda {int(band_pos*100)}%) — FALTA SÓ: {miss_txt}!"
                score = 84.0 + max(0.0, (band_pos - min_short_band) * 22.0) + (3.5 if book_ok else 0.0) + (2.5 if candle_turning_down else 0.0) + elite_bonus
            elif htf_bull and outside_band_bottom:
                signal = "🔥 PRÉ-LONG"
                stage_tier = "PRE_TRIGGER"
                strategy_name = f"🔥 EXTREMO FUNDO (Banda {int(band_pos*100)}% | RSI {rsi:.1f}) — Aguardando voltar >= 5%!"
                score = round(84.5 + (2.0 if book_ok else 0.0), 1)
            elif htf_bear and outside_band_top:
                signal = "🔥 PRÉ-SHORT"
                stage_tier = "PRE_TRIGGER"
                strategy_name = f"🔥 EXTREMO TOPO (Banda {int(band_pos*100)}% | RSI {rsi:.1f}) — Aguardando voltar <= 95%!"
                score = round(84.5 + (2.0 if book_ok else 0.0), 1)
            elif htf_bull and band_pos <= 0.60:
                signal = "🎯 NA MIRA LONG"
                stage_tier = "APPROACHING"
                gap_pct = max(1, int(round((band_pos - max_long_band) * 100)))
                strategy_name = f"🎯 APROXIMANDO DE COMPRA (Banda {int(band_pos*100)}%) — Faltam {gap_pct}% p/ Zona <= {int(max_long_band*100)}%"
                score = round(78.5 - (dist_to_zone_pct * 0.55) + (1.5 if book_ok else 0.0), 1)
            elif htf_bear and band_pos >= 0.40:
                signal = "🎯 NA MIRA SHORT"
                stage_tier = "APPROACHING"
                gap_pct = max(1, int(round((min_short_band - band_pos) * 100)))
                strategy_name = f"🎯 SUBINDO P/ VENDA SHORT (Banda {int(band_pos*100)}%) — Faltam {gap_pct}% p/ Zona >= {int(min_short_band*100)}%"
                score = round(78.5 - (dist_to_zone_pct * 0.55) + (1.5 if book_ok else 0.0), 1)
            elif htf_bull:
                signal = "⏳ AGUARDANDO"
                stage_tier = "WAIT"
                gap_pct = max(1, int(round((band_pos - max_long_band) * 100)))
                strategy_name = f"⏳ EM ALTA 15M (Banda {int(band_pos*100)}%) — Aguardando recuo de {gap_pct}% p/ Zona <= {int(max_long_band*100)}%"
                score = round(max(52.0, 66.0 - (dist_to_zone_pct * 0.18)), 1)
            else:
                signal = "⏳ AGUARDANDO"
                stage_tier = "WAIT"
                gap_pct = max(1, int(round((min_short_band - band_pos) * 100)))
                strategy_name = f"⏳ EM BAIXA 15M (Banda {int(band_pos*100)}%) — Aguardando subir +{gap_pct}% p/ Zona >= {int(min_short_band*100)}%"
                score = round(max(52.0, 66.0 - (dist_to_zone_pct * 0.18)), 1)

        active_room = room_to_upper_pct if target_side == "LONG" else room_to_lower_pct
        final_score = round(min(99.0, max(35.0, score)), 1)

        return {
            "price": price,
            "vwap": round(vwap, 4),
            "rsi": round(rsi, 1),
            "band_pos": round(band_pos, 2),
            "ema_fast": ema9_5m,
            "ema_slow": ema21_5m,
            "trend": trend_label,
            "htf_15m": htf_15m_state,
            "regime": regime_label,
            "htf_bull": htf_bull,
            "htf_bear": htf_bear,
            "tf_conflict": False,
            "l2_obi": round(l2_obi, 2),
            "shallow_obi": round(shallow_obi, 2),
            "microprice": round(microprice, 6),
            "microprice_dev_pct": round(microprice_dev_pct, 4),
            "spread_pct": round(spread_pct * 100.0, 4),
            "vol_z": round(vol_z, 2),
            "vel_1m_pct": round(vel_1m, 3),
            "ret_3m_pct": round(ret_3m, 2),
            "atr_pct": round(atr_pct, 4),
            "kaufman_er": round(kaufman_er, 2),
            "coin_tick_pct": round(coin_tick_pct, 5),
            "room_pct": round(active_room * 100.0, 2),
            "dna_rate_pct": dna_rate_pct,
            "dna_approved": dna_approved,
            "htf_ok": htf_ok,
            "zone_ok": zone_ok,
            "book_ok": book_ok,
            "candle_ok": candle_ok,
            "target_side": target_side,
            "stage_tier": stage_tier,
            "dist_to_zone_pct": round(dist_to_zone_pct, 1),
            "strategy": strategy_name,
            "score": final_score,
            "signal": signal,
            "updated_ts": now,
        }


# =========================================================================================
# 3. GATEWAY HFT WEBSOCKET + MICROPRICE + RECONCILIAÇÃO L1 + WATCHDOG AUTO-HEAL
# =========================================================================================
class HyperliquidDeFiGateway:
    def __init__(self, memory_engine: WholeMarketMemoryEngine):
        self.memory = memory_engine
        account_addr, raw_key = validate_required_credentials()
        self.account_address = account_addr
        BOT_STATE["account_address"] = mask_sensitive_hex(self.account_address)

        self.agent_wallet: LocalAccount = Account.from_key(raw_key)
        BOT_STATE["agent_address"] = mask_sensitive_hex(self.agent_wallet.address)

        self.cooldowns: dict[str, float] = {}
        self.recent_closed_ts: dict[str, float] = {}
        self.configured_leverage: dict[str, int] = {}
        self.cache_5m: dict[str, tuple[float, list]] = {}
        self.cache_15m: dict[str, tuple[float, list]] = {}
        self.ws_l2_books: dict[str, dict[str, Any]] = {}
        self.last_ws_allmids_ts: float = time.time()
        self.last_ws_reconnect_ts: float = 0.0
        self.last_ctx_sync_ts: float = 0.0
        self.last_fills_sync_ts: float = 0.0
        self.last_portfolio_sync_ts: float = 0.0

        self.info: Info = Info(constants.MAINNET_API_URL, skip_ws=False)
        self.exchange: Exchange = Exchange(
            wallet=self.agent_wallet,
            base_url=constants.MAINNET_API_URL,
            account_address=self.account_address,
        )
        self.meta = self.info.meta()
        self.sz_decimals = {asset["name"]: asset["szDecimals"] for asset in self.meta["universe"]}

        self._subscribe_ws_channels()
        self.reconcile_onchain_state()

        add_log(
            f"🎯 Sovereign HFT v72.0 Conectado (WebSocket Ativo) | Conta: {mask_sensitive_hex(self.account_address)} | "
            f"19 Moedas (AAVE & INJ Ativas) + Microprice L2 + Soft SL -0.12% / Hard SL L1 -0.28%!"
        )
        threading.Thread(target=self.preconfigure_watchlist_leverage, daemon=True).start()

    def _hl_coin(self, coin: str) -> str:
        if coin in self.sz_decimals:
            return coin
        k_sym = f"k{coin}"
        if k_sym in self.sz_decimals:
            return k_sym
        return coin

    def _norm_coin(self, hl_coin: str) -> str:
        if hl_coin == "kPEPE" and "PEPE" in GLOBAL_BASKET:
            return "PEPE"
        if hl_coin.startswith("k") and hl_coin[1:] in GLOBAL_BASKET and hl_coin not in GLOBAL_BASKET:
            return hl_coin[1:]
        return hl_coin

    @staticmethod
    def compute_book_microstructure(levels: list) -> dict[str, Any]:
        """
        Calcula OBI de 15 níveis, Shallow OBI (Top-3), Microprice Institucional ponderado
        pelo topo do livro ((Bid_Px * Ask_Sz + Ask_Px * Bid_Sz) / (Bid_Sz + Ask_Sz)),
        desvio percentual do Microprice em relação ao Mid Price e liquidez Top-3 em USD/ Contratos.
        """
        if not isinstance(levels, list) or len(levels) < 2 or not levels[0] or not levels[1]:
            return {}
        bids = levels[0]
        asks = levels[1]
        best_bid_px = safe_float(bids[0].get("px", 0.0), 0.0)
        best_bid_sz = safe_float(bids[0].get("sz", 0.0), 0.0)
        best_ask_px = safe_float(asks[0].get("px", 0.0), 0.0)
        best_ask_sz = safe_float(asks[0].get("sz", 0.0), 0.0)
        if best_bid_px <= 0 or best_ask_px <= 0:
            return {}

        mid_px = (best_bid_px + best_ask_px) * 0.5
        spread_pct = (best_ask_px - best_bid_px) / mid_px if mid_px > 0 else 0.0

        top_sz_sum = best_bid_sz + best_ask_sz
        if top_sz_sum > 0:
            microprice = (best_bid_px * best_ask_sz + best_ask_px * best_bid_sz) / top_sz_sum
        else:
            microprice = mid_px
        microprice_dev_pct = ((microprice - mid_px) / mid_px) * 100.0 if mid_px > 0 else 0.0

        bids_15 = bids[:15]
        asks_15 = asks[:15]
        bid_vol_15 = sum(safe_float(b.get("sz", 0.0), 0.0) * (1.5 if i < 5 else 1.0) for i, b in enumerate(bids_15))
        ask_vol_15 = sum(safe_float(a.get("sz", 0.0), 0.0) * (1.5 if i < 5 else 1.0) for i, a in enumerate(asks_15))
        tot_15 = bid_vol_15 + ask_vol_15
        l2_obi = ((bid_vol_15 - ask_vol_15) / tot_15) if tot_15 > 0 else 0.0

        bids_3 = bids[:3]
        asks_3 = asks[:3]
        top3_bid_sz = sum(safe_float(b.get("sz", 0.0), 0.0) for b in bids_3)
        top3_ask_sz = sum(safe_float(a.get("sz", 0.0), 0.0) for a in asks_3)
        top3_bid_usd = sum(safe_float(b.get("sz", 0.0), 0.0) * safe_float(b.get("px", mid_px), mid_px) for b in bids_3)
        top3_ask_usd = sum(safe_float(a.get("sz", 0.0), 0.0) * safe_float(a.get("px", mid_px), mid_px) for a in asks_3)
        tot_3 = top3_bid_sz + top3_ask_sz
        shallow_obi = ((top3_bid_sz - top3_ask_sz) / tot_3) if tot_3 > 0 else 0.0

        return {
            "ts": time.time(),
            "best_bid": best_bid_px,
            "best_ask": best_ask_px,
            "mid_px": mid_px,
            "spread_pct": spread_pct,
            "microprice": microprice,
            "microprice_dev_pct": microprice_dev_pct,
            "l2_obi": round(l2_obi, 4),
            "shallow_obi": round(shallow_obi, 4),
            "top3_bid_sz": top3_bid_sz,
            "top3_ask_sz": top3_ask_sz,
            "top3_bid_usd": top3_bid_usd,
            "top3_ask_usd": top3_ask_usd,
            "levels": levels,
        }

    def _on_ws_all_mids(self, msg: dict[str, Any]):
        try:
            data = msg.get("data", msg) if isinstance(msg, dict) else {}
            mids = data.get("mids", data) if isinstance(data, dict) else {}
            if not isinstance(mids, dict) or not mids:
                return
            self.last_ws_allmids_ts = time.time()
            BOT_STATE["ws_connected"] = True
            BOT_STATE["ws_last_tick_age_sec"] = 0.0
            norm_mids = dict(mids)
            if "PEPE" not in norm_mids and "kPEPE" in norm_mids:
                norm_mids["PEPE"] = norm_mids["kPEPE"]
            self.memory.record_all_mids(norm_mids)
        except Exception as e:
            logger.debug(f"Aviso no callback WebSocket allMids: {e}")

    def _on_ws_l2_book(self, msg: dict[str, Any]):
        try:
            data = msg.get("data", msg) if isinstance(msg, dict) else {}
            if not isinstance(data, dict):
                return
            raw_coin = str(data.get("coin", ""))
            if not raw_coin:
                return
            coin = self._norm_coin(raw_coin)
            levels = data.get("levels", [])
            metrics = self.compute_book_microstructure(levels)
            if metrics:
                self.last_ws_allmids_ts = time.time()
                BOT_STATE["ws_connected"] = True
                BOT_STATE["ws_last_tick_age_sec"] = 0.0
                with WS_BOOK_LOCK:
                    self.ws_l2_books[coin] = metrics
                if coin in BOT_STATE["radar"]:
                    BOT_STATE["radar"][coin]["l2_obi"] = round(metrics["l2_obi"], 2)
                    BOT_STATE["radar"][coin]["shallow_obi"] = round(metrics["shallow_obi"], 2)
                    BOT_STATE["radar"][coin]["microprice"] = round(metrics["microprice"], 6)
                    BOT_STATE["radar"][coin]["microprice_dev_pct"] = round(metrics["microprice_dev_pct"], 4)
                    BOT_STATE["radar"][coin]["spread_pct"] = round(metrics["spread_pct"] * 100.0, 4)
        except Exception as e:
            logger.debug(f"Aviso no callback WebSocket l2Book: {e}")

    def _subscribe_ws_channels(self):
        try:
            # Assina apenas allMids no WebSocket (1 stream global ultra-leve p/ todas as 19 moedas, zero sobrecarga de fila e zero queda!)
            self.info.subscribe({"type": "allMids"}, self._on_ws_all_mids)
            self.last_ws_allmids_ts = time.time()
            BOT_STATE["ws_connected"] = True
        except Exception as e:
            BOT_STATE["ws_connected"] = False
            add_log(f"⚠️ Aviso ao assinar canal WebSocket allMids: {e}")

    def check_websocket_watchdog(self):
        now = time.time()
        silence_sec = now - self.last_ws_allmids_ts
        BOT_STATE["ws_last_tick_age_sec"] = round(silence_sec, 1)
        if silence_sec <= 90.0 or (now - self.last_ws_reconnect_ts) < 90.0:
            return
        self.last_ws_reconnect_ts = now
        BOT_STATE["ws_connected"] = False
        add_log(f"🔄 Watchdog HFT: {silence_sec:.1f}s sem ticks WebSocket allMids! Reiniciando conexão WS (Auto-Heal)...")
        try:
            old_ws = getattr(self.info, "ws_manager", None)
            if old_ws is not None and hasattr(old_ws, "stop"):
                try:
                    old_ws.stop()
                except Exception:
                    pass
            self.info = Info(constants.MAINNET_API_URL, skip_ws=False)
            self._subscribe_ws_channels()
            add_log("✅ Watchdog HFT: Streams WebSocket (allMids + l2Book) reconectados com sucesso!")
        except Exception as e:
            add_log(f"⚠️ Watchdog HFT falhou ao reconectar WebSocket: {e}")

    def reconcile_onchain_state(self):
        """
        Reconciliação de Estado ao Iniciar: sincroniza imediatamente as posições abertas
        e cancela qualquer ordem aberta/trigger órfã em moedas sem posição ativa na L1.
        """
        try:
            _, open_pos = self.sync_portfolio(force=True)
            active_coins = {p["coin"] for p in open_pos}
            active_hl_coins = {self._hl_coin(c) for c in active_coins}

            open_ords = self.info.open_orders(self.account_address)
            frontend_ords = []
            if hasattr(self.info, "frontend_open_orders"):
                try:
                    frontend_ords = self.info.frontend_open_orders(self.account_address)
                except Exception:
                    frontend_ords = []

            all_orders_by_oid: dict[int, dict[str, Any]] = {}
            for ord_list in (open_ords, frontend_ords):
                if isinstance(ord_list, list):
                    for o in ord_list:
                        if isinstance(o, dict) and "oid" in o:
                            all_orders_by_oid[int(o["oid"])] = o

            canceled_count = 0
            for oid, o in all_orders_by_oid.items():
                raw_c = str(o.get("coin", ""))
                norm_c = self._norm_coin(raw_c)
                if raw_c not in active_hl_coins and norm_c not in active_coins:
                    try:
                        with GATEWAY_LOCK:
                            self.exchange.cancel(raw_c, oid)
                        canceled_count += 1
                        add_log(f"🧹 Reconciliação L1: Ordem órfã cancelada em {norm_c} (oid={oid})")
                    except Exception as ce:
                        logger.debug(f"Aviso ao cancelar ordem órfã {oid} em {raw_c}: {ce}")

            if canceled_count > 0:
                add_log(f"✅ Reconciliação L1 concluída: {canceled_count} ordem(ns) órfã(s) removida(s).")
            else:
                add_log(f"✅ Reconciliação L1 concluída: {len(active_coins)} posição(ões) ativa(s) e 0 ordens órfãs.")
        except Exception as e:
            add_log(f"⚠️ Aviso na reconciliação inicial de estado L1: {e}")

    def get_onchain_position_size(self, coin: str) -> float:
        """
        Consulta diretamente a L1 da Hyperliquid para confirmar se a posição ainda existe
        antes de disparar qualquer fechamento a mercado via software.
        """
        hl_target = self._hl_coin(coin)
        user_state = self.info.user_state(self.account_address)
        for pos in user_state.get("assetPositions", []):
            item = pos.get("position", {})
            raw_c = str(item.get("coin", ""))
            norm_c = self._norm_coin(raw_c)
            if raw_c == hl_target or norm_c == coin:
                szi = safe_float(item.get("szi", 0.0), 0.0)
                if abs(szi) > 0:
                    return szi
        return 0.0

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
            time.sleep(0.10)

    def sync_global_market_tape(self) -> dict[str, Any]:
        self.check_websocket_watchdog()
        now = time.time()
        # Se o WebSocket já atualizou a fita há menos de 2.5s, evita requisição HTTP redundante
        if (now - self.last_ws_allmids_ts) <= 2.5 and self.memory.snapshots_count > 0:
            return BOT_STATE["market_brain"]
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

        if len(open_positions) < effective_max_pos:
            BOT_STATE["market_brain"]["second_slot_status"] = "SLOT ÚNICO LIVRE (CAÇANDO EXTREMO <=24% OU >=76%)"
            return (True, "SLOT_1_OPEN")
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
                coin = self._norm_coin(raw_c)
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
                    c_name = str(asset_info.get("name", ""))
                    norm_name = self._norm_coin(c_name)
                    if norm_name in GLOBAL_BASKET and idx < len(ctxs):
                        ctx = ctxs[idx]
                        BOT_STATE["funding_by_coin"][norm_name] = float(ctx.get("funding", 0.0))
                        BOT_STATE["open_interest_by_coin"][norm_name] = float(ctx.get("openInterest", 0.0))
        except Exception:
            pass

    def fetch_l2_metrics_cached(self, coin: str, max_ws_age_sec: float = 15.0) -> dict[str, Any]:
        r_prev = BOT_STATE.get("radar", {}).get(coin, {})
        b_prev = safe_float(r_prev.get("band_pos", 0.50), 0.50)
        is_hot_coin = (b_prev <= 0.32) or (b_prev >= 0.68) or any(op.get("coin") == coin for op in BOT_STATE.get("open_positions", []))
        max_ws_age_sec = min(max_ws_age_sec, 3.5) if is_hot_coin else max(max_ws_age_sec, 22.0)
        """
        Retorna as métricas L2 + Microprice diretamente da memória alimentada via WebSocket
        em sub-milissegundo; faz fallback para l2_snapshot HTTP apenas se o stream WS ainda
        não tiver enviado o primeiro livro daquela moeda.
        """
        now = time.time()
        with WS_BOOK_LOCK:
            ws_entry = self.ws_l2_books.get(coin)
            if ws_entry and (now - safe_float(ws_entry.get("ts", 0.0), 0.0)) <= max_ws_age_sec:
                return dict(ws_entry)
        try:
            snap = self.info.l2_snapshot(self._hl_coin(coin))
            levels = snap.get("levels", [])
            metrics = self.compute_book_microstructure(levels)
            if metrics:
                with WS_BOOK_LOCK:
                    self.ws_l2_books[coin] = metrics
                return metrics
        except Exception:
            pass
        with WS_BOOK_LOCK:
            return dict(self.ws_l2_books.get(coin, {}))

    def fetch_candles_cached(
        self,
        coin: str,
        interval: str = "5m",
        count: int = 45,
        ttl_override: float | None = None,
        stagger_idx: int = 0,
    ) -> list:
        now = time.time()
        jitter = (stagger_idx % 19) * 2.2
        if interval == "15m":
            ttl = (ttl_override if ttl_override is not None else 110.0) + jitter
            cached_15 = self.cache_15m.get(coin)
            if cached_15 and (now - cached_15[0]) < ttl and int(now // 900) == int(cached_15[0] // 900):
                return cached_15[1]
            try:
                now_ms = int(now * 1000)
                start_ms = now_ms - (count * 15 * 60 * 1000)
                data = self.info.candles_snapshot(self._hl_coin(coin), "15m", start_ms, now_ms)
                if data:
                    self.cache_15m[coin] = (now, data)
                return data or (cached_15[1] if cached_15 else [])
            except Exception:
                if cached_15:
                    self.cache_15m[coin] = (now - ttl + 15.0, cached_15[1])
                    return cached_15[1]
                return []
        else:
            ttl = (ttl_override if ttl_override is not None else 65.0) + jitter
            cached_5 = self.cache_5m.get(coin)
            if cached_5 and (now - cached_5[0]) < ttl and int(now // 300) == int(cached_5[0] // 300):
                return cached_5[1]
            try:
                now_ms = int(now * 1000)
                start_ms = now_ms - (count * 5 * 60 * 1000)
                data = self.info.candles_snapshot(self._hl_coin(coin), "5m", start_ms, now_ms)
                if data:
                    self.cache_5m[coin] = (now, data)
                return data or (cached_5[1] if cached_5 else [])
            except Exception:
                if cached_5:
                    self.cache_5m[coin] = (now - ttl + 15.0, cached_5[1])
                    return cached_5[1]
                return []

    def sync_portfolio(self, force: bool = False):
        now = time.time()
        if not force and (now - self.last_portfolio_sync_ts) < 1.2:
            return BOT_STATE["equity_usdc"], BOT_STATE["open_positions"]
        try:
            self.last_portfolio_sync_ts = now
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
                    raw_pos_c = str(item.get("coin", ""))
                    coin = self._norm_coin(raw_pos_c)
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

                    r_coin_info = BOT_STATE["radar"].get(coin, {})
                    coin_atr = safe_float(r_coin_info.get("atr_pct", 0.0045), 0.0045)
                    ai_mem = BOT_STATE.get("coin_ai_brain", {}).get(coin, {})
                    learned_harvest_mult = safe_float(ai_mem.get("harvest_mult", 1.0), 1.0)
                    dyn_tp_move = max(0.0045, min(BOT_STATE["tp_move_pct"], coin_atr * 1.95 * learned_harvest_mult))
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
                        shield_tag = "🛟 MODO RECUPERAÇÃO 0x0 ATIVO (Sai no Preço de Entrada assim que voltar!)"
                    else:
                        dyn_stop_move = -dyn_sl_move
                        shield_tag = f"🛡️ SOFT SL ({dyn_stop_move * eff_lev * 100:.1f}% ROE) | HARD STOP L1 (-{BOT_STATE['hard_sl_move_pct'] * eff_lev * 100:.1f}% ROE)"

                    prev_notified_step = int(BOT_STATE["notified_step_by_coin"].get(coin, 0))
                    if current_step > prev_notified_step:
                        BOT_STATE["notified_step_by_coin"][coin] = current_step
                        est_fee_usd = pos_val * BOT_STATE["round_trip_fee_pct"]
                        net_pnl_now = max(0.01, pnl - est_fee_usd)
                        pnl_brl_now = net_pnl_now * USD_BRL_RATE
                        locked_roe = dyn_stop_move * eff_lev * 100.0
                        if current_step == 1:
                            step_desc = "🛡️ Risco 100% Zerado — deixando subir até o alvo do canal!"
                        else:
                            step_desc = f"🔥 Lucro Gordo Travado em +{locked_roe:.1f}% ROE garantido — surfando o topo!"
                        send_mobile_alert(
                            f"🚀 {coin} ({side}) SUBINDO — DEGRAU {current_step} ATIVO!",
                            f"A operação em {coin} ({side} {eff_lev:.0f}x) bateu +{roe_pct:.2f}% ROE (Líquido ~+${net_pnl_now:.2f} USDC / R$ +{pnl_brl_now:.2f} já descontando taxa)!\n"
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

            calculated_notional = max(13.5, min(44.0, total_equity * 0.28 * BOT_STATE["leverage"]))
            BOT_STATE["order_notional"] = round(calculated_notional, 2)

            # Inclui moedas abertas na Simulação em active_symbols_now para NUNCA zerar o peak_move_by_coin da Simulação!
            for pp_act in BOT_STATE.get("paper_open_positions", []):
                if pp_act.get("coin"):
                    active_symbols_now.add(pp_act["coin"])

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

            if BOT_STATE.get("paper_mode", True):
                paper_pos_updated = []
                paper_float = 0.0
                for pp in BOT_STATE.get("paper_open_positions", []):
                    pc = pp["coin"]
                    pepx = safe_float(pp.get("entry_px", 0.0), 0.0)
                    pval = safe_float(pp.get("pos_val_usd", 15.0), 15.0)
                    pside = pp.get("side", "LONG")
                    dq_p = self.memory.price_tape.get(pc)
                    pmv = pp.get("move_pct", 0.0)
                    if dq_p and len(dq_p) > 0 and pepx > 0:
                        pmid = float(dq_p[-1][1])
                        pmv = ((pmid - pepx) / pepx) if pside == "LONG" else ((pepx - pmid) / pepx)
                    ppnl = round(pmv * pval, 4)
                    paper_float += ppnl
                    plev = float(BOT_STATE["leverage"])
                    proe = pmv * plev * 100.0
                    ppeak = max(safe_float(pp.get("peak_move_pct", 0.0), 0.0), safe_float(BOT_STATE["peak_move_by_coin"].get(pc, 0.0), 0.0), pmv)
                    pworst = min(safe_float(pp.get("worst_move_pct", 0.0), 0.0), safe_float(BOT_STATE["worst_move_by_coin"].get(pc, 0.0), 0.0), pmv)
                    BOT_STATE["peak_move_by_coin"][pc] = ppeak
                    BOT_STATE["worst_move_by_coin"][pc] = pworst

                    dyn_stop_mv = -BOT_STATE["sl_move_pct"]
                    if ppeak >= BOT_STATE["trail_step3_trigger_pct"]:
                        dyn_stop_mv = max(0.0058, ppeak - BOT_STATE["trail_step3_dist_pct"])
                    elif ppeak >= BOT_STATE["trail_step2_trigger_pct"]:
                        dyn_stop_mv = max(0.0044, ppeak - BOT_STATE["trail_step2_dist_pct"])
                    elif ppeak >= BOT_STATE["trail_step1_trigger_pct"]:
                        dyn_stop_mv = max(BOT_STATE["breakeven_lock_pct"], ppeak - BOT_STATE["trail_step1_dist_pct"])
                    elif ppeak >= BOT_STATE["breakeven_trigger_pct"]:
                        dyn_stop_mv = BOT_STATE["breakeven_lock_pct"]
                    elif ppeak >= BOT_STATE["zero_risk_trigger_pct"]:
                        dyn_stop_mv = BOT_STATE["zero_risk_lock_pct"]

                    pp.update({
                        "pnl": ppnl,
                        "move_pct": pmv,
                        "peak_move_pct": ppeak,
                        "worst_move_pct": pworst,
                        "peak_roe_pct": ppeak * plev * 100.0,
                        "dynamic_stop_move_pct": dyn_stop_mv,
                        "roe_pct": proe,
                        "shield_tag": f"🧪 SIMULAÇÃO (Stop {dyn_stop_mv*plev*100:+.2f}% ROE | Pico {ppeak*plev*100:+.2f}% ROE)",
                    })
                    paper_pos_updated.append(pp)
                BOT_STATE["paper_open_positions"] = paper_pos_updated
                # Se não houver posição real aberta na L1, exibe as posições simuladas no painel
                if not open_pos:
                    open_pos = paper_pos_updated
                    BOT_STATE["floating_pnl_usdc"] = round(paper_float, 2)

            BOT_STATE["open_positions"] = open_pos
            BOT_STATE["last_update"] = time.strftime("%H:%M:%S UTC", time.gmtime())
            ws_tag = "WS ATIVO" if BOT_STATE.get("ws_connected") else "WS RECONECTANDO"
            mode_badge = "🧪 MODO SIMULAÇÃO (0 RISCO REAL)" if BOT_STATE.get("paper_mode", True) else "⚡ MODO REAL L1"
            BOT_STATE["status"] = (
                f"{mode_badge} | {ws_tag} — SNIPER v74.0 (Banca Sim: ${BOT_STATE['paper_equity_usdc']:.2f} | {BOT_STATE['paper_wins']}W/{BOT_STATE['paper_losses']}L)"
                if BOT_STATE["trading_enabled"]
                else "PAUSADO PELO OPERADOR"
            )

            self.sync_onchain_trade_history()
            return total_equity, open_pos
        except Exception as e:
            err_str = str(e)
            if "429" in err_str:
                time.sleep(4.0)
            else:
                add_log(f"⚠️ Aviso na leitura L1: {err_str[:80]}")
            return BOT_STATE["equity_usdc"], BOT_STATE["open_positions"]

    def execute_partial_take_profit(self, pos: dict):
        coin = pos["coin"]
        if BOT_STATE["partial_taken_by_coin"].get(coin, False):
            return
        if pos.get("pos_val_usd", 0.0) < 150.0:
            BOT_STATE["partial_taken_by_coin"][coin] = True
            return

        with GATEWAY_LOCK:
            try:
                onchain_szi = self.get_onchain_position_size(coin)
                if abs(onchain_szi) <= 0:
                    BOT_STATE["partial_taken_by_coin"][coin] = True
                    return
                hl_c = self._hl_coin(coin)
                decimals = self.sz_decimals.get(hl_c, self.sz_decimals.get(coin, 2))
                abs_sz = abs(onchain_szi)
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
                    f"Metade do lote realizada com lucro (+{pos['roe_pct']:.1f}% ROE)! Restante 100% blindado no Zero-Loss surfando o alvo!",
                    priority="high",
                    tags="money_mouth_face,chart_with_upwards_trend",
                )
            except Exception as e:
                BOT_STATE["partial_taken_by_coin"][coin] = True
                logger.warning(f"Aviso ao executar parcial em {coin}: {e}")

    def audit_and_protect_positions(self, open_positions: list):
        brain = BOT_STATE.get("market_brain", {})

        for p in list(open_positions):
            coin = p["coin"]
            if not any(op.get("coin") == coin for op in BOT_STATE.get("open_positions", [])):
                continue
            now_audit = time.time()
            prev_r = BOT_STATE["radar"].get(coin, {})
            if (now_audit - safe_float(prev_r.get("updated_ts", 0.0), 0.0)) >= 2.5:
                try:
                    c_5m = self.fetch_candles_cached(coin, "5m", 45, ttl_override=12.0)
                    c_15m = self.fetch_candles_cached(coin, "15m", 35, ttl_override=15.0)
                    l2_m = self.fetch_l2_metrics_cached(coin, max_ws_age_sec=8.0)
                    c_fund = BOT_STATE["funding_by_coin"].get(coin, 0.0)
                    k_info = self.memory.get_kalman_telemetry(coin)
                    BOT_STATE["radar"][coin] = QuantumOracleEngine.analyze_omni_intelligence(
                        coin, c_5m, c_15m, l2_m, c_fund, k_info, brain
                    )
                except Exception:
                    pass

            side = p["side"]
            entry_px_p = safe_float(p.get("entry_px", 0.0), 0.0)
            pos_val_p = safe_float(p.get("pos_val_usd", 15.0), 15.0)
            eff_lev_p = safe_float(p.get("eff_lev", BOT_STATE["leverage"]), float(BOT_STATE["leverage"]))
            dq_now = self.memory.price_tape.get(coin)
            move = safe_float(p.get("move_pct", 0.0), 0.0)
            if dq_now and len(dq_now) > 0 and entry_px_p > 0:
                live_px_now = float(dq_now[-1][1])
                move = ((live_px_now - entry_px_p) / entry_px_p) if side == "LONG" else ((entry_px_p - live_px_now) / entry_px_p)
                p["move_pct"] = move
                p["pnl"] = round(move * pos_val_p, 4)
                p["roe_pct"] = move * eff_lev_p * 100.0

            peak_move = max(
                safe_float(p.get("peak_move_pct", 0.0), 0.0),
                safe_float(BOT_STATE["peak_move_by_coin"].get(coin, 0.0), 0.0),
                move,
            )
            worst_move = min(
                safe_float(p.get("worst_move_pct", 0.0), 0.0),
                safe_float(BOT_STATE["worst_move_by_coin"].get(coin, 0.0), 0.0),
                move,
            )
            BOT_STATE["peak_move_by_coin"][coin] = peak_move
            BOT_STATE["worst_move_by_coin"][coin] = worst_move
            p["peak_move_pct"] = peak_move
            p["worst_move_pct"] = worst_move
            p["peak_roe_pct"] = peak_move * eff_lev_p * 100.0

            tp_target = p.get("tp_target_move_pct", BOT_STATE["tp_move_pct"])
            sl_limit = p.get("sl_limit_move_pct", BOT_STATE["sl_move_pct"])
            if peak_move >= BOT_STATE["trail_step3_trigger_pct"]:
                dyn_stop = max(0.0058, peak_move - BOT_STATE["trail_step3_dist_pct"])
            elif peak_move >= BOT_STATE["trail_step2_trigger_pct"]:
                dyn_stop = max(0.0044, peak_move - BOT_STATE["trail_step2_dist_pct"])
            elif peak_move >= BOT_STATE["trail_step1_trigger_pct"]:
                dyn_stop = max(BOT_STATE["breakeven_lock_pct"], peak_move - BOT_STATE["trail_step1_dist_pct"])
            elif peak_move >= BOT_STATE["breakeven_trigger_pct"]:
                dyn_stop = BOT_STATE["breakeven_lock_pct"]
            elif peak_move >= BOT_STATE["zero_risk_trigger_pct"]:
                dyn_stop = BOT_STATE["zero_risk_lock_pct"]
            else:
                dyn_stop = -sl_limit
            p["dynamic_stop_move_pct"] = dyn_stop

            now_audit = time.time()
            age_sec = now_audit - safe_float(p.get("opened_ts", now_audit), now_audit)
            radar_info = BOT_STATE["radar"].get(coin, {})
            band_pos = safe_float(radar_info.get("band_pos", 0.50), 0.50)
            rsi_now = safe_float(radar_info.get("rsi", 50.0), 50.0)
            l2_obi = safe_float(radar_info.get("l2_obi", 0.0), 0.0)
            vel_1m = safe_float(radar_info.get("vel_1m_pct", 0.0), 0.0)
            htf_15m_now = str(radar_info.get("htf_15m", ""))

            # 1) SAÍDA DE RECUPERAÇÃO 0x0 IMEDIATA:
            if age_sec >= 45.0 and worst_move <= BOT_STATE["recovery_drawdown_pct"] and move >= BOT_STATE["recovery_exit_pct"] and peak_move < 0.0014:
                book_strong_favor = (
                    (side == "LONG" and l2_obi >= 0.18 and vel_1m >= MIN_ENTRY_VEL_1M_PCT)
                    or (side == "SHORT" and l2_obi <= -0.18 and vel_1m <= -MIN_ENTRY_VEL_1M_PCT)
                )
                if not book_strong_favor:
                    add_log(
                        f"🛟 SAÍDA DE RECUPERAÇÃO 0x0 BLINDADA em {coin} ({p['roe_pct']:+.2f}% ROE / ${p['pnl']:+.2f})! "
                        f"Operação recuperou de susto ({worst_move*100:.2f}%) — saindo no 0x0 para proteger a banca!"
                    )
                    self.close_position(coin, is_loss=False, side_closed=side)
                    continue

            # 2) COLHEDOR DE LUCRO CHEIO DINÂMICO (Unificado com BOT_STATE['cash_in_band_move_pct']):
            cash_in_target = safe_float(BOT_STATE.get("cash_in_band_move_pct", 0.0028), 0.0028)
            opposite_band_target = max(0.0022, cash_in_target - 0.0002)
            ratchet_peak_target = max(0.0020, cash_in_target - 0.0004)

            reached_full_cashin = (move >= cash_in_target) and (
                (side == "LONG" and (band_pos >= 0.65 or rsi_now >= 57.0 or vel_1m <= 0.0 or l2_obi <= 0.0))
                or (side == "SHORT" and (band_pos <= 0.35 or rsi_now <= 43.0 or vel_1m >= 0.0 or l2_obi >= 0.0))
            )
            reached_opposite_band_green = (move >= opposite_band_target) and (
                (side == "LONG" and (band_pos >= 0.72 or rsi_now >= 58.0) and (vel_1m <= 0.015 or l2_obi <= 0.0))
                or (side == "SHORT" and (band_pos <= 0.28 or rsi_now <= 42.0) and (vel_1m >= -0.015 or l2_obi >= 0.0))
            )
            shallow_obi_now = safe_float(radar_info.get("shallow_obi", 0.0), 0.0)
            mpx_dev_now = safe_float(radar_info.get("microprice_dev_pct", 0.0), 0.0)
            flow_exhaustion_peak = (move >= 0.0016) and (
                (side == "LONG" and shallow_obi_now <= -0.12 and mpx_dev_now < 0.0)
                or (side == "SHORT" and shallow_obi_now >= 0.12 and mpx_dev_now > 0.0)
            )
            ratchet_profit_save = (peak_move >= ratchet_peak_target) and (move <= max(0.0015, peak_move - 0.0008)) and (move >= 0.0013)
            if reached_full_cashin or reached_opposite_band_green or flow_exhaustion_peak or ratchet_profit_save:
                add_log(
                    f"💰 CASH-IN NO PICO DO CANAL em {coin} (+{p['roe_pct']:.2f}% ROE / +${p['pnl']:.2f} bruto | Banda {int(band_pos*100)}%)! "
                    f"Green cheio trancado no topo antes de devolver qualquer centavo!"
                )
                self.close_position(coin, is_loss=False, side_closed=side)
                continue

            # 3) DEFESA DE INVERSÃO REAL DO 15M (Após 180s se o 15M virar contra com velocidade real):
            if age_sec >= 180.0 and move <= -0.0011:
                trend_flipped_against_long = (side == "LONG") and (
                    htf_15m_now == "BAIXA 15M" and l2_obi <= -0.10 and vel_1m <= -MIN_ENTRY_VEL_1M_PCT
                )
                trend_flipped_against_short = (side == "SHORT") and (
                    htf_15m_now == "ALTA 15M" and l2_obi >= 0.10 and vel_1m >= MIN_ENTRY_VEL_1M_PCT
                )
                if trend_flipped_against_long or trend_flipped_against_short:
                    add_log(
                        f"🛡️ DEFESA IRON SHIELD 15M em {coin} ({p['roe_pct']:.2f}% ROE)! "
                        f"Tendência de 15M inverteu contra ({htf_15m_now}, Book {l2_obi:+.2f}) — abortando antes do stop cheio!"
                    )
                    self.close_position(coin, is_loss=True, side_closed=side)
                    continue

            # 3.2) EJEÇÃO INTELIGENTE POR VIRADA DE FLUXO APÓS PICO POSITIVO:
            if age_sec >= 240.0 and peak_move >= 0.0014 and (0.0006 <= move <= 0.0016):
                flow_reversed_against = (
                    (side == "LONG" and l2_obi <= -0.12 and vel_1m <= -0.025)
                    or (side == "SHORT" and l2_obi >= 0.12 and vel_1m >= 0.025)
                )
                if flow_reversed_against:
                    add_log(
                        f"🛡️ EJEÇÃO INTELIGENTE ZERO-LOSS em {coin} (+{p['roe_pct']:.2f}% ROE | Pico +{p['peak_roe_pct']:.1f}% ROE)! "
                        f"Fluxo L2 virou contra após 4m+ — saindo no positivo/0x0 antes de virar Red!"
                    )
                    self.close_position(coin, is_loss=False, side_closed=side)
                    continue

            # 3.4) EJEÇÃO ANTI-ESTAGNAÇÃO 180s (Evita ficar 509s preso como no BNB até virar Red!):
            # Se após 180s (3m) a moeda não teve força nem para bater +0.10% move e o fluxo L2 virou contra, sai perto do 0x0!
            if age_sec >= 180.0 and peak_move < 0.0010 and (-0.0003 <= move <= 0.0008):
                weak_flow = (side == "LONG" and (l2_obi < 0.05 or vel_1m <= 0.0)) or (side == "SHORT" and (l2_obi > -0.05 or vel_1m >= 0.0))
                if weak_flow:
                    add_log(
                        f"⏱️ EJEÇÃO ANTI-ESTAGNAÇÃO 180s em {coin} ({p['roe_pct']:+.2f}% ROE | {int(age_sec)}s sem explosão)! "
                        f"Abortando trade lento antes de virar Stop!"
                    )
                    self.close_position(coin, is_loss=False, side_closed=side)
                    continue

            # 3.5) TIME-STOP ANTI-ZUMBI (15 minutos / 900s — somente no positivo):
            if age_sec >= 900.0 and (0.0004 <= move < BOT_STATE["zero_risk_trigger_pct"]):
                is_stagnant = (abs(vel_1m) <= 0.015) or (0.38 <= band_pos <= 0.62)
                if is_stagnant:
                    add_log(
                        f"⏱️ TIME-STOP ANTI-ZUMBI NO VERDE em {coin} (+{p['roe_pct']:.2f}% ROE | {int(age_sec//60)}m aberta)! "
                        f"Operação lenta encerrada no positivo sem prejuízo!"
                    )
                    self.close_position(coin, is_loss=False, side_closed=side)
                    continue

            # 4) Parcial de 50% no bolso
            if move >= BOT_STATE["partial_tp_trigger_pct"] and not p.get("partial_done", False):
                self.execute_partial_take_profit(p)

            # 5) Take Profit Cheio, Escada de Lucro, Micro-Shield (com Disjuntor Anti-Cascata) e Soft Stop Técnico (-0.12%)
            if move >= tp_target:
                add_log(f"🎯 TAKE PROFIT ATINGIDO em {coin} (+{p['roe_pct']:.2f}% ROE / +${p['pnl']:.2f})! Fechando posição...")
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
                    f"Operação fechou no negativo ({move*100:.2f}%) — ativando Quarentena e Disjuntor Anti-Cascata!"
                )
                self.close_position(coin, is_loss=True, side_closed=side)
            elif move <= -sl_limit:
                eff_sl_used = sl_limit * 100.0
                add_log(
                    f"🛡️ SOFT STOP LOSS TÉCNICO (-{eff_sl_used:.2f}%) em {coin} ({p['roe_pct']:.2f}% ROE | {int(age_sec)}s)! "
                    f"Ativando Disjuntor Anti-Cascata (20m de trava em {side} + 6m de pausa geral)..."
                )
                self.close_position(coin, is_loss=True, side_closed=side)

    def open_sniper_order(self, coin: str, is_buy: bool, strategy_label: str = "", score: float = 90.0) -> bool:
        if coin in COMPASS_ONLY_COINS:
            return False
        now = time.time()
        if now - self.cooldowns.get(coin, 0) < 1800:
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
        if len(BOT_STATE["open_positions"]) >= BOT_STATE["max_positions"]:
            return False

        with GATEWAY_LOCK:
            try:
                lev = BOT_STATE["leverage"]
                hl_coin = self._hl_coin(coin)
                if self.configured_leverage.get(coin) != lev:
                    self.exchange.update_leverage(lev, hl_coin, is_cross=True)
                    self.configured_leverage[coin] = lev

                # Leitura L2 fresquíssima (WebSocket < 2.5s ou snapshot HTTP imediato)
                l2_m = self.fetch_l2_metrics_cached(coin, max_ws_age_sec=2.5)
                if not l2_m:
                    snap_now = self.info.l2_snapshot(hl_coin)
                    l2_m = self.compute_book_microstructure(snap_now.get("levels", []))
                if not l2_m:
                    return False

                best_bid = safe_float(l2_m.get("best_bid", 0.0), 0.0)
                best_ask = safe_float(l2_m.get("best_ask", 0.0), 0.0)
                mid_px = safe_float(l2_m.get("mid_px", 0.0), 0.0)
                spread_pct = safe_float(l2_m.get("spread_pct", 1.0), 1.0)
                live_obi_now = safe_float(l2_m.get("l2_obi", 0.0), 0.0)
                shallow_obi = safe_float(l2_m.get("shallow_obi", 0.0), 0.0)
                microprice = safe_float(l2_m.get("microprice", mid_px), mid_px)
                microprice_dev_pct = safe_float(l2_m.get("microprice_dev_pct", 0.0), 0.0)

                if best_bid <= 0 or best_ask <= 0 or mid_px <= 0:
                    return False

                # Validação estrita de Spread <= 0.06% (0.0006)
                max_spread = safe_float(BOT_STATE.get("max_entry_spread_pct", 0.0006), 0.0006)
                if spread_pct > max_spread:
                    add_log(
                        f"🛡️ Disparo {new_side} cancelado em {coin}: Spread L2 acima do limite "
                        f"({spread_pct*100:.3f}% > {max_spread*100:.2f}%)"
                    )
                    return False

                # Confirmação de OBI (15 níveis), Shallow OBI (Top-3) e Microprice Institucional
                req_obi_now = 0.22 if (coin in HIGH_BETA_COINS) else 0.18
                if is_buy and (live_obi_now < req_obi_now or shallow_obi < 0.12 or microprice_dev_pct < 0.008):
                    add_log(
                        f"🛡️ Disparo LONG cancelado em {coin}: Pressão L2/Microprice insuficiente "
                        f"(OBI {live_obi_now:+.2f} | Top3 {shallow_obi:+.2f} | MicroPx {microprice_dev_pct:+.4f}%)"
                    )
                    return False
                if (not is_buy) and (live_obi_now > -req_obi_now or shallow_obi > -0.12 or microprice_dev_pct > -0.008):
                    add_log(
                        f"🛡️ Disparo SHORT cancelado em {coin}: Pressão L2/Microprice insuficiente "
                        f"(OBI {live_obi_now:+.2f} | Top3 {shallow_obi:+.2f} | MicroPx {microprice_dev_pct:+.4f}%)"
                    )
                    return False

                decimals = self.sz_decimals.get(hl_coin, self.sz_decimals.get(coin, 2))
                kelly_mult, db_count = QUANT_BRAIN.get_kelly_multiplier_and_count()
                BOT_STATE["kelly_mult"] = kelly_mult
                BOT_STATE["quant_db_count"] = db_count
                radar_c = BOT_STATE.get("radar", {}).get(coin, {})
                coin_regime = str(radar_c.get("regime", "RANGING"))
                chosen_arm = QUANT_BRAIN.select_exit_arm(coin_regime)
                BOT_STATE["active_exit_arm_by_coin"][coin] = chosen_arm
                arm_cfg = QuantBrainDB.EXIT_ARMS.get(chosen_arm, QuantBrainDB.EXIT_ARMS["SWING_ATR"])
                BOT_STATE["zero_risk_trigger_pct"] = arm_cfg["zero_risk"]
                BOT_STATE["zero_risk_lock_pct"] = arm_cfg["zero_lock"]

                base_notional = BOT_STATE["order_notional"]
                notional = round(max(13.5, base_notional * kelly_mult), 2)

                size = round(notional / mid_px, decimals)
                if size <= 0:
                    return False

                # Validação de Liquidez Top-3 >= 3x o tamanho da nossa ordem
                min_liq_mult = safe_float(BOT_STATE.get("min_top3_liquidity_mult", 3.0), 3.0)
                exec_top3_sz = safe_float(l2_m.get("top3_ask_sz" if is_buy else "top3_bid_sz", 0.0), 0.0)
                exec_top3_usd = safe_float(l2_m.get("top3_ask_usd" if is_buy else "top3_bid_usd", 0.0), 0.0)
                if exec_top3_sz < (size * min_liq_mult) or exec_top3_usd < (notional * min_liq_mult):
                    add_log(
                        f"🛡️ Disparo {new_side} cancelado em {coin}: Liquidez Top-3 insuficiente "
                        f"(${exec_top3_usd:.2f} < {min_liq_mult:.0f}x lote ${notional * min_liq_mult:.2f})"
                    )
                    return False

                is_paper = bool(BOT_STATE.get("paper_mode", True))
                mode_tag = "🧪 [SIMULAÇÃO 0-RISCO]" if is_paper else "⚡ [REAL L1]"
                add_log(
                    f"{mode_tag} DISPARANDO {new_side} ({lev}x) em {coin} "
                    f"[{strategy_label} | OBI {live_obi_now:+.2f} | Top3 {shallow_obi:+.2f} | MicroPx {microprice_dev_pct:+.3f}% | Score {score:.1f}] | "
                    f"Qtd: {size} (~${notional}) @ ${mid_px:.4f}"
                )

                if is_paper:
                    entry_fill_px = best_ask if is_buy else best_bid
                    self.cooldowns[coin] = now
                    BOT_STATE["peak_move_by_coin"][coin] = 0.0
                    BOT_STATE["worst_move_by_coin"][coin] = 0.0
                    BOT_STATE["partial_taken_by_coin"][coin] = False
                    BOT_STATE["notified_step_by_coin"][coin] = 0
                    BOT_STATE["opened_ts_by_coin"][coin] = now
                    BOT_STATE["paper_open_positions"] = [{
                        "coin": coin,
                        "size": size if is_buy else -size,
                        "pos_val_usd": round(notional, 2),
                        "margin_used": round(notional / max(1, lev), 2),
                        "eff_lev": float(lev),
                        "entry_px": entry_fill_px,
                        "pnl": 0.0,
                        "move_pct": 0.0,
                        "peak_move_pct": 0.0,
                        "worst_move_pct": 0.0,
                        "peak_roe_pct": 0.0,
                        "tp_target_move_pct": BOT_STATE["tp_move_pct"],
                        "sl_limit_move_pct": BOT_STATE["sl_move_pct"],
                        "dynamic_stop_move_pct": -BOT_STATE["sl_move_pct"],
                        "partial_done": False,
                        "opened_ts": now,
                        "shield_tag": "🧪 SIMULAÇÃO ATIVA (0 USDC REAL)",
                        "roe_pct": 0.0,
                        "side": new_side,
                    }]
                    BOT_STATE["open_positions"] = list(BOT_STATE["paper_open_positions"])
                    self.memory.save_persisted_memory(force=True)
                    send_mobile_alert(
                        f"🧪 [SIMULAÇÃO] NOVA ENTRADA: {new_side} ({lev}x) em {coin}",
                        f"🎯 Estratégia: {strategy_label} (Score {score:.1f})\n"
                        f"💵 Preço Simulado: ${entry_fill_px:.4f} | Lote: ~${notional:.2f} ({size} {coin})\n"
                        f"🧪 Banca Simulada: ${BOT_STATE['paper_equity_usdc']:.2f} USDC (0 risco real!)",
                        priority="default",
                        tags="test_tube,chart_with_upwards_trend",
                    )
                    return True

                # Tentativa Limit IOC no Topo do Livro com fallback imediato a mercado
                res = None
                try:
                    top_px = best_ask if is_buy else best_bid
                    lim_open = self.exchange.order(hl_coin, is_buy, size, top_px, {"limit": {"tif": "Ioc"}}, reduce_only=False)
                    if "filled" in str(lim_open).lower():
                        res = lim_open
                except Exception:
                    pass
                if res is None:
                    res = self.exchange.market_open(hl_coin, is_buy, size, mid_px, 0.0012)
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

                # Hard Stop On-Chain L1 em -0.28% move (paraquedas de emergência caso o servidor caia)
                try:
                    hard_sl_dist = safe_float(BOT_STATE.get("hard_sl_move_pct", 0.0028), 0.0028)
                    px_digits = max(0, 6 - decimals) if mid_px < 10.0 else (2 if mid_px < 1000.0 else 1)
                    hard_sl_px = round(mid_px * (1.0 - hard_sl_dist) if is_buy else mid_px * (1.0 + hard_sl_dist), px_digits)
                    if hard_sl_px > 0:
                        self.exchange.order(
                            hl_coin,
                            not is_buy,
                            size,
                            hard_sl_px,
                            {"trigger": {"triggerPx": hard_sl_px, "isMarket": True, "tpsl": "sl"}},
                            reduce_only=True,
                        )
                        add_log(f"🛡️ Hard Stop On-Chain L1 (-{hard_sl_dist*100:.2f}%) gravado na Hyperliquid para {coin} @ ${hard_sl_px}")
                except Exception as sl_err:
                    logger.debug(f"Aviso ao gravar Hard Stop L1 em {coin}: {sl_err}")

                send_mobile_alert(
                    f"⚡ NOVA ENTRADA: {new_side} ({lev}x) em {coin}",
                    f"🎯 Estratégia: {strategy_label} (Score {score:.1f})\n"
                    f"💵 Preço de Entrada: ${mid_px:.4f} | Lote: ~${notional:.2f} ({size} {coin})\n"
                    f"💰 Banca Atual: ${BOT_STATE['equity_usdc']:.2f} USDC (R$ {BOT_STATE['equity_brl']:.2f})",
                    priority="high",
                    tags="zap,chart_with_upwards_trend",
                )
                return True
            except Exception as e:
                add_log(f"❌ Erro ao abrir ordem em {coin}: {e}")
                return False

    def _cancel_coin_open_orders(self, coin: str, hl_c: str):
        try:
            open_ords = self.info.open_orders(self.account_address)
            if isinstance(open_ords, list):
                for o in open_ords:
                    if o.get("coin") in (coin, hl_c) and "oid" in o:
                        self.exchange.cancel(hl_c, int(o["oid"]))
        except Exception:
            pass

    def close_position(self, coin: str, is_loss: bool = False, side_closed: str = ""):
        with GATEWAY_LOCK:
            try:
                pos_snap = next((p for p in BOT_STATE.get("open_positions", []) if p.get("coin") == coin), None)
                est_pnl = float(pos_snap["pnl"]) if pos_snap else 0.0
                est_roe = float(pos_snap["roe_pct"]) if pos_snap else 0.0
                if not side_closed and pos_snap:
                    side_closed = str(pos_snap.get("side", ""))

                if BOT_STATE.get("paper_mode", True) and any(p.get("coin") == coin for p in BOT_STATE.get("paper_open_positions", [])):
                    now = time.time()
                    if (now - self.recent_closed_ts.get(coin, 0.0)) < 10.0:
                        return
                    self.recent_closed_ts[coin] = now
                    pp = next((p for p in BOT_STATE["paper_open_positions"] if p.get("coin") == coin), pos_snap)
                    pval = safe_float(pp.get("pos_val_usd", 15.0), 15.0)
                    fee_usd = round(pval * BOT_STATE["round_trip_fee_pct"], 4)
                    net_sim = round(est_pnl - fee_usd, 2)
                    net_sim_brl = round(net_sim * USD_BRL_RATE, 2)
                    BOT_STATE["paper_equity_usdc"] = round(BOT_STATE["paper_equity_usdc"] + net_sim, 2)
                    BOT_STATE["paper_realized_usdc"] = round(BOT_STATE["paper_realized_usdc"] + net_sim, 2)
                    if net_sim >= 0:
                        BOT_STATE["paper_wins"] += 1
                        res_lbl = "🧪 SIMULAÇÃO GREEN"
                    elif -0.045 <= net_sim < 0.0 and not is_loss:
                        res_lbl = "🛡️ SIMULAÇÃO 0x0 (TAXA)"
                    else:
                        BOT_STATE["paper_losses"] += 1
                        res_lbl = "🧪 SIMULAÇÃO RED"
                    dq_p = self.memory.price_tape.get(coin)
                    exit_px = float(dq_p[-1][1]) if (dq_p and len(dq_p) > 0) else safe_float(pp.get("entry_px", 0.0), 0.0)
                    BOT_STATE["paper_closed_trades"].insert(0, {
                        "time_str": time.strftime("%d/%m %H:%M:%S", time.gmtime(now)),
                        "coin": coin,
                        "result": res_lbl,
                        "px": exit_px,
                        "net_usdc": net_sim,
                        "net_brl": net_sim_brl,
                        "is_win": net_sim >= 0,
                        "is_scratch": (-0.045 <= net_sim < 0.0),
                    })
                    BOT_STATE["paper_closed_trades"] = BOT_STATE["paper_closed_trades"][:40]
                    p_map = BOT_STATE.get("coin_performance_map", {})
                    if coin not in p_map:
                        p_map[coin] = {"w": 0, "l": 0, "net": 0.0}
                    p_map[coin]["net"] = safe_float(p_map[coin].get("net", 0.0), 0.0) + net_sim
                    if net_sim >= 0:
                        p_map[coin]["w"] = int(p_map[coin].get("w", 0)) + 1
                    elif not (-0.045 <= net_sim < 0.0 and not is_loss):
                        p_map[coin]["l"] = int(p_map[coin].get("l", 0)) + 1
                    BOT_STATE["coin_performance_map"] = p_map
                    BOT_STATE["paper_open_positions"] = [p for p in BOT_STATE["paper_open_positions"] if p.get("coin") != coin]
                    BOT_STATE["open_positions"] = [p for p in BOT_STATE.get("open_positions", []) if p.get("coin") != coin]
                    self.cooldowns[coin] = now
                    if is_loss or net_sim < -0.045:
                        BOT_STATE["loss_quarantine_until"][coin] = now + 3600.0
                        BOT_STATE["global_any_lock_until"] = now + 360.0
                    BOT_STATE["peak_move_by_coin"].pop(coin, None)
                    BOT_STATE["worst_move_by_coin"].pop(coin, None)
                    BOT_STATE["partial_taken_by_coin"].pop(coin, None)
                    BOT_STATE["notified_step_by_coin"].pop(coin, None)
                    BOT_STATE["opened_ts_by_coin"].pop(coin, None)
                    self.memory.save_persisted_memory(force=True)
                    r_snap = BOT_STATE.get("radar", {}).get(coin, {})
                    QUANT_BRAIN.record_outcome({
                        "mode": "PAPER",
                        "coin": coin,
                        "side": side_closed or pp.get("side", ""),
                        "regime": r_snap.get("regime", "RANGING"),
                        "tactic": r_snap.get("signal", "SNIPER"),
                        "exit_arm": BOT_STATE.get("active_exit_arm_by_coin", {}).get(coin, "SWING_ATR"),
                        "kaufman_er": r_snap.get("kaufman_er", 0.3),
                        "band_pos": r_snap.get("band_pos", 0.5),
                        "rsi": r_snap.get("rsi", 50.0),
                        "l2_obi": r_snap.get("l2_obi", 0.0),
                        "shallow_obi": r_snap.get("shallow_obi", 0.0),
                        "microprice_dev": r_snap.get("microprice_dev_pct", 0.0),
                        "vel_1m": r_snap.get("vel_1m_pct", 0.0),
                        "btc_3m": BOT_STATE.get("market_brain", {}).get("btc_impulse_3m_pct", 0.0),
                        "net_usdc": net_sim,
                    })
                    _, db_cnt = QUANT_BRAIN.get_kelly_multiplier_and_count()
                    BOT_STATE["quant_db_count"] = db_cnt
                    pw = BOT_STATE["paper_wins"]
                    pl = BOT_STATE["paper_losses"]
                    pwr = (pw / max(1, pw + pl)) * 100.0
                    add_log(f"🧪 [SIMULAÇÃO] {coin} encerrada @ ${exit_px:.4f} | Líq: ${net_sim:+.2f} USDC (taxa ${fee_usd:.3f}) | Placar Sim: {pw}W/{pl}L")
                    send_mobile_alert(
                        f"🧪 [SIMULAÇÃO] {coin} FECHADA: ${net_sim:+.2f} USDC",
                        f"{res_lbl} ({est_roe:+.2f}% ROE | Taxa simulada: -${fee_usd:.3f})\n"
                        f"🏆 Placar Simulado: {pw}W x {pl}L ({pwr:.1f}%)\n"
                        f"🧪 Banca Simulada: ${BOT_STATE['paper_equity_usdc']:.2f} USDC (0 risco real!)",
                        priority="default",
                        tags="test_tube",
                    )
                    return

                hl_c = self._hl_coin(coin)

                now_close = time.time()
                # Verifica na L1 se a posição ainda existe antes de enviar fechamento no software
                onchain_szi = self.get_onchain_position_size(coin)
                if abs(onchain_szi) <= 0:
                    BOT_STATE["open_positions"] = [
                        p for p in BOT_STATE.get("open_positions", []) if p.get("coin") != coin
                    ]
                    self._cancel_coin_open_orders(coin, hl_c)
                    if (now_close - self.recent_closed_ts.get(coin, 0.0)) < 20.0:
                        return
                    self.recent_closed_ts[coin] = now_close
                    add_log(f"ℹ️ Reconciliação L1: Posição em {coin} já havia sido encerrada na blockchain.")
                    return

                self.recent_closed_ts[coin] = now_close
                res = None
                close_is_buy = onchain_szi < 0
                abs_sz = abs(onchain_szi)
                if not is_loss:
                    try:
                        l2_c = self.fetch_l2_metrics_cached(coin, max_ws_age_sec=2.0)
                        b_bid = safe_float(l2_c.get("best_bid", 0.0), 0.0)
                        b_ask = safe_float(l2_c.get("best_ask", 0.0), 0.0)
                        best_px = b_bid if close_is_buy else b_ask
                        if best_px > 0 and abs_sz > 0:
                            lim_res = self.exchange.order(
                                hl_c, close_is_buy, abs_sz, best_px, {"limit": {"tif": "Ioc"}}, reduce_only=True
                            )
                            if "filled" in str(lim_res).lower():
                                res = lim_res
                                add_log(f"💎 Saída Otimizada no Topo do Livro L2 em {coin} @ ${best_px}!")
                    except Exception:
                        pass

                # Verifica novamente na L1 se ainda restou saldo após tentativa Limit IOC
                rem_szi = self.get_onchain_position_size(coin) if res is not None else onchain_szi
                if abs(rem_szi) > 0:
                    res_mkt = self.exchange.market_close(hl_c)
                    if res is None:
                        res = res_mkt

                BOT_STATE["open_positions"] = [
                    p for p in BOT_STATE.get("open_positions", []) if p.get("coin") != coin
                ]
                self._cancel_coin_open_orders(coin, hl_c)

                now = time.time()
                self.cooldowns[coin] = now
                peak_mv_closed = safe_float(BOT_STATE.get("peak_move_by_coin", {}).get(coin, 0.0), 0.0)
                if coin not in BOT_STATE["coin_ai_brain"]:
                    BOT_STATE["coin_ai_brain"][coin] = {"harvest_mult": 1.0, "scratch_after_peak": 0}
                if (not is_loss) and est_pnl < 0.05 and peak_mv_closed >= 0.0017:
                    BOT_STATE["coin_ai_brain"][coin]["scratch_after_peak"] = int(BOT_STATE["coin_ai_brain"][coin].get("scratch_after_peak", 0)) + 1
                    cur_m = safe_float(BOT_STATE["coin_ai_brain"][coin].get("harvest_mult", 1.0), 1.0)
                    BOT_STATE["coin_ai_brain"][coin]["harvest_mult"] = round(max(0.76, cur_m * 0.88), 3)
                    add_log(
                        f"🧠 AUTO-APRENDIZADO IA em {coin}: Pico foi +{peak_mv_closed*800:.1f}% ROE -> "
                        f"Calibrando colheita automática p/ {BOT_STATE['coin_ai_brain'][coin]['harvest_mult']*100:.0f}%!"
                    )

                if is_loss:
                    BOT_STATE["loss_quarantine_until"][coin] = now + 3600.0
                    BOT_STATE["global_any_lock_until"] = now + 360.0
                    if side_closed == "LONG":
                        BOT_STATE["global_long_lock_until"] = now + 1200.0
                    elif side_closed == "SHORT":
                        BOT_STATE["global_short_lock_until"] = now + 1200.0
                elif est_pnl < 0.06:
                    BOT_STATE["loss_quarantine_until"][coin] = now + 600.0

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
                        f"✅ Lucro Líquido no Bolso: +${net_u:.2f} USDC (R$ +{net_b:.2f} | {est_roe:+.2f}% ROE)\n"
                        f"🏆 Placar On-Chain: {w_tot} Vitórias x {l_tot} Derrotas ({wr:.1f}%)\n"
                        f"💰 Banca Atual: ${BOT_STATE['equity_usdc']:.2f} USDC (R$ {BOT_STATE['equity_brl']:.2f})",
                        priority="high",
                        tags="trophy,money_with_wings",
                    )
                elif not is_loss and net_u >= -0.045:
                    send_mobile_alert(
                        f"🛡️ ZERO-A-ZERO PROTEGIDO EM {coin} (${net_u:+.2f} taxa)",
                        f"⚖️ Posição encerrada no preço de entrada em {coin} (Zero perda de gráfico, apenas ${abs(net_u):.2f} de taxa da corretora).\n"
                        f"🏆 Placar Mantido: {w_tot} Vitórias x {l_tot} Derrotas ({wr:.1f}%) | Banca: ${BOT_STATE['equity_usdc']:.2f} USDC",
                        priority="default",
                        tags="shield",
                    )
                else:
                    send_mobile_alert(
                        f"🛑 SAÍDA DE PROTEÇÃO (RED) EM {coin}: ${net_u:+.2f} USDC",
                        f"🛡️ Posição encerrada em {coin} ({net_u:+.2f} USDC / R$ {net_b:+.2f}).\n"
                        f"🧊 Moeda {coin} em quarentena por 60m + Disjuntor Geral (6m pausa + 20m na direção).\n"
                        f"🏆 Placar: {w_tot}W x {l_tot}L ({wr:.1f}%) | Banca: ${BOT_STATE['equity_usdc']:.2f} USDC",
                        priority="high",
                        tags="shield,warning",
                    )
            except Exception as e:
                add_log(f"❌ Erro ao encerrar {coin}: {e}")


GLOBAL_GATEWAY: HyperliquidDeFiGateway | None = None


# =========================================================================================
# 4. PAINEL WEB LEVE COM ATUALIZAÇÃO ASSÍNCRONA VIA FETCH (/api/state A CADA 2 SEGUNDOS)
# =========================================================================================
class SovereignWebServer(BaseHTTPRequestHandler):
    def do_GET(self):
        global GLOBAL_GATEWAY
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            BOT_STATE["logs"] = [mask_sensitive_hex(line) for line in list(LOG_BUFFER)]
            payload_state = dict(BOT_STATE)
            if payload_state.get("paper_mode", True):
                pw = int(payload_state.get("paper_wins", 0))
                pl = int(payload_state.get("paper_losses", 0))
                ptot = pw + pl
                preal = float(payload_state.get("paper_realized_usdc", 0.0))
                ptrades = payload_state.get("paper_closed_trades", [])
                w_vals = [float(t.get("net_usdc", 0.0)) for t in ptrades if float(t.get("net_usdc", 0.0)) >= 0]
                l_vals = [abs(float(t.get("net_usdc", 0.0))) for t in ptrades if float(t.get("net_usdc", 0.0)) < 0 and not t.get("is_scratch", False)]
                p_stats: dict[str, dict[str, float]] = {}
                for t in ptrades:
                    cs = str(t.get("coin", "?"))
                    nv = float(t.get("net_usdc", 0.0))
                    if cs not in p_stats:
                        p_stats[cs] = {"w": 0, "l": 0, "net": 0.0}
                    p_stats[cs]["net"] += nv
                    if nv >= 0:
                        p_stats[cs]["w"] += 1
                    elif not t.get("is_scratch", False):
                        p_stats[cs]["l"] += 1
                BOT_STATE["coin_performance_map"] = p_stats
                if p_stats:
                    s_coins = sorted(p_stats.items(), key=lambda x: x[1]["net"], reverse=True)
                    parts = [
                        f"{cn}: {int(st['w'])}W/{int(st['l'])}L ({int(round(st['w']/max(1, st['w']+st['l'])*100))}% | ${st['net']:+.2f})"
                        for cn, st in s_coins
                    ]
                    payload_state["top_coins_summary"] = " • ".join(parts)
                else:
                    payload_state["top_coins_summary"] = "Placar simulado zerado — aguardando o 1º trade!"
                goal_u = max(0.10, float(payload_state.get("daily_goal_usdc", 1.50)))
                payload_state["daily_progress_pct"] = round(max(0.0, min(100.0, (preal / goal_u) * 100.0)), 1)
                payload_state["avg_win_usdc"] = round(sum(w_vals) / len(w_vals), 2) if w_vals else 0.0
                payload_state["avg_loss_usdc"] = round(sum(l_vals) / len(l_vals), 2) if l_vals else 0.0
                payload_state["wins_total"] = pw
                payload_state["losses_total"] = pl
                payload_state["win_rate_pct"] = round((pw / ptot) * 100.0, 1) if ptot > 0 else 0.0
                payload_state["realized_profit_usdc"] = round(preal, 2)
                payload_state["realized_profit_brl"] = round(preal * USD_BRL_RATE, 2)
                payload_state["recent_closed_trades"] = ptrades
                payload_state["reset_mode_label"] = f"SIMULAÇÃO IA ({payload_state.get('quant_db_count', 0)} EXP NO SQLITE)"
            self.wfile.write(json.dumps(payload_state).encode("utf-8"))
            return

        if parsed.path == "/api/action":
            qs = parse_qs(parsed.query)
            cmd = qs.get("cmd", [""])[0]
            coin = qs.get("coin", [""])[0]
            if cmd == "toggle_bot":
                BOT_STATE["trading_enabled"] = not BOT_STATE["trading_enabled"]
                if BOT_STATE["trading_enabled"]:
                    RISK_SHIELD.reset_kill_switch()
                add_log(f"Operador alterou status do robô para: {'ATIVO' if BOT_STATE['trading_enabled'] else 'PAUSADO'}")
            elif cmd == "toggle_paper":
                BOT_STATE["paper_mode"] = not BOT_STATE.get("paper_mode", True)
                add_log(f"Operador alternou modo para: {'🧪 SIMULAÇÃO (0 RISCO REAL)' if BOT_STATE['paper_mode'] else '⚡ CONTA REAL L1'}")
            elif cmd == "reset_paper":
                RISK_SHIELD.reset_kill_switch()
                BOT_STATE["paper_equity_usdc"] = 20.00
                BOT_STATE["paper_wins"] = 0
                BOT_STATE["paper_losses"] = 0
                BOT_STATE["paper_realized_usdc"] = 0.0
                BOT_STATE["paper_closed_trades"] = []
                BOT_STATE["paper_open_positions"] = []
                add_log("🧪 Placar e banca da Simulação zerados para $20.00 USDC!")
            elif cmd == "test_alert":
                send_mobile_alert(
                    "🔔 TESTE DE ALERTA NO CELULAR — SNIPER HFT v72.0",
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
                RISK_SHIELD.reset_kill_switch()
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
            pos_rows = "<tr><td colspan='6' style='text-align:center;color:#94a3b8;padding:12px;'>Aguardando moeda tocar no EXTREMO REAL da banda (<=24% p/ LONG ou >=76% p/ SHORT) com vela + Microprice virando...</td></tr>"

        tier_rank_map = {
            "TRIGGER": 0,
            "PRE_TRIGGER": 1,
            "APPROACHING": 2,
            "WAIT": 3,
            "BLOCKED": 4,
            "COMPASS": 5,
        }
        sorted_radar = sorted(
            BOT_STATE["radar"].items(),
            key=lambda kv: (
                kv[0] in COMPASS_ONLY_COINS,
                tier_rank_map.get(str(kv[1].get("stage_tier", "WAIT")), 3),
                -safe_float(kv[1].get("score", 0.0), 0.0),
                safe_float(kv[1].get("dist_to_zone_pct", 50.0), 50.0),
            )
        )

        top_candidates_html = ""
        non_compass_list = [(c, d) for c, d in sorted_radar if c not in COMPASS_ONLY_COINS][:3]
        for rank_idx, (tc_sym, tc_r) in enumerate(non_compass_list, start=1):
            tc_score = safe_float(tc_r.get("score", 50.0), 50.0)
            tc_tier = str(tc_r.get("stage_tier", "WAIT"))
            tc_sig = str(tc_r.get("signal", "NEUTRO"))
            tc_bpct = int(safe_float(tc_r.get("band_pos", 0.5), 0.5) * 100)
            tc_obi = safe_float(tc_r.get("l2_obi", 0.0), 0.0)
            tc_dna = safe_float(tc_r.get("dna_rate_pct", 80.0), 80.0)
            tc_htf_ok = bool(tc_r.get("htf_ok", False))
            tc_dna_ok = bool(tc_r.get("dna_approved", True))
            tc_zone_ok = bool(tc_r.get("zone_ok", False))
            tc_book_ok = bool(tc_r.get("book_ok", False))

            if tc_tier == "TRIGGER":
                card_border = "#10b981" if "LONG" in tc_sig else "#ef4444"
                card_bg = "rgba(16,185,129,0.12)" if "LONG" in tc_sig else "rgba(239,68,68,0.12)"
                badge_bg = card_border
                badge_fg = "#060911"
                prox_pct = 100
            elif tc_tier == "PRE_TRIGGER":
                card_border = "#f59e0b"
                card_bg = "rgba(245,158,11,0.11)"
                badge_bg = "#f59e0b"
                badge_fg = "#060911"
                prox_pct = int(min(96, max(82, tc_score)))
            elif tc_tier == "APPROACHING":
                card_border = "#38bdf8"
                card_bg = "rgba(56,189,248,0.08)"
                badge_bg = "#0284c7"
                badge_fg = "#f8fafc"
                prox_pct = int(min(80, max(58, tc_score)))
            else:
                card_border = "#334155"
                card_bg = "#09101f"
                badge_bg = "#334155"
                badge_fg = "#cbd5e1"
                prox_pct = int(min(55, max(25, tc_score - 10)))

            p_htf_col = "#10b981" if tc_htf_ok else "#64748b"
            p_dna_col = "#10b981" if tc_dna_ok else "#ef4444"
            p_zon_col = "#10b981" if tc_zone_ok else ("#f59e0b" if tc_tier == "APPROACHING" else "#64748b")
            p_bok_col = "#10b981" if tc_book_ok else "#f59e0b"

            top_candidates_html += f"""
            <div style="background:{card_bg};border:1px solid {card_border};border-radius:8px;padding:9px 10px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                <div>
                  <span style="font-size:11px;color:#94a3b8;font-weight:bold;">#{rank_idx}</span>
                  <b style="font-size:14px;color:#f8fafc;margin-left:3px;">{tc_sym}</b>
                  <span style="font-size:11px;color:#94a3b8;margin-left:4px;">${safe_float(tc_r.get('price', 0.0)):.4f}</span>
                </div>
                <span style="background:{badge_bg};color:{badge_fg};padding:2px 7px;border-radius:4px;font-size:10.5px;font-weight:800;">
                  {tc_sig} ({tc_score:.1f})
                </span>
              </div>
              <div style="background:#1e293b;height:5px;border-radius:4px;width:100%;margin-bottom:6px;overflow:hidden;">
                <div style="background:{card_border};height:100%;width:{prox_pct}%;"></div>
              </div>
              <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:5px;font-size:10px;">
                <span style="background:#0f172a;border:1px solid {p_htf_col};color:{p_htf_col};padding:1px 5px;border-radius:4px;font-weight:bold;">{'✓' if tc_htf_ok else '⏳'} {tc_r.get('htf_15m', '15M')}</span>
                <span style="background:#0f172a;border:1px solid {p_dna_col};color:{p_dna_col};padding:1px 5px;border-radius:4px;font-weight:bold;">{'✓' if tc_dna_ok else '✗'} DNA {tc_dna:.0f}%</span>
                <span style="background:#0f172a;border:1px solid {p_zon_col};color:{p_zon_col};padding:1px 5px;border-radius:4px;font-weight:bold;">{'✓' if tc_zone_ok else '⏳'} Banda {tc_bpct}%</span>
                <span style="background:#0f172a;border:1px solid {p_bok_col};color:{p_bok_col};padding:1px 5px;border-radius:4px;font-weight:bold;">{'✓' if tc_book_ok else '⏳'} Book {tc_obi:+.2f}</span>
              </div>
              <div style="font-size:10.5px;color:#e2e8f0;line-height:1.3;">{tc_r.get('strategy', '')}</div>
            </div>"""

        radar_rows = ""
        for idx_row, (c_sym, r) in enumerate(sorted_radar, start=1):
            obi_val = safe_float(r.get("l2_obi", 0.0), 0.0)
            mpx_dev = safe_float(r.get("microprice_dev_pct", 0.0), 0.0)
            obi_col = "#10b981" if obi_val > 0 else ("#ef4444" if obi_val < 0 else "#94a3b8")
            sig_str = str(r.get("signal", "NEUTRO"))
            stage_tier = str(r.get("stage_tier", "WAIT"))
            sc_val = safe_float(r.get("score", 50.0), 50.0)
            b_pct = int(safe_float(r.get("band_pos", 0.5), 0.5) * 100)
            dna_val = safe_float(r.get("dna_rate_pct", 80.0), 80.0)

            if stage_tier == "TRIGGER":
                row_style = "background:rgba(16,185,129,0.13);border-left:4px solid #10b981;" if "LONG" in sig_str else "background:rgba(239,68,68,0.13);border-left:4px solid #ef4444;"
                badge_style = "background:#10b981;color:#060911;padding:3px 7px;border-radius:5px;font-weight:800;display:inline-block;" if "LONG" in sig_str else "background:#ef4444;color:#fff;padding:3px 7px;border-radius:5px;font-weight:800;display:inline-block;"
            elif stage_tier == "PRE_TRIGGER":
                row_style = "background:rgba(245,158,11,0.11);border-left:4px solid #f59e0b;"
                badge_style = "background:#f59e0b;color:#060911;padding:3px 7px;border-radius:5px;font-weight:800;display:inline-block;"
            elif stage_tier == "APPROACHING":
                row_style = "background:rgba(56,189,248,0.06);border-left:3px solid #38bdf8;"
                badge_style = "background:#0284c7;color:#f8fafc;padding:3px 7px;border-radius:5px;font-weight:700;display:inline-block;"
            elif stage_tier == "BLOCKED":
                row_style = "opacity:0.68;"
                badge_style = "background:#1e293b;color:#94a3b8;padding:2px 6px;border-radius:4px;font-weight:600;display:inline-block;"
            elif stage_tier == "COMPASS":
                row_style = "background:rgba(56,189,248,0.04);"
                badge_style = "background:#0f172a;border:1px solid #38bdf8;color:#38bdf8;padding:2px 6px;border-radius:4px;font-weight:700;display:inline-block;"
            else:
                row_style = ""
                badge_style = "background:#1e293b;color:#cbd5e1;padding:2px 6px;border-radius:4px;font-weight:600;display:inline-block;"

            bar_dot_col = "#10b981" if b_pct <= 18 else ("#ef4444" if b_pct >= 82 else "#38bdf8")
            htf_ok = bool(r.get("htf_ok", False))
            dna_ok = bool(r.get("dna_approved", True))
            zon_ok = bool(r.get("zone_ok", False))
            bok_ok = bool(r.get("book_ok", False))

            c_htf = "#10b981" if htf_ok else "#64748b"
            s_htf = "✓" if htf_ok else "⏳"
            c_dna = "#10b981" if dna_ok else "#ef4444"
            s_dna = "✓" if dna_ok else "✗"
            c_zon = "#10b981" if zon_ok else ("#f59e0b" if stage_tier == "APPROACHING" else "#64748b")
            s_zon = "✓" if zon_ok else "⏳"
            c_bok = "#10b981" if bok_ok else "#f59e0b"
            s_bok = "✓" if bok_ok else "⏳"
            chk_pills = (
                f"<span style='color:{c_htf};font-weight:bold;'>15M:{s_htf}</span> • "
                f"<span style='color:{c_dna};font-weight:bold;'>DNA:{s_dna}</span> • "
                f"<span style='color:{c_zon};font-weight:bold;'>Zona:{s_zon}</span> • "
                f"<span style='color:{c_bok};font-weight:bold;'>Book:{s_bok}</span>"
            )

            rank_tag = "🧭" if c_sym in COMPASS_ONLY_COINS else f"<span style='color:#64748b;font-size:10px;'>#{idx_row}</span>"
            radar_rows += f"""
            <tr style="{row_style}">
                <td>{rank_tag} <b>{c_sym}</b></td>
                <td>${safe_float(r.get('price', 0.0)):.4f}<br><span style="font-size:10.5px;color:#64748b;">VWAP ${safe_float(r.get('vwap', 0.0)):.4f}</span></td>
                <td>
                    RSI {safe_float(r.get('rsi', 50.0)):.1f} <b>(Banda {b_pct}%)</b>
                    <div style="background:#1e293b;height:5px;border-radius:3px;width:100%;margin:3px 0;position:relative;overflow:hidden;">
                        <div style="background:{bar_dot_col};height:100%;width:{max(4, min(100, b_pct))}%;"></div>
                    </div>
                    <span style="font-size:10.5px;color:#38bdf8;">Espaço: +{safe_float(r.get('room_pct', 0.0)):.2f}% | 🧬 DNA: {dna_val:.0f}%</span>
                </td>
                <td style="color:{obi_col};font-weight:bold;">Book {obi_val:+.2f} <span style="font-size:10px;color:#cbd5e1;">(MPx {mpx_dev:+.3f}%)</span><br><span style="font-size:10.5px;color:#94a3b8;">Vel: {safe_float(r.get('vel_1m_pct', 0.0)):+.3f}%/m</span></td>
                <td>
                    {r.get('trend', 'NEUTRO')}<br>
                    <span style="font-size:10.5px;color:#e2e8f0;">{r.get('strategy', '')}</span><br>
                    <span style="font-size:10px;">{chk_pills}</span>
                </td>
                <td><span style="{badge_style}">{sig_str} ({sc_val:.1f})</span></td>
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
        logs_txt = "\n".join(mask_sensitive_hex(line) for line in LOG_BUFFER)

        html = f"""<!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="utf-8">
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
              <h2 id="hud-version" style="margin:0;font-size:15px;color:#10b981;">🎯 {BOT_STATE['version']}</h2>
              <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
                <a href="/api/action?cmd=reset_stats" style="background:#ef4444;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🆕 Zerar Placar &amp; Histórico (0x0)</a>
                <a href="/api/action?cmd=era_v30" style="background:#8b5cf6;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">💎 Só Era v30</a>
                <a href="/api/action?cmd=test_alert" style="background:#10b981;color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🔔 Testar Aviso</a>
                <a href="/api/action?cmd=clear_quarantine" style="background:#38bdf8;color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🔓 Limpar Quarentenas</a>
                <a id="btn-toggle-paper" href="/api/action?cmd=toggle_paper" style="background:{'#38bdf8' if BOT_STATE.get('paper_mode', True) else '#ef4444'};color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">{'🧪 MODO SIMULAÇÃO ATIVO (0 RISCO)' if BOT_STATE.get('paper_mode', True) else '🔴 CONTA REAL L1 ATIVA'}</a>
                <a href="/api/action?cmd=reset_paper" style="background:#64748b;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">🔄 Zerar Simulação</a>
                <a id="btn-toggle-bot" href="/api/action?cmd=toggle_bot" style="background:#f59e0b;color:#060911;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">{'⏸️ Pausar Novas Entradas' if BOT_STATE['trading_enabled'] else '▶️ Retomar Entradas'}</a>
              </div>
              <div style="font-size:11px;color:#94a3b8;margin-top:6px;">
                Status: <b id="hud-status" style="color:#10b981;">{BOT_STATE['status']}</b> | Atualizado: <span id="hud-last-update">{BOT_STATE['last_update']}</span> | App <b>ntfy</b> no Celular: <code>{BOT_STATE['ntfy_topic']}</code>
              </div>
            </div>
          </div>
        </div>

        <div class="kpi-grid">
          <div class="kpi-box" style="border-color:#38bdf8;">
            <div class="kpi-title">💰 Quanto a Banca Está Agora</div>
            <div id="kpi-equity-usd" class="kpi-big" style="color:#38bdf8;">${BOT_STATE['equity_usdc']:.2f} USDC</div>
            <div id="kpi-equity-sub" class="kpi-sub">≈ <b>R$ {BOT_STATE['equity_brl']:.2f}</b> | Em Uso: ${BOT_STATE['margin_used_usdc']:.2f} | Livre: <b style="color:#10b981;">${BOT_STATE['free_margin_usdc']:.2f}</b></div>
          </div>

          <div class="kpi-box" style="border-color:#10b981;">
            <div class="kpi-title">🏆 Placar de Vitórias x Derrotas</div>
            <div id="kpi-score-big" class="kpi-big">
              <span style="color:#10b981;">{BOT_STATE['wins_total']} Vitórias</span>
              <span style="color:#64748b;font-size:15px;"> x </span>
              <span style="color:#ef4444;">{BOT_STATE['losses_total']} Derrotas</span>
            </div>
            <div id="kpi-score-sub" class="kpi-sub">Acerto: <b style="color:#10b981;">{BOT_STATE['win_rate_pct']:.1f}%</b> | Média W: <b style="color:#10b981;">+${BOT_STATE['avg_win_usdc']:.2f}</b> vs L: <b style="color:#ef4444;">-${BOT_STATE['avg_loss_usdc']:.2f}</b></div>
          </div>

          <div id="kpi-pnl-box" class="kpi-box" style="border-color:{pnl_col};">
            <div class="kpi-title">💵 Quanto Ganhamos (Realizado + Aberto)</div>
            <div id="kpi-pnl-big" class="kpi-big" style="color:{pnl_col};">${realized_u:+.2f} USDC <span style="font-size:14px;">(R$ {realized_b:+.2f})</span></div>
            <div id="kpi-pnl-sub" class="kpi-sub">Em Aberto Agora: <b style="color:{fl_col};">${float_u:+.2f} (R$ {float_b:+.2f})</b> | 24h: <b>${BOT_STATE['realized_24h_usdc']:+.2f}</b></div>
          </div>

          <div class="kpi-box" style="border-color:#8b5cf6;">
            <div class="kpi-title">🛡️ Extremo Real &amp; Greens Cheios</div>
            <div id="kpi-notional-big" class="kpi-big" style="color:#f59e0b;">${BOT_STATE['order_notional']:.2f} <span style="font-size:13px;color:#94a3b8;">({BOT_STATE['leverage']}x)</span></div>
            <div id="kpi-notional-sub" class="kpi-sub">Trava 0x0: <b>+0.095%</b> | Alvo: <b>+{BOT_STATE['cash_in_band_move_pct']*100:.2f}%+</b> | Soft SL: <b>-0.12%</b> (L1 -0.28%)</div>
          </div>
        </div>

        <!-- PAINEL DO CÉREBRO GLOBAL -->
        <div id="market-brain-card" class="card" style="border-color:{reg_col};background:#09101f;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:6px;">
            <h3 id="mb-regime" style="margin:0;font-size:13.5px;color:{reg_col};">🌐 {mb.get('regime', 'MAPEANDO...')}</h3>
            <span style="font-size:11px;background:#1e293b;padding:4px 8px;border-radius:5px;color:#e2e8f0;">
              Regra: <b id="mb-allowed-dir">{mb.get('allowed_direction', 'EXTREMO REAL')}</b>
            </span>
          </div>
          <div id="mb-details" style="font-size:12px;color:#cbd5e1;">
            📊 <b>Tendência 15m Intacta ({len(GLOBAL_BASKET)} Moedas):</b> <span style="color:#10b981;font-weight:bold;">{mb.get('breadth_bull_pct', 50):.0f}% em Alta 15m</span> vs <span style="color:#ef4444;font-weight:bold;">{mb.get('breadth_bear_pct', 50):.0f}% em Baixa 15m</span>
            &nbsp;|&nbsp; ⚡ <b>BTC 3m (Bússola):</b> <b>{mb.get('btc_impulse_3m_pct', 0.0):+.2f}%</b> • <b>ETH 3m:</b> <b>{mb.get('eth_impulse_3m_pct', 0.0):+.2f}%</b><br>
            🛡️ <b>Modo Foco Único:</b> <b style="color:#38bdf8;">{mb.get('second_slot_status', 'ATIVO')}</b> &nbsp;|&nbsp; 🌐 <b>Sessão Ativa:</b> <b style="color:#10b981;">{BOT_STATE.get('active_session_mode', 'AUTOMÁTICA')}</b> &nbsp;|&nbsp; 🔒 <b>Cofre Diário:</b> <b style="color:{'#10b981' if BOT_STATE.get('daily_vault_active') else '#94a3b8'};">{'META BATIDA (SÓ SCORE >=95)' if BOT_STATE.get('daily_vault_active') else 'CAÇANDO META DO DIA'}</b>
          </div>
        </div>

        <div class="card"><h3 style="margin-top:0;font-size:13.5px;color:#38bdf8;">🎯 POSIÇÃO PERPÉTUA ATIVA (ALVO BANDA OPOSTA • SOFT SL -0.12% • HARD STOP L1 -0.28%)</h3>
        <table><thead><tr><th>Ativo</th><th>Lado</th><th>Qtd (Valor)</th><th>Entrada</th><th>Lucro Aberto / ROE &amp; Escudo</th><th>Ação</th></tr></thead><tbody id="open-positions-tbody">{pos_rows}</tbody></table></div>

        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
            <h3 id="hist-title" style="margin:0;font-size:13.5px;color:#10b981;">📊 HISTÓRICO DO CICLO ATUAL ({BOT_STATE.get('reset_mode_label', 'ERA OMEGA v30+')})</h3>
            <span id="hist-goal-badge" style="font-size:11px;background:#1e293b;padding:4px 8px;border-radius:5px;color:#38bdf8;">
              🎯 <b>Meta do Ciclo (+${BOT_STATE.get('daily_goal_usdc', 1.50):.2f} USDC):</b> <b style="color:#10b981;">{BOT_STATE.get('daily_progress_pct', 0.0):.1f}% Concluída</b>
            </span>
          </div>
          <div style="background:#1e293b;border-radius:6px;height:8px;width:100%;margin-bottom:8px;overflow:hidden;">
            <div id="hist-progress-bar" style="background:linear-gradient(90deg,#10b981,#38bdf8);height:100%;width:{BOT_STATE.get('daily_progress_pct', 0.0)}%;"></div>
          </div>
          <div style="font-size:11.5px;color:#cbd5e1;margin-bottom:10px;">
            🏅 <b>Taxa de Vitória/Derrota por Moeda neste Ciclo:</b> <span id="hist-top-coins" style="color:#a78bfa;font-weight:bold;">{BOT_STATE.get('top_coins_summary', '')}</span>
          </div>
          <table><thead><tr><th>Data / Hora (UTC)</th><th>Moeda</th><th>Resultado</th><th>Preço Saída</th><th>Lucro / Prejuízo Líquido</th></tr></thead><tbody id="history-tbody">{hist_rows}</tbody></table>
        </div>

        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
            <h3 style="margin:0;font-size:13.5px;color:#f59e0b;">🔥 NA MIRA DO SNIPER — TOP 3 MOEDAS MAIS PRÓXIMAS DE ENTRAR AGORA</h3>
            <span style="font-size:10.5px;color:#94a3b8;">Atualização em tempo real (2s via fetch sem reload)</span>
          </div>
          <div id="top-candidates-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px;">
            {top_candidates_html}
          </div>
          <h3 style="margin-top:4px;margin-bottom:6px;font-size:13.5px;color:#a78bfa;">📡 RADAR SNIPER HFT v72 (WEBSOCKET + MICROPRICE • BTC = BÚSSOLA)</h3>
          <table><thead><tr><th># Ativo</th><th>Preço &amp; VWAP</th><th>RSI &amp; Barra da Banda</th><th>Fluxo L2, Microprice &amp; Kalman</th><th>Tendência, Checklist &amp; O Que Falta</th><th>Status &amp; Score</th></tr></thead><tbody id="radar-tbody">{radar_rows}</tbody></table>
        </div>

        <div class="card"><h3 style="margin-top:0;font-size:13.5px;color:#94a3b8;">📜 LOGS DE EXECUÇÃO ON-CHAIN (CHAVES MASCARADAS)</h3><pre id="logs-pre">{logs_txt}</pre></div>

        <script>
        const USD_BRL_RATE = {USD_BRL_RATE};
        const COMPASS_COINS = new Set(["BTC"]);
        const TIER_RANK = {{ TRIGGER: 0, PRE_TRIGGER: 1, APPROACHING: 2, WAIT: 3, BLOCKED: 4, COMPASS: 5 }};

        function fmtSigned(val, dec = 2, prefix = "") {{
            const n = Number(val) || 0;
            const sign = n >= 0 ? "+" : "-";
            return sign + prefix + Math.abs(n).toFixed(dec);
        }}

        async function refreshSniperDashboard() {{
            try {{
                const res = await fetch("/api/state", {{ cache: "no-store" }});
                if (!res.ok) return;
                const st = await res.json();

                document.getElementById("hud-status").textContent = st.status || "";
                document.getElementById("hud-last-update").textContent = st.last_update || "";
                const btnToggle = document.getElementById("btn-toggle-bot");
                if (btnToggle) {{
                    btnToggle.textContent = st.trading_enabled ? "⏸️ Pausar Novas Entradas" : "▶️ Retomar Entradas";
                }}
                const btnPaper = document.getElementById("btn-toggle-paper");
                if (btnPaper) {{
                    btnPaper.textContent = st.paper_mode ? "🧪 MODO SIMULAÇÃO ATIVO (0 RISCO)" : "🔴 CONTA REAL L1 ATIVA";
                    btnPaper.style.background = st.paper_mode ? "#38bdf8" : "#ef4444";
                }}

                document.getElementById("kpi-equity-usd").textContent = `$${{Number(st.equity_usdc || 0).toFixed(2)}} USDC`;
                document.getElementById("kpi-equity-sub").innerHTML =
                    `≈ <b>R$ ${{Number(st.equity_brl || 0).toFixed(2)}}</b> | Em Uso: $${{Number(st.margin_used_usdc || 0).toFixed(2)}} | Livre: <b style="color:#10b981;">$${{Number(st.free_margin_usdc || 0).toFixed(2)}}</b>`;

                document.getElementById("kpi-score-big").innerHTML =
                    `<span style="color:#10b981;">${{st.wins_total || 0}} Vitórias</span><span style="color:#64748b;font-size:15px;"> x </span><span style="color:#ef4444;">${{st.losses_total || 0}} Derrotas</span>`;
                document.getElementById("kpi-score-sub").innerHTML =
                    `Acerto: <b style="color:#10b981;">${{Number(st.win_rate_pct || 0).toFixed(1)}}%</b> | Média W: <b style="color:#10b981;">+$${{Number(st.avg_win_usdc || 0).toFixed(2)}}</b> vs L: <b style="color:#ef4444;">-$${{Number(st.avg_loss_usdc || 0).toFixed(2)}}</b>`;

                const realU = Number(st.realized_profit_usdc || 0);
                const realB = Number(st.realized_profit_brl || 0);
                const fltU = Number(st.floating_pnl_usdc || 0);
                const fltB = fltU * USD_BRL_RATE;
                const pnlCol = realU >= 0 ? "#10b981" : "#ef4444";
                const fltCol = fltU >= 0 ? "#10b981" : "#ef4444";

                const pnlBox = document.getElementById("kpi-pnl-box");
                if (pnlBox) pnlBox.style.borderColor = pnlCol;
                const pnlBig = document.getElementById("kpi-pnl-big");
                if (pnlBig) {{
                    pnlBig.style.color = pnlCol;
                    pnlBig.innerHTML = `${{fmtSigned(realU, 2, "$")}} USDC <span style="font-size:14px;">(R$ ${{fmtSigned(realB, 2)}})</span>`;
                }}
                document.getElementById("kpi-pnl-sub").innerHTML =
                    `Em Aberto Agora: <b style="color:${{fltCol}};">${{fmtSigned(fltU, 2, "$")}} (R$ ${{fmtSigned(fltB, 2)}})</b> | 24h: <b>${{fmtSigned(st.realized_24h_usdc || 0, 2, "$")}}</b>`;

                document.getElementById("kpi-notional-big").innerHTML =
                    `$${{Number(st.order_notional || 15).toFixed(2)}} <span style="font-size:13px;color:#94a3b8;">(${{st.leverage || 8}}x)</span>`;
                document.getElementById("kpi-notional-sub").innerHTML =
                    `Trava 0x0: <b>+0.095%</b> | Alvo: <b>+${{(Number(st.cash_in_band_move_pct || 0.0028) * 100).toFixed(2)}}%+</b> | Soft SL: <b>-0.12%</b> (L1 -0.28%)`;

                const mb = st.market_brain || {{}};
                const regCol = mb.regime_color || "#10b981";
                const mbCard = document.getElementById("market-brain-card");
                if (mbCard) mbCard.style.borderColor = regCol;
                const mbReg = document.getElementById("mb-regime");
                if (mbReg) {{
                    mbReg.style.color = regCol;
                    mbReg.textContent = `🌐 ${{mb.regime || "MAPEANDO..."}}`;
                }}
                document.getElementById("mb-allowed-dir").textContent = mb.allowed_direction || "";
                document.getElementById("mb-details").innerHTML =
                    `📊 <b>Tendência 15m Intacta (${{mb.coins_tracked || 19}} Moedas):</b> <span style="color:#10b981;font-weight:bold;">${{Number(mb.breadth_bull_pct || 50).toFixed(0)}}% em Alta 15m</span> vs <span style="color:#ef4444;font-weight:bold;">${{Number(mb.breadth_bear_pct || 50).toFixed(0)}}% em Baixa 15m</span>` +
                    ` &nbsp;|&nbsp; ⚡ <b>BTC 3m (Bússola):</b> <b>${{fmtSigned(mb.btc_impulse_3m_pct || 0, 2)}}%</b> • <b>ETH 3m:</b> <b>${{fmtSigned(mb.eth_impulse_3m_pct || 0, 2)}}%</b><br>` +
                    `🛡️ <b>Modo Foco Único:</b> <b style="color:#38bdf8;">${{mb.second_slot_status || "ATIVO"}}</b> &nbsp;|&nbsp; 🌐 <b>Sessão Ativa:</b> <b style="color:#10b981;">${{st.active_session_mode || "AUTOMÁTICA"}}</b> &nbsp;|&nbsp; 🔒 <b>Cofre Diário:</b> <b style="color:${{st.daily_vault_active ? "#10b981" : "#94a3b8"}};">${{st.daily_vault_active ? "META BATIDA (SÓ SCORE >=95)" : "CAÇANDO META DO DIA"}}</b>`;

                // Posições Abertas
                const openPos = st.open_positions || [];
                const posTbody = document.getElementById("open-positions-tbody");
                if (openPos.length === 0) {{
                    posTbody.innerHTML = "<tr><td colspan='6' style='text-align:center;color:#94a3b8;padding:12px;'>Aguardando moeda tocar no EXTREMO REAL da banda (<=24% p/ LONG ou >=76% p/ SHORT) com vela + Microprice virando...</td></tr>";
                }} else {{
                    posTbody.innerHTML = openPos.map(p => {{
                        const cCol = p.pnl >= 0 ? "#10b981" : "#ef4444";
                        const sCol = p.side === "LONG" ? "#10b981" : "#ef4444";
                        return `<tr>
                            <td><b>${{p.coin}}</b> <span style="color:#94a3b8;font-size:11px;">(${{Number(p.eff_lev || 8).toFixed(0)}}x)</span></td>
                            <td style="color:${{sCol}};font-weight:bold;">${{p.side}}</td>
                            <td>${{p.size}} <span style="color:#94a3b8;font-size:11px;">($${{Number(p.pos_val_usd || 0).toFixed(2)}})</span></td>
                            <td>$${{Number(p.entry_px || 0).toFixed(4)}}</td>
                            <td style="color:${{cCol}};font-weight:bold;">
                                ${{fmtSigned(p.pnl, 4, "$")}} (${{fmtSigned(p.roe_pct, 2)}}% ROE)<br>
                                <span style="font-size:11px;color:#fbbf24;">${{p.shield_tag || ""}}</span>
                            </td>
                            <td><a href="/api/action?cmd=close&coin=${{p.coin}}" style="background:#ef4444;color:#fff;padding:5px 10px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold;">Fechar L1</a></td>
                        </tr>`;
                    }}).join("");
                }}

                // Histórico do Ciclo
                document.getElementById("hist-title").textContent = `📊 HISTÓRICO DO CICLO ATUAL (${{st.reset_mode_label || "ERA OMEGA v30+"}})`;
                document.getElementById("hist-goal-badge").innerHTML =
                    `🎯 <b>Meta do Ciclo (+$${{Number(st.daily_goal_usdc || 1.5).toFixed(2)}} USDC):</b> <b style="color:#10b981;">${{Number(st.daily_progress_pct || 0).toFixed(1)}}% Concluída</b>`;
                document.getElementById("hist-progress-bar").style.width = `${{Number(st.daily_progress_pct || 0)}}%`;
                document.getElementById("hist-top-coins").textContent = st.top_coins_summary || "";

                const histList = st.recent_closed_trades || [];
                const histTbody = document.getElementById("history-tbody");
                if (histList.length === 0) {{
                    histTbody.innerHTML = "<tr><td colspan='5' style='text-align:center;color:#94a3b8;padding:10px;'>Sincronizando histórico de trades da blockchain...</td></tr>";
                }} else {{
                    histTbody.innerHTML = histList.map(h => {{
                        const hCol = h.is_win ? "#10b981" : (h.is_scratch ? "#38bdf8" : "#ef4444");
                        return `<tr>
                            <td>${{h.time_str}}</td>
                            <td><b>${{h.coin}}</b></td>
                            <td style="color:${{hCol}};font-weight:bold;">${{h.result}}</td>
                            <td>$${{Number(h.px || 0).toFixed(4)}}</td>
                            <td style="color:${{hCol}};font-weight:bold;">${{fmtSigned(h.net_usdc, 2, "$")}} USDC (R$ ${{fmtSigned(h.net_brl, 2)}})</td>
                        </tr>`;
                    }}).join("");
                }}

                // Ordenação do Radar e Top-3 Cards
                const radarEntries = Object.entries(st.radar || {{}}).sort((a, b) => {{
                    const aComp = COMPASS_COINS.has(a[0]) ? 1 : 0;
                    const bComp = COMPASS_COINS.has(b[0]) ? 1 : 0;
                    if (aComp !== bComp) return aComp - bComp;
                    const aTier = TIER_RANK[a[1].stage_tier || "WAIT"] ?? 3;
                    const bTier = TIER_RANK[b[1].stage_tier || "WAIT"] ?? 3;
                    if (aTier !== bTier) return aTier - bTier;
                    const scDiff = (Number(b[1].score) || 0) - (Number(a[1].score) || 0);
                    if (Math.abs(scDiff) > 1e-5) return scDiff;
                    return (Number(a[1].dist_to_zone_pct) || 50) - (Number(b[1].dist_to_zone_pct) || 50);
                }});

                const top3 = radarEntries.filter(([c]) => !COMPASS_COINS.has(c)).slice(0, 3);
                document.getElementById("top-candidates-grid").innerHTML = top3.map(([sym, r], idx) => {{
                    const sc = Number(r.score || 50);
                    const tier = r.stage_tier || "WAIT";
                    const sig = r.signal || "NEUTRO";
                    const bpct = Math.round(Number(r.band_pos || 0.5) * 100);
                    const obi = Number(r.l2_obi || 0);
                    const dna = Number(r.dna_rate_pct || 80);
                    let border = "#334155", bg = "#09101f", bBg = "#334155", bFg = "#cbd5e1", prox = Math.min(55, Math.max(25, Math.round(sc - 10)));
                    if (tier === "TRIGGER") {{
                        border = sig.includes("LONG") ? "#10b981" : "#ef4444";
                        bg = sig.includes("LONG") ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)";
                        bBg = border; bFg = "#060911"; prox = 100;
                    }} else if (tier === "PRE_TRIGGER") {{
                        border = "#f59e0b"; bg = "rgba(245,158,11,0.11)"; bBg = "#f59e0b"; bFg = "#060911";
                        prox = Math.min(96, Math.max(82, Math.round(sc)));
                    }} else if (tier === "APPROACHING") {{
                        border = "#38bdf8"; bg = "rgba(56,189,248,0.08)"; bBg = "#0284c7"; bFg = "#f8fafc";
                        prox = Math.min(80, Math.max(58, Math.round(sc)));
                    }}
                    const cHtf = r.htf_ok ? "#10b981" : "#64748b";
                    const cDna = r.dna_approved ? "#10b981" : "#ef4444";
                    const cZon = r.zone_ok ? "#10b981" : (tier === "APPROACHING" ? "#f59e0b" : "#64748b");
                    const cBok = r.book_ok ? "#10b981" : "#f59e0b";
                    return `<div style="background:${{bg}};border:1px solid ${{border}};border-radius:8px;padding:9px 10px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                            <div>
                                <span style="font-size:11px;color:#94a3b8;font-weight:bold;">#${{idx + 1}}</span>
                                <b style="font-size:14px;color:#f8fafc;margin-left:3px;">${{sym}}</b>
                                <span style="font-size:11px;color:#94a3b8;margin-left:4px;">$${{Number(r.price || 0).toFixed(4)}}</span>
                            </div>
                            <span style="background:${{bBg}};color:${{bFg}};padding:2px 7px;border-radius:4px;font-size:10.5px;font-weight:800;">${{sig}} (${{sc.toFixed(1)}})</span>
                        </div>
                        <div style="background:#1e293b;height:5px;border-radius:4px;width:100%;margin-bottom:6px;overflow:hidden;">
                            <div style="background:${{border}};height:100%;width:${{prox}}%;"></div>
                        </div>
                        <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:5px;font-size:10px;">
                            <span style="background:#0f172a;border:1px solid ${{cHtf}};color:${{cHtf}};padding:1px 5px;border-radius:4px;font-weight:bold;">${{r.htf_ok ? "✓" : "⏳"}} ${{r.htf_15m || "15M"}}</span>
                            <span style="background:#0f172a;border:1px solid ${{cDna}};color:${{cDna}};padding:1px 5px;border-radius:4px;font-weight:bold;">${{r.dna_approved ? "✓" : "✗"}} DNA ${{dna.toFixed(0)}}%</span>
                            <span style="background:#0f172a;border:1px solid ${{cZon}};color:${{cZon}};padding:1px 5px;border-radius:4px;font-weight:bold;">${{r.zone_ok ? "✓" : "⏳"}} Banda ${{bpct}}%</span>
                            <span style="background:#0f172a;border:1px solid ${{cBok}};color:${{cBok}};padding:1px 5px;border-radius:4px;font-weight:bold;">${{r.book_ok ? "✓" : "⏳"}} Book ${{fmtSigned(obi, 2)}}</span>
                        </div>
                        <div style="font-size:10.5px;color:#e2e8f0;line-height:1.3;">${{r.strategy || ""}}</div>
                    </div>`;
                }}).join("");

                document.getElementById("radar-tbody").innerHTML = radarEntries.map(([sym, r], idx) => {{
                    const obi = Number(r.l2_obi || 0);
                    const mpx = Number(r.microprice_dev_pct || 0);
                    const obiCol = obi > 0 ? "#10b981" : (obi < 0 ? "#ef4444" : "#94a3b8");
                    const sig = r.signal || "NEUTRO";
                    const tier = r.stage_tier || "WAIT";
                    const sc = Number(r.score || 50);
                    const bpct = Math.round(Number(r.band_pos || 0.5) * 100);
                    const dna = Number(r.dna_rate_pct || 80);
                    let rowStyle = "", badgeStyle = "background:#1e293b;color:#cbd5e1;padding:2px 6px;border-radius:4px;font-weight:600;display:inline-block;";
                    if (tier === "TRIGGER") {{
                        rowStyle = sig.includes("LONG") ? "background:rgba(16,185,129,0.13);border-left:4px solid #10b981;" : "background:rgba(239,68,68,0.13);border-left:4px solid #ef4444;";
                        badgeStyle = sig.includes("LONG") ? "background:#10b981;color:#060911;padding:3px 7px;border-radius:5px;font-weight:800;display:inline-block;" : "background:#ef4444;color:#fff;padding:3px 7px;border-radius:5px;font-weight:800;display:inline-block;";
                    }} else if (tier === "PRE_TRIGGER") {{
                        rowStyle = "background:rgba(245,158,11,0.11);border-left:4px solid #f59e0b;";
                        badgeStyle = "background:#f59e0b;color:#060911;padding:3px 7px;border-radius:5px;font-weight:800;display:inline-block;";
                    }} else if (tier === "APPROACHING") {{
                        rowStyle = "background:rgba(56,189,248,0.06);border-left:3px solid #38bdf8;";
                        badgeStyle = "background:#0284c7;color:#f8fafc;padding:3px 7px;border-radius:5px;font-weight:700;display:inline-block;";
                    }} else if (tier === "BLOCKED") {{
                        rowStyle = "opacity:0.68;";
                        badgeStyle = "background:#1e293b;color:#94a3b8;padding:2px 6px;border-radius:4px;font-weight:600;display:inline-block;";
                    }} else if (tier === "COMPASS") {{
                        rowStyle = "background:rgba(56,189,248,0.04);";
                        badgeStyle = "background:#0f172a;border:1px solid #38bdf8;color:#38bdf8;padding:2px 6px;border-radius:4px;font-weight:700;display:inline-block;";
                    }}
                    const barCol = bpct <= 18 ? "#10b981" : (bpct >= 82 ? "#ef4444" : "#38bdf8");
                    const cHtf = r.htf_ok ? "#10b981" : "#64748b";
                    const cDna = r.dna_approved ? "#10b981" : "#ef4444";
                    const cZon = r.zone_ok ? "#10b981" : (tier === "APPROACHING" ? "#f59e0b" : "#64748b");
                    const cBok = r.book_ok ? "#10b981" : "#f59e0b";
                    const chkPills = `<span style="color:${{cHtf}};font-weight:bold;">15M:${{r.htf_ok ? "✓" : "⏳"}}</span> • <span style="color:${{cDna}};font-weight:bold;">DNA:${{r.dna_approved ? "✓" : "✗"}}</span> • <span style="color:${{cZon}};font-weight:bold;">Zona:${{r.zone_ok ? "✓" : "⏳"}}</span> • <span style="color:${{cBok}};font-weight:bold;">Book:${{r.book_ok ? "✓" : "⏳"}}</span>`;
                    const rankTag = COMPASS_COINS.has(sym) ? "🧭" : `<span style="color:#64748b;font-size:10px;">#${{idx + 1}}</span>`;
                    return `<tr style="${{rowStyle}}">
                        <td>${{rankTag}} <b>${{sym}}</b></td>
                        <td>$${{Number(r.price || 0).toFixed(4)}}<br><span style="font-size:10.5px;color:#64748b;">VWAP $${{Number(r.vwap || 0).toFixed(4)}}</span></td>
                        <td>
                            RSI ${{Number(r.rsi || 50).toFixed(1)}} <b>(Banda ${{bpct}}%)</b>
                            <div style="background:#1e293b;height:5px;border-radius:3px;width:100%;margin:3px 0;position:relative;overflow:hidden;">
                                <div style="background:${{barCol}};height:100%;width:${{Math.max(4, Math.min(100, bpct))}}%;"></div>
                            </div>
                            <span style="font-size:10.5px;color:#38bdf8;">Espaço: +${{Number(r.room_pct || 0).toFixed(2)}}% | 🧬 DNA: ${{dna.toFixed(0)}}%</span>
                        </td>
                        <td style="color:${{obiCol}};font-weight:bold;">Book ${{fmtSigned(obi, 2)}} <span style="font-size:10px;color:#cbd5e1;">(MPx ${{fmtSigned(mpx, 3)}}%)</span><br><span style="font-size:10.5px;color:#94a3b8;">Vel: ${{fmtSigned(r.vel_1m_pct || 0, 3)}}%/m</span></td>
                        <td>
                            ${{r.trend || "NEUTRO"}}<br>
                            <span style="font-size:10.5px;color:#e2e8f0;">${{r.strategy || ""}}</span><br>
                            <span style="font-size:10px;">${{chkPills}}</span>
                        </td>
                        <td><span style="${{badgeStyle}}">${{sig}} (${{sc.toFixed(1)}})</span></td>
                    </tr>`;
                }}).join("");

                if (Array.isArray(st.logs)) {{
                    document.getElementById("logs-pre").textContent = st.logs.join("\\n");
                }}
            }} catch (err) {{
                console.debug("Falha temporária ao consultar /api/state:", err);
            }}
        }}

        setInterval(refreshSniperDashboard, 2000);
        </script>
        </body></html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        return


def autonomous_sniper_loop():
    global GLOBAL_GATEWAY
    memory_engine = WholeMarketMemoryEngine()
    RISK_SHIELD.start_background_guardian()
    while True:
        try:
            gw = HyperliquidDeFiGateway(memory_engine)
            GLOBAL_GATEWAY = gw

            gw.sync_global_market_tape()
            gw.refresh_funding_and_open_interest()
            gw.sync_onchain_trade_history(force=True)

            # Aquecimento inicial do radar sem bloqueio sequencial lento
            for idx_init, init_coin in enumerate(BOT_STATE["watchlist"]):
                try:
                    c_5m = gw.fetch_candles_cached(init_coin, "5m", 45, stagger_idx=idx_init)
                    c_15m = gw.fetch_candles_cached(init_coin, "15m", 35, stagger_idx=idx_init)
                    l2_m = gw.fetch_l2_metrics_cached(init_coin)
                    c_fund = BOT_STATE["funding_by_coin"].get(init_coin, 0.0)
                    k_info = memory_engine.get_kalman_telemetry(init_coin)
                    BOT_STATE["radar"][init_coin] = QuantumOracleEngine.analyze_omni_intelligence(
                        init_coin, c_5m, c_15m, l2_m, c_fund, k_info, BOT_STATE["market_brain"]
                    )
                except Exception:
                    pass

            # Loop HFT de Baixa Latência blindado (não recria Gateway nem derruba WebSocket em caso de erro isolado)
            while True:
              try:
                now_loop = time.time()
                brain_state = gw.sync_global_market_tape()

                equity, open_positions = gw.sync_portfolio()
                gw.audit_and_protect_positions(open_positions)
                open_positions = list(BOT_STATE["open_positions"])
                active_coins = {p["coin"] for p in open_positions}

                gw.refresh_funding_and_open_interest()

                for idx_c, coin in enumerate(BOT_STATE["watchlist"]):
                    try:
                        c_5m = gw.fetch_candles_cached(coin, "5m", 45, stagger_idx=idx_c)
                        c_15m = gw.fetch_candles_cached(coin, "15m", 35, stagger_idx=idx_c)
                        l2_m = gw.fetch_l2_metrics_cached(coin)
                        c_fund = BOT_STATE["funding_by_coin"].get(coin, 0.0)
                        k_info = memory_engine.get_kalman_telemetry(coin)
                        analysis = QuantumOracleEngine.analyze_omni_intelligence(
                            coin, c_5m, c_15m, l2_m, c_fund, k_info, brain_state
                        )
                        BOT_STATE["radar"][coin] = analysis

                        if (
                            BOT_STATE["trading_enabled"]
                            and equity >= 3.5
                            and len(open_positions) == 0
                            and coin not in COMPASS_ONLY_COINS
                            and analysis.get("dna_approved", False)
                            and analysis.get("signal") in ("SNIPER LONG", "SNIPER SHORT")
                        ):
                            can_now, _ = gw.can_open_next_position(open_positions, BOT_STATE["max_positions"])
                            sc_now = safe_float(analysis.get("score", 0.0), 0.0)
                            vault_ok = (not BOT_STATE.get("daily_vault_active", False)) or (sc_now >= 95.0)
                            if can_now and vault_ok and sc_now >= 92.5:
                                is_b = analysis["signal"] == "SNIPER LONG"
                                if gw.open_sniper_order(coin, is_buy=is_b, strategy_label=analysis.get("strategy", "ELITE"), score=sc_now):
                                    equity, open_positions = gw.sync_portfolio(force=True)
                                    active_coins = {p["coin"] for p in open_positions}
                    except Exception as ce:
                        if "429" in str(ce):
                            time.sleep(2.0)
                        else:
                            logger.warning(f"Aviso ao analisar {coin}: {ce}")

                    if BOT_STATE["open_positions"]:
                        gw.audit_and_protect_positions(list(BOT_STATE["open_positions"]))
                        open_positions = list(BOT_STATE["open_positions"])
                        active_coins = {p["coin"] for p in open_positions}
                    else:
                        open_positions = []
                        active_coins = set()

                can_enter, _ = gw.can_open_next_position(open_positions, BOT_STATE["max_positions"])

                if (
                    BOT_STATE["trading_enabled"]
                    and equity >= 3.5
                    and can_enter
                ):
                    candidates = []
                    for r_coin, r_data in BOT_STATE["radar"].items():
                        if r_coin in active_coins or r_coin in COMPASS_ONLY_COINS:
                            continue
                        if not r_data.get("dna_approved", False):
                            continue
                        if (now_loop - safe_float(r_data.get("updated_ts", 0.0), 0.0)) > 45.0:
                            continue
                        if r_data.get("signal") in ("SNIPER LONG", "SNIPER SHORT"):
                            if BOT_STATE.get("daily_vault_active", False) and safe_float(r_data.get("score", 0.0), 0.0) < 95.0:
                                continue
                            k_now = memory_engine.get_kalman_telemetry(r_coin)
                            v_now = safe_float(k_now.get("vel_1m_pct", 0.0), 0.0)
                            if r_data["signal"] == "SNIPER LONG" and v_now >= MIN_ENTRY_VEL_1M_PCT:
                                candidates.append((safe_float(r_data.get("score", 0.0), 0.0), r_coin, True, r_data))
                            elif r_data["signal"] == "SNIPER SHORT" and v_now <= -MIN_ENTRY_VEL_1M_PCT:
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

                time.sleep(0.25)
              except Exception as inner_e:
                if "429" in str(inner_e):
                    time.sleep(4.0)
                else:
                    add_log(f"⚠️ Aviso recuperado no ciclo HFT: {inner_e}")
                    time.sleep(1.0)
        except ValueError as ve:
            BOT_STATE["status"] = f"ERRO DE CREDENCIAIS: {mask_sensitive_hex(ve)}"
            add_log(f"❌ {ve}")
            raise
        except Exception as e:
            BOT_STATE["status"] = f"RECONECTANDO: {mask_sensitive_hex(str(e))[:45]}"
            add_log(f"⚠️ Erro no loop principal: {e}")
            time.sleep(5.0)


if __name__ == "__main__":
    # Valida imediatamente na inicialização antes de tentar conectar (Zero Hardcode)
    validate_required_credentials()
    worker = threading.Thread(target=autonomous_sniper_loop, daemon=True)
    worker.start()
    port = int(os.getenv("PORT", 8080))
    add_log(f"Painel Web HTML v72.0 Sovereign HFT WebSocket & Microprice ativo na porta {port}")
    server = ThreadingHTTPServer(("0.0.0.0", port), SovereignWebServer)
    server.serve_forever()
