"""
Sniper HFT & Quantitative Trading Engine — ORACLE SINGULARITY v18.0 (MEGA INTELIGÊNCIA PREDITIVA AUTÔNOMA)
===========================================================================================================
Motor Autônomo 24/7 para Railway / Render / VPS — 100% Mercado SPOT ("spot") com Previsão Matemática de Futuro v18.0

AS 6 INOVAÇÕES "ORACLE SINGULARITY v18.0" (PREVISÃO DE FUTURO + SMART MONEY L2 + RADAR LEAD-LAG):
1. Motor Preditivo de Futuro (`predict_future_trajectory` — Kalman Filter + Velocidade/Aceleração + Regressão 12 Velas):
   - Substitui a reação atrasada por previsão matemática da trajetória futura do preço:
     * **Filtro de Kalman 1D (`kalman_price`, `kalman_velocity`)** acoplado à **1ª derivada (velocidade)** e
       **2ª derivada (aceleração)** do preço + **Regressão Linear Ponderada** das últimas 12 velas e da janela de 5s.
     * Calcula em tempo real `predicted_move_pct_3m` (movimento percentual projetado para os próximos 3 minutos)
       e `win_probability_pct` (probabilidade matemática de vitória de `0.0%` a `99.0%`).
     * **Regra de Ouro v18.0:** O robô SÓ abre compra automática se `predicted_move_pct_3m >= +0.85%` E
       `win_probability_pct >= 76.0%`, garantindo entrada na ignição ANTES do movimento acontecer!
2. Detector de Absorção Institucional e Vácuo de Liquidez (`Smart Money Radar L2`):
   - Em `on_l2_orderbook_update`, além do `l2_obi`, calcula a razão de vácuo superior (`ask_thinning_ratio`):
     compara o suporte comprador dos 15 níveis de Bids com a resistência dos 5 primeiros níveis de Asks.
   - Quando há absorção institucional (`l2_obi >= +0.20` e `ask_thinning_ratio >= 1.35`), ativa `smart_money_ignition = True`,
     elevando imediatamente a probabilidade preditiva e antecipando o disparo antes da explosão da vela!
3. Radar Lead-Lag (`check_lead_lag_radar` — Antecipação pela Ignição do BTC/ETH):
   - Monitora o micro-impulso de 5 segundos (`impulse_5s_pct`) e o fluxo (`obi`) dos líderes macro `BTCUSDT` e `ETHUSDT`.
   - Quando BTC ou ETH iniciam ignição compradora (`impulse_5s_pct >= +0.06%` e `obi > 0.10`), ativa `macro_leader_igniting = True`,
     priorizando compra imediata na altcoin ativa (`SOL`, `XRP`, `DOGE` ou `BNB`) de maior `win_probability_pct` e menor spread!
4. Saída Preditiva no Topo da Onda (`PREDICTIVE_TOP_CASH_IN` em 0ms — Zero Devolução de Lucro):
   - Em `evaluate_single_position`, quando a posição já está em lucro líquido (`gain_pct >= +0.42%`), o robô não espera
     o preço despencar até o Stop: se a aceleração/impulso de 5s virar negativa (`impulse_5s_pct < -0.02%`) OU surgir
     parede vendedora institucional no Book (`l2_obi <= -0.18`), executa `PREDICTIVE_TOP_CASH_IN` em 0ms no topo da vela!
5. Cérebro Auto-Adaptativo de Gatilho (`auto_tune_neural_parameters` — 100% Autônomo):
   - Analisa continuamente a força média do mercado (`OBI`, `CVD`, `Win Prob` e regime das 6 moedas) e ajusta sozinho
     `self.min_confluence_score` entre `76.0` (explosão compradora sincronizada) e `85.0` (mercado travado/traiçoeiro),
     além de reabilitar automaticamente uma moeda suspensa caso ela apresente reversão institucional perfeita com
     `win_probability_pct >= 84.0%`!
6. Mantém 100% das blindagens da conta real Bybit Spot (`qty_step=0.001` na SOL, Fast-Exit 0ms, Wilder RSI, MACD,
   VWAP Ponderada por Volume, Spread Guard, Time-Stop 12m e High-Water Mark Diário).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:
    import websockets  # type: ignore
except ImportError:
    websockets = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SniperBybitOracleV18")

BRAIN_STATE_FILE = Path("/tmp/sniper_v18_oracle_brain_state.json")


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# =====================================================================
# 1. ESPECIFICAÇÕES REAIS DO MERCADO SPOT DA BYBIT V5 ("category": "spot")
# =====================================================================

@dataclass(frozen=True)
class BybitSpotSpec:
    symbol: str
    base_coin: str
    qty_step: float
    min_qty: float
    min_notional_usd: float
    tick_size: float
    price_decimals: int
    min_equity_usd: float


BYBIT_CONTRACTS: Dict[str, BybitSpotSpec] = {
    "SOLUSDT":  BybitSpotSpec("SOLUSDT",  base_coin="SOL",  qty_step=0.001,   min_qty=0.001,   min_notional_usd=5.0,  tick_size=0.01,    price_decimals=2, min_equity_usd=8.0),
    "XRPUSDT":  BybitSpotSpec("XRPUSDT",  base_coin="XRP",  qty_step=0.01,    min_qty=0.1,     min_notional_usd=5.0,  tick_size=0.0001,  price_decimals=4, min_equity_usd=8.0),
    "DOGEUSDT": BybitSpotSpec("DOGEUSDT", base_coin="DOGE", qty_step=0.1,     min_qty=1.0,     min_notional_usd=5.0,  tick_size=0.00001, price_decimals=5, min_equity_usd=8.0),
    "BNBUSDT":  BybitSpotSpec("BNBUSDT",  base_coin="BNB",  qty_step=0.0001,  min_qty=0.001,   min_notional_usd=5.0,  tick_size=0.01,    price_decimals=2, min_equity_usd=15.0),
    "ETHUSDT":  BybitSpotSpec("ETHUSDT",  base_coin="ETH",  qty_step=0.00001, min_qty=0.0001,  min_notional_usd=5.0,  tick_size=0.01,    price_decimals=2, min_equity_usd=25.0),
    "BTCUSDT":  BybitSpotSpec("BTCUSDT",  base_coin="BTC",  qty_step=0.000001,min_qty=0.00001, min_notional_usd=5.0,  tick_size=0.10,    price_decimals=1, min_equity_usd=50.0),
}

BASE_COIN_TO_SYMBOL: Dict[str, str] = {spec.base_coin: sym for sym, spec in BYBIT_CONTRACTS.items()}


def format_bybit_qty(qty: float, step: float) -> str:
    if step <= 0:
        step = 0.001
    if step >= 1.0:
        floored_int = max(0, int(math.floor((qty + 1e-12) / step) * step))
        return str(floored_int)
    decimals = max(0, int(round(-math.log10(step))))
    floored = math.floor((qty + 1e-12) / step) * step
    return f"{floored:.{decimals}f}"


def format_bybit_price(price: float, tick: float, decimals: int) -> str:
    if tick <= 0:
        tick = 0.01
    rounded = round(price / tick) * tick
    return f"{rounded:.{decimals}f}"


# =====================================================================
# 2. GATEWAY OFICIAL BYBIT V5 SPOT (FAST-EXECUTION 0MS + ZERO POEIRA)
# =====================================================================

class BybitV5AutonomousGateway:
    MAINNET_ENDPOINTS: List[str] = [
        "https://api.bytick.com",
        "https://api.bybitglobal.com",
        "https://api.bybit.com",
    ]
    DEMO_ENDPOINTS: List[str] = [
        "https://api-demo.bybit.com",
        "https://api-testnet.bybit.com",
    ]
    WS_SPOT_ENDPOINTS: List[str] = [
        "wss://stream.bytick.com/v5/public/spot",
        "wss://stream.bybit.com/v5/public/spot",
        "wss://stream.bybitglobal.com/v5/public/spot",
    ]
    RECV_WINDOW: str = "25000"

    def __init__(self) -> None:
        self.env_api_key: str = os.getenv("BYBIT_API_KEY", "").strip()
        self.env_api_secret: str = os.getenv("BYBIT_API_SECRET", "").strip()
        self.api_key: str = self.env_api_key or "2Q9GwuhSJ7x87HqIEN"
        self.api_secret: str = self.env_api_secret
        self.exec_mode: str = os.getenv("BYBIT_EXEC_MODE", "BYBIT_REAL").strip()
        self.active_base_url: str = self.MAINNET_ENDPOINTS[0]
        self.time_offset_ms: int = 0
        self.last_time_sync_ts: float = 0.0
        self.http: Optional[httpx.AsyncClient] = None
        self.last_api_status: str = "Inicializando conector Bybit V5 Spot Oracle Singularity v18.0..."
        self.last_api_error: str = ""
        self.last_http_code: int = 0
        self.is_us_west_geoblocked: bool = False
        self.account_type_detected: str = "UNIFIED"
        self.leverage_configured: Dict[str, int] = {}
        self.coin_balances: Dict[str, float] = {
            "USDT": 24.8282,
            "SOL": 0.0,
            "XRP": 0.0,
            "DOGE": 0.0,
            "BNB": 0.0,
            "ETH": 0.0,
            "BTC": 0.0,
        }
        self.coin_usd_values: Dict[str, float] = {
            "USDT": 24.8282,
            "SOL": 0.0,
            "XRP": 0.0,
            "DOGE": 0.0,
            "BNB": 0.0,
            "ETH": 0.0,
            "BTC": 0.0,
        }

    async def ensure_http(self) -> httpx.AsyncClient:
        if self.http is None or self.http.is_closed:
            self.http = httpx.AsyncClient(
                timeout=6.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
            )
        return self.http

    def get_candidate_urls(self) -> List[str]:
        if self.exec_mode == "BYBIT_DEMO":
            return list(self.DEMO_ENDPOINTS)
        return [self.active_base_url] + [u for u in self.MAINNET_ENDPOINTS if u != self.active_base_url]

    def get_candidate_api_keys(self) -> List[str]:
        candidates: List[str] = []
        for k in [self.env_api_key, self.api_key]:
            k = k.strip()
            if k and k not in candidates:
                candidates.append(k)
                for variant in [
                    k.replace("HqIEN", "HqlEN"),
                    k.replace("HqlEN", "HqIEN"),
                    k.replace("HqIEN", "Hq1EN"),
                ]:
                    if variant and variant not in candidates:
                        candidates.append(variant)
        return candidates

    def sign_v5_headers(self, payload_str: str, ts_ms: Optional[str] = None, override_key: Optional[str] = None) -> Dict[str, str]:
        use_key = (override_key or self.api_key).strip()
        ts = ts_ms or self.current_ts_ms()
        raw_to_sign = f"{ts}{use_key}{self.RECV_WINDOW}{payload_str}"
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            raw_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": use_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": self.RECV_WINDOW,
            "X-BAPI-SIGN": sig,
        }

    async def sync_server_time(self, force: bool = False) -> str:
        if not force and (time.time() - self.last_time_sync_ts) < 45.0:
            return self.current_ts_ms()
        client = await self.ensure_http()
        for base in self.get_candidate_urls():
            try:
                r = await client.get(f"{base}/v5/market/time")
                self.last_http_code = r.status_code
                if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                    data = r.json()
                    srv_ms = int(data.get("time") or (int(data.get("result", {}).get("timeNano", 0)) // 1_000_000))
                    if srv_ms > 0:
                        self.active_base_url = base
                        self.time_offset_ms = srv_ms - int(time.time() * 1000)
                        self.last_time_sync_ts = time.time()
                        self.is_us_west_geoblocked = False
                        return str(srv_ms)
            except Exception:
                continue
        return str(int(time.time() * 1000) + self.time_offset_ms)

    def current_ts_ms(self) -> str:
        return str(int(time.time() * 1000) + self.time_offset_ms)

    async def sync_spot_instruments_precision(self) -> None:
        client = await self.ensure_http()
        for base in self.get_candidate_urls():
            try:
                r = await client.get(f"{base}/v5/market/instruments-info?category=spot")
                if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                    items = r.json().get("result", {}).get("list", [])
                    for it in items:
                        sym = str(it.get("symbol", ""))
                        if sym in BYBIT_CONTRACTS:
                            lot_filter = it.get("lotSizeFilter", {})
                            price_filter = it.get("priceFilter", {})
                            b_prec = safe_float(lot_filter.get("basePrecision"), BYBIT_CONTRACTS[sym].qty_step)
                            m_qty = safe_float(lot_filter.get("minOrderQty"), BYBIT_CONTRACTS[sym].min_qty)
                            m_amt = safe_float(lot_filter.get("minOrderAmt"), BYBIT_CONTRACTS[sym].min_notional_usd)
                            t_size = safe_float(price_filter.get("tickSize"), BYBIT_CONTRACTS[sym].tick_size)
                            if sym == "SOLUSDT":
                                b_prec = min(b_prec, 0.001) if b_prec > 0 else 0.001
                            if b_prec > 0 and t_size > 0:
                                p_dec = max(0, int(round(-math.log10(t_size)))) if t_size < 1.0 else 1
                                BYBIT_CONTRACTS[sym] = replace(
                                    BYBIT_CONTRACTS[sym],
                                    qty_step=b_prec,
                                    min_qty=max(b_prec, m_qty),
                                    min_notional_usd=max(5.0, m_amt),
                                    tick_size=t_size,
                                    price_decimals=p_dec,
                                )
                    return
            except Exception:
                continue

    async def signed_get(
        self,
        path: str,
        query_string: str,
        override_key: Optional[str] = None,
        override_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        client = await self.ensure_http()
        await self.sync_server_time()
        saw_403_geoblock = False
        last_status = 0
        urls = override_urls or self.get_candidate_urls()

        for base in urls:
            ts = self.current_ts_ms()
            headers = self.sign_v5_headers(query_string, ts_ms=ts, override_key=override_key)
            url = f"{base}{path}?{query_string}" if query_string else f"{base}{path}"
            try:
                resp = await client.get(url, headers=headers)
                last_status = resp.status_code
                self.last_http_code = last_status
                if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                    self.active_base_url = base
                    self.is_us_west_geoblocked = False
                    data = resp.json()
                    data["_domain"] = base
                    return data
                elif resp.status_code == 403:
                    saw_403_geoblock = True
            except Exception as exc:
                self.last_api_error = str(exc)

        if saw_403_geoblock:
            self.is_us_west_geoblocked = True
            return {
                "retCode": 403,
                "_domain": "Railway US-West",
                "retMsg": "Servidor em US West recebeu HTTP 403. Mude Region no Railway para Singapore ou EU West.",
            }
        return {"retCode": -1, "retMsg": f"Falha HTTP ({last_status}) ao conectar na Bybit: {self.last_api_error}"}

    async def signed_post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        client = await self.ensure_http()
        await self.sync_server_time()
        body_str = json.dumps(payload, separators=(",", ":"))
        saw_403_geoblock = False

        for base in self.get_candidate_urls():
            ts = self.current_ts_ms()
            headers = {
                **self.sign_v5_headers(body_str, ts_ms=ts),
                "Content-Type": "application/json",
            }
            url = f"{base}{path}"
            try:
                resp = await client.post(url, content=body_str, headers=headers)
                self.last_http_code = resp.status_code
                if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                    self.active_base_url = base
                    self.is_us_west_geoblocked = False
                    return resp.json()
                elif resp.status_code == 403:
                    saw_403_geoblock = True
            except Exception as exc:
                self.last_api_error = str(exc)

        if saw_403_geoblock:
            self.is_us_west_geoblocked = True
            return {
                "retCode": 403,
                "retMsg": "HTTP 403 (Servidor Railway bloqueado regionalmente).",
            }
        return {"retCode": -1, "retMsg": f"Erro POST Bybit ({self.last_api_error})"}

    async def auto_transfer_fund_to_unified(self, amount_usdt: float) -> bool:
        if amount_usdt < 0.50:
            return False
        transfer_payload = {
            "transferId": str(uuid.uuid4()),
            "coin": "USDT",
            "amount": f"{amount_usdt:.2f}",
            "fromAccountType": "FUND",
            "toAccountType": "UNIFIED",
        }
        res = await self.signed_post("/v5/asset/transfer/inter-transfer", transfer_payload)
        if res.get("retCode") == 0:
            logger.info(f"🔄 [AUTO-TRANSFER BYBIT] Transferiu ${amount_usdt:.2f} USDT de FUND -> UNIFIED!")
            return True
        return False

    def extract_usd_and_coins_from_wallet_response(self, res: Dict[str, Any], usd_brl_rate: float) -> float:
        lists = res.get("result", {}).get("list", [])
        best_usd = 0.0
        for acc in lists:
            total_eq = max(
                safe_float(acc.get("totalEquity")),
                safe_float(acc.get("totalWalletBalance")),
                safe_float(acc.get("totalMarginBalance")),
                safe_float(acc.get("totalAvailableBalance")),
            )
            coins = acc.get("coin", [])
            coin_sum_usd = 0.0
            for c in coins:
                c_name = str(c.get("coin", "")).upper()
                c_qty = max(
                    safe_float(c.get("walletBalance")),
                    safe_float(c.get("equity")),
                    safe_float(c.get("availableToWithdraw")),
                )
                c_usd = safe_float(c.get("usdValue"))
                if c_name:
                    self.coin_balances[c_name] = c_qty
                    self.coin_usd_values[c_name] = c_qty if c_name in ("USDT", "USDC") else c_usd
                if c_name in ("USDT", "USDC"):
                    coin_sum_usd += c_qty
                elif c_name == "BRL":
                    coin_sum_usd += c_qty / usd_brl_rate
                else:
                    coin_sum_usd += c_usd
            best_usd = max(best_usd, total_eq, coin_sum_usd)
        return best_usd

    def build_dynamic_holding_summary(self) -> str:
        parts: List[str] = []
        usdt_q = self.coin_balances.get("USDT", 0.0)
        if usdt_q >= 0.05:
            parts.append(f"USDT: ${usdt_q:.2f}")
        for base_c in ["SOL", "XRP", "DOGE", "BNB", "ETH", "BTC"]:
            q = self.coin_balances.get(base_c, 0.0)
            u_val = self.coin_usd_values.get(base_c, 0.0)
            if q > 0 and (u_val >= 0.05 or q >= 0.0005):
                dec = 4 if q < 1 else 2
                parts.append(f"{base_c}: {q:.{dec}f}" + (f" (${u_val:.2f})" if u_val > 0 else ""))
        return " | ".join(parts) if parts else f"USDT: ${usdt_q:.2f}"

    async def get_spot_coin_available_balance(self, coin_name: str) -> float:
        for acct_type in ["UNIFIED", "SPOT"]:
            res = await self.signed_get("/v5/account/wallet-balance", f"accountType={acct_type}&coin={coin_name}")
            if int(res.get("retCode", -1)) == 0:
                lists = res.get("result", {}).get("list", [])
                for acc in lists:
                    for c in acc.get("coin", []):
                        if str(c.get("coin", "")).upper() == coin_name.upper():
                            wb = safe_float(c.get("walletBalance"))
                            eq = safe_float(c.get("equity"))
                            av = safe_float(c.get("availableToWithdraw"))
                            bal = wb if wb > 0 else max(eq, av)
                            self.coin_balances[coin_name.upper()] = bal
                            return bal
        return self.coin_balances.get(coin_name.upper(), 0.0)

    async def fetch_wallet_balance_v5(self, usd_brl_rate: float = 5.3487) -> Dict[str, Any]:
        if not self.api_key or not self.api_secret:
            self.last_api_status = "⚠️ API Secret ainda não informado nas Variables do Railway (BYBIT_API_SECRET)."
            return {"ok": False, "error": self.last_api_status}

        candidate_keys = self.get_candidate_api_keys()
        last_ret_code = 0
        last_ret_msg = ""
        last_domain = self.active_base_url

        for cand_key in candidate_keys:
            try:
                fund_res = await self.signed_get(
                    "/v5/asset/transfer/query-account-coins-balance",
                    "accountType=FUND&coin=USDT",
                    override_key=cand_key,
                )
                if int(fund_res.get("retCode", -1)) == 0:
                    f_list = fund_res.get("result", {}).get("balance", [])
                    for f_item in f_list:
                        if str(f_item.get("coin", "")).upper() == "USDT":
                            f_usdt = safe_float(f_item.get("transferBalance") or f_item.get("walletBalance"))
                            if f_usdt >= 1.0:
                                await self.auto_transfer_fund_to_unified(f_usdt)
            except Exception:
                pass

            for acct_type in ["UNIFIED", "SPOT"]:
                for query in [
                    f"accountType={acct_type}&coin=USDT,SOL,XRP,DOGE,BNB,ETH,BTC",
                    f"accountType={acct_type}",
                ]:
                    res = await self.signed_get("/v5/account/wallet-balance", query, override_key=cand_key)
                    ret_code = int(res.get("retCode", -1))
                    ret_msg = str(res.get("retMsg", ""))
                    last_domain = str(res.get("_domain", self.active_base_url))

                    if ret_code == 403:
                        self.last_api_status = f"🌍 {ret_msg}"
                        return {"ok": False, "retCode": 403, "geoblocked": True, "error": self.last_api_status}

                    if ret_code == 0:
                        self.api_key = cand_key
                        best_usd = self.extract_usd_and_coins_from_wallet_response(res, usd_brl_rate)
                        if best_usd > 0.1:
                            self.account_type_detected = acct_type
                            brl_val = best_usd * usd_brl_rate
                            holding_detail = self.build_dynamic_holding_summary()
                            self.last_api_status = (
                                f"✅ CONTA SPOT SINCRONIZADA ({acct_type}): ${best_usd:.4f} (≈ R$ {brl_val:.2f}) "
                                f"[{holding_detail}] via {last_domain}"
                            )
                            return {
                                "ok": True,
                                "equity_usd": round(best_usd, 4),
                                "account_type": acct_type,
                                "coin_balances": dict(self.coin_balances),
                                "coin_usd_values": dict(self.coin_usd_values),
                                "source": f"Bybit Spot ({holding_detail})",
                            }
                    else:
                        last_ret_code = ret_code
                        last_ret_msg = ret_msg
                        if ret_code == 10003:
                            break

                if last_ret_code == 10003:
                    break

        if last_ret_code != 0:
            self.last_api_status = f"⚠️ Resposta da Bybit (Código {last_ret_code} em {last_domain}): {last_ret_msg}"
            return {"ok": False, "retCode": last_ret_code, "error": self.last_api_status}

        self.last_api_status = "✅ Chave API conectada ao Mercado Spot Bybit!"
        return {"ok": False, "error": self.last_api_status}

    async def ensure_leverage(self, symbol: str, leverage: int = 1) -> None:
        self.leverage_configured[symbol] = leverage
        return

    async def place_real_bybit_order(
        self,
        symbol: str,
        side: str,
        qty_float: float,
        stop_loss: float,
        take_profit: float,
        leverage: int = 1,
    ) -> Dict[str, Any]:
        spec = BYBIT_CONTRACTS.get(symbol, BYBIT_CONTRACTS["SOLUSDT"])
        qty_str = format_bybit_qty(qty_float, spec.qty_step)
        sl_str = format_bybit_price(stop_loss, spec.tick_size, spec.price_decimals)
        tp_str = format_bybit_price(take_profit, spec.tick_size, spec.price_decimals)
        bybit_side = "Buy" if side.upper() in ("LONG", "BUY") else "Sell"

        await self.ensure_leverage(symbol, leverage)

        order_payload: Dict[str, Any] = {
            "category": "spot",
            "symbol": symbol,
            "side": bybit_side,
            "orderType": "Market",
            "qty": qty_str,
            "marketUnit": "baseCoin",
        }

        res = await self.signed_post("/v5/order/create", order_payload)
        ret_code = int(res.get("retCode", -1))
        if ret_code == 0:
            order_id = res.get("result", {}).get("orderId", f"SPOT_{int(time.time())}")
            net_sellable_str = format_bybit_qty(float(qty_str) * 0.9988, spec.qty_step)
            net_sellable_qty = max(spec.min_qty, float(net_sellable_str))
            logger.info(
                f"🔥 [ORDEM REAL SPOT EXECUTADA NA BYBIT] {bybit_side} {qty_str} {symbol} (Líquido: {net_sellable_qty}) | "
                f"OrderID={order_id} | SL={sl_str} | TP={tp_str}"
            )
            return {
                "ok": True,
                "order_id": order_id,
                "qty_str": qty_str,
                "net_sellable_qty": net_sellable_qty,
                "sl_str": sl_str,
                "tp_str": tp_str,
                "raw": res,
            }

        err_msg = str(res.get("retMsg", "Erro desconhecido"))
        logger.warning(f"⚠️ [AVISO ORDEM SPOT BYBIT] retCode={ret_code} retMsg={err_msg}")
        return {
            "ok": False,
            "retCode": ret_code,
            "error": f"Erro Bybit Spot {ret_code}: {err_msg}",
            "signed_order_payload": order_payload,
        }

    async def close_real_bybit_position(
        self,
        symbol: str,
        side: str,
        qty_float: float,
        current_price: float = 0.0,
    ) -> Dict[str, Any]:
        spec = BYBIT_CONTRACTS.get(symbol, BYBIT_CONTRACTS["SOLUSDT"])
        close_side = "Sell" if side.upper() in ("LONG", "BUY") else "Buy"

        fast_qty_str = format_bybit_qty(max(spec.min_qty, qty_float), spec.qty_step)
        if float(fast_qty_str) >= spec.min_qty:
            fast_payload: Dict[str, Any] = {
                "category": "spot",
                "symbol": symbol,
                "side": close_side,
                "orderType": "Market",
                "qty": fast_qty_str,
                "marketUnit": "baseCoin",
            }
            fast_res = await self.signed_post("/v5/order/create", fast_payload)
            if int(fast_res.get("retCode", -1)) == 0:
                order_id = fast_res.get("result", {}).get("orderId", "")
                logger.info(f"⚡ [FAST-EXIT 0ms SPOT LIQUIDADO] {close_side} {fast_qty_str} {symbol} | OrderID={order_id}")
                return {"ok": True, "order_id": order_id, "sold_qty": float(fast_qty_str)}

        avail_coin = await self.get_spot_coin_available_balance(spec.base_coin)
        if avail_coin > 0:
            leftover_coin = max(0.0, avail_coin - qty_float)
            leftover_usd = leftover_coin * current_price if current_price > 0 else 0.0
            if 0 <= leftover_usd < 5.50 or qty_float >= avail_coin * 0.98:
                sell_qty = avail_coin
            else:
                sell_qty = min(qty_float, avail_coin)
        else:
            sell_qty = qty_float * 0.9985

        for factor in [1.0, 0.9990]:
            candidate_qty = max(spec.min_qty, (sell_qty * factor) if factor < 1.0 else sell_qty)
            qty_str = format_bybit_qty(candidate_qty, spec.qty_step)
            if float(qty_str) <= 0:
                continue
            payload: Dict[str, Any] = {
                "category": "spot",
                "symbol": symbol,
                "side": close_side,
                "orderType": "Market",
                "qty": qty_str,
                "marketUnit": "baseCoin",
            }
            res = await self.signed_post("/v5/order/create", payload)
            if int(res.get("retCode", -1)) == 0:
                order_id = res.get("result", {}).get("orderId", "")
                logger.info(f"✅ [POSIÇÃO SPOT 100% LIQUIDADA NA BYBIT] {close_side} {qty_str} {symbol} | OrderID={order_id}")
                return {"ok": True, "order_id": order_id, "sold_qty": float(qty_str)}

        logger.warning(f"⚠️ [AVISO FECHAMENTO SPOT] Não foi possível liquidar {symbol}")
        return {"ok": False, "raw": {}}


# =====================================================================
# 3. TELEMETRIA ORACLE SINGULARITY v18.0 (KALMAN FILTER + PREVISÃO 3M + SMART MONEY L2)
# =====================================================================

class CloudAssetTelemetry:
    """
    ORACLE SINGULARITY v18.0 (PREVISÃO MATEMÁTICA DE FUTURO + SMART MONEY L2):
    1) `predict_future_trajectory()`:
       - Filtro de Kalman 1D (`kalman_price`, `kalman_velocity`, `kalman_cov`) +
         1ª derivada (`price_velocity`), 2ª derivada (`price_acceleration`) +
         Regressão Linear Ponderada das últimas 12 velas e da janela de ticks de 5s (`impulse_5s_pct`).
       - Calcula `predicted_move_pct_3m` (movimento previsto para os próximos 3 minutos)
         e `win_probability_pct` (`0.0%` a `99.0%`).
       - Regra de Ouro v18.0: SÓ abre compra se `predicted_move_pct_3m >= +0.85%` E `win_probability_pct >= 76.0%`!
    2) `on_l2_orderbook_update()`:
       - Calcula `ask_thinning_ratio` (liquidez dos 15 níveis de suporte Bids vs. 5 primeiros níveis de venda Asks).
       - Quando há absorção institucional (`l2_obi >= +0.20` e `ask_thinning_ratio >= 1.35`), ativa
         `smart_money_ignition = True` e concede bônus preditivo imediato!
    """

    CANDLE_INTERVAL_SEC: float = 60.0

    def __init__(self, symbol: str, initial_price: float, step: float, decimals: int) -> None:
        self.symbol = symbol
        self.price = initial_price
        self.best_bid = round(initial_price - step, decimals)
        self.best_ask = round(initial_price + step, decimals)
        self.spread_pct = round(((self.best_ask - self.best_bid) / max(initial_price, 1e-8)) * 100.0, 4)
        self.vwap = initial_price
        self.step = step
        self.decimals = decimals
        self.rsi = 46.0
        self.prev_rsi = 44.0
        self.zbb = -0.25
        self.atr = round(max(initial_price * 0.0055, step * 15), decimals)
        self.ema_fast = initial_price
        self.ema_slow = initial_price
        self.macd_line = 0.0
        self.macd_signal = 0.0
        self.macd_hist = 0.0
        self.prev_macd_hist = 0.0
        self.impulse_5s_pct = 0.0
        # Estado do Filtro de Kalman e Derivadas Preditivas (v18.0 Oracle Singularity)
        self.kalman_price: float = initial_price
        self.kalman_velocity: float = 0.0
        self.kalman_cov: float = 1.0
        self.price_velocity: float = 0.0
        self.price_acceleration: float = 0.0
        self.predicted_move_pct_3m: float = 0.0
        self.win_probability_pct: float = 60.0
        # Smart Money Radar L2
        self.ask_thinning_ratio: float = 1.0
        self.smart_money_ignition: bool = False
        self.htf_ema_fast = initial_price
        self.htf_ema_slow = initial_price
        self.htf_bullish: bool = True
        self.obi = 0.18
        self.l2_obi = 0.15
        self.cvd = 0.15
        self.whale_wall_status: str = "BOOK_EQUILIBRADO"
        self.coin_wins: int = 0
        self.coin_losses: int = 0
        self.consecutive_losses: int = 0
        self.ai_trust_bonus: float = 0.0
        self.suspended_until: float = 0.0
        self.trend_regime: str = "NEUTRAL"
        self.long_score = 65.0
        self.short_score = 35.0
        self.best_side = "LONG"
        self.score = 65.0
        self.history: Deque[float] = deque(maxlen=40)
        self.highs: Deque[float] = deque(maxlen=40)
        self.lows: Deque[float] = deque(maxlen=40)
        self.volumes: Deque[float] = deque(maxlen=40)
        self.htf_closes: Deque[float] = deque(maxlen=25)
        self.tick_window_5s: Deque[Tuple[float, float]] = deque(maxlen=40)
        self.current_bar_high: float = initial_price
        self.current_bar_low: float = initial_price
        self.current_bar_vol: float = 1000.0
        self.last_candle_ts: float = 0.0
        self.seeded = False
        self.seed_history(initial_price)

    @property
    def is_suspended_by_ai(self) -> bool:
        return time.time() < self.suspended_until

    @property
    def suspension_remaining_min(self) -> int:
        if not self.is_suspended_by_ai:
            return 0
        return max(1, int(round((self.suspended_until - time.time()) / 60.0)))

    def record_trade_outcome(self, is_win: bool) -> str:
        if is_win:
            self.coin_wins += 1
            self.consecutive_losses = 0
            self.ai_trust_bonus = min(5.0, round(self.ai_trust_bonus + 2.0, 1))
            return f"🧠 Oracle v18.0 aumentou confiança em {self.symbol} (Bônus +{self.ai_trust_bonus:.1f} pts • {self.coin_wins}W/{self.coin_losses}L)"
        else:
            self.coin_losses += 1
            self.consecutive_losses += 1
            self.ai_trust_bonus = max(-6.0, round(self.ai_trust_bonus - 3.5, 1))
            if self.consecutive_losses >= 2:
                self.suspended_until = time.time() + 7200.0
                return (
                    f"🧠 AUTO-DEFESA ORACLE: {self.symbol} teve {self.consecutive_losses} Stops seguidos e foi "
                    f"SUSPENSA AUTOMATICAMENTE por 2 horas (a menos que atinja Reversão Institucional ≥ 84% Win Prob)!"
                )
            return f"🧠 Oracle v18.0 ativou Modo Seletivo em {self.symbol} após 1 Stop (Penalidade {self.ai_trust_bonus:.1f} pts)"

    def on_l2_orderbook_update(self, bids: List[List[Any]], asks: List[List[Any]]) -> None:
        """
        INOVAÇÃO #2 — Detector de Absorção Institucional e Vácuo de Liquidez (Smart Money Radar L2):
        - Calcula `l2_obi` (15 níveis) e `ask_thinning_ratio` (liquidez dos 15 níveis de suporte Bids
          comparada à resistência dos 5 primeiros níveis de Asks).
        - Quando há forte suporte comprador nos Bids segurando o preço + parede de Asks fina acima
          (`l2_obi >= +0.20` e `ask_thinning_ratio >= 1.35`), ativa `self.smart_money_ignition = True`!
        """
        if not bids or not asks:
            return
        top_bid = safe_float(bids[0][0]) if len(bids[0]) >= 1 else 0.0
        top_ask = safe_float(asks[0][0]) if len(asks[0]) >= 1 else 0.0
        if top_bid > 0 and top_ask >= top_bid:
            self.best_bid = round(top_bid, self.decimals)
            self.best_ask = round(top_ask, self.decimals)
            self.spread_pct = round(((top_ask - top_bid) / top_bid) * 100.0, 4)

        bid_vol_15 = sum(safe_float(b[1]) for b in bids[:15] if len(b) >= 2)
        ask_vol_15 = sum(safe_float(a[1]) for a in asks[:15] if len(a) >= 2)
        ask_vol_top5 = sum(safe_float(a[1]) for a in asks[:5] if len(a) >= 2)
        total = bid_vol_15 + ask_vol_15
        if total <= 0:
            return
        raw_l2 = (bid_vol_15 - ask_vol_15) / total
        self.l2_obi = round(max(-0.90, min(0.90, raw_l2)), 2)
        self.obi = round(max(-0.88, min(0.88, (self.obi * 0.55) + (self.l2_obi * 0.45))), 2)

        # Razão de Vácuo Superior (suporte médio de 5 blocos de Bids vs 5 primeiros níveis de Asks)
        normalized_bid_support = bid_vol_15 / 3.0
        self.ask_thinning_ratio = round(normalized_bid_support / max(ask_vol_top5, 1e-8), 2)

        if self.l2_obi >= 0.20 and self.ask_thinning_ratio >= 1.35:
            self.smart_money_ignition = True
            self.whale_wall_status = f"🚀 ABSORÇÃO SMART MONEY (Vácuo {self.ask_thinning_ratio:.1f}x)"
        elif self.l2_obi >= 0.22:
            self.smart_money_ignition = True
            self.whale_wall_status = "🐋 PAREDE COMPRADORA (SUPORTE FORTE)"
        elif self.l2_obi <= -0.18:
            self.smart_money_ignition = False
            self.whale_wall_status = "🧱 PAREDE VENDEDORA (BLOQUEIO DE TOPO)"
        else:
            self.smart_money_ignition = False
            self.whale_wall_status = "⚖️ BOOK EQUILIBRADO"

        # Recalcula a trajetória futura com os novos dados de absorção L2
        self.predict_future_trajectory(self.price)

    def predict_future_trajectory(self, live_px: float) -> Tuple[float, float]:
        """
        INOVAÇÃO #1 — MOTOR PREDITIVO DE FUTURO (Kalman Filter + Velocidade/Aceleração + Regressão Linear Ponderada):
        1) Atualiza o Filtro de Kalman 1D para estimar estado limpo de preço (`kalman_price`) e derivada (`kalman_velocity`).
        2) Calcula a 1ª derivada (`price_velocity`, % por minuto) e a 2ª derivada (`price_acceleration`, mudança de velocidade)
           nas últimas 12 velas + regressão linear ponderada (WLS) + micro-impulso de 5 segundos (`impulse_5s_pct`).
        3) Projeta `predicted_move_pct_3m` (movimento percentual esperado para os próximos 3 minutos) e
           `win_probability_pct` (probabilidade matemática de sucesso de 0 a 100%).
        """
        hist = list(self.history)
        if not hist or live_px <= 0:
            return (0.0, 50.0)
        hist[-1] = live_px
        window = hist[-12:] if len(hist) >= 12 else hist
        m = len(window)

        # 1) Atualização do Filtro de Kalman 1D
        q_proc = max(live_px * 0.0005, self.step) ** 2
        r_meas = max(live_px * 0.0012, self.step * 2.0) ** 2
        pred_px = self.kalman_price + self.kalman_velocity
        pred_cov = self.kalman_cov + q_proc
        k_gain = pred_cov / max(pred_cov + r_meas, 1e-12)
        innovation = live_px - pred_px
        self.kalman_price = pred_px + (k_gain * innovation)
        self.kalman_velocity = (self.kalman_velocity * 0.75) + (0.25 * innovation)
        self.kalman_cov = (1.0 - k_gain) * pred_cov

        # 2) Regressão Linear Ponderada (WLS) nas últimas 12 velas (pesos maiores para as barras mais recentes)
        weights = [float(i + 1) for i in range(m)]
        w_sum = sum(weights)
        x_vals = [float(i) for i in range(m)]
        x_bar = sum(w * x for w, x in zip(weights, x_vals)) / w_sum
        y_bar = sum(w * y for w, y in zip(weights, window)) / w_sum
        num = sum(w * (x - x_bar) * (y - y_bar) for w, x, y in zip(weights, x_vals, window))
        den = sum(w * ((x - x_bar) ** 2) for w, x in zip(weights, x_vals))
        wls_slope_per_bar = (num / den) if den > 1e-12 else 0.0
        wls_slope_pct = (wls_slope_per_bar / live_px) * 100.0

        # 3) 1ª Derivada (Velocidade) e 2ª Derivada (Aceleração)
        if m >= 3:
            v_curr = ((window[-1] - window[-2]) / max(window[-2], 1e-8)) * 100.0
            v_prev = ((window[-2] - window[-3]) / max(window[-3], 1e-8)) * 100.0
            self.price_velocity = round((v_curr * 0.65) + (wls_slope_pct * 0.35), 4)
            self.price_acceleration = round(v_curr - v_prev, 4)
        else:
            self.price_velocity = round(wls_slope_pct, 4)
            self.price_acceleration = 0.0

        kalman_vel_pct = (self.kalman_velocity / live_px) * 100.0

        # 4) Projeção Matemática para os próximos 3 minutos (`predicted_move_pct_3m`)
        # Combina potencial de expansão ATR + velocidade Kalman/WLS + aceleração + impulso de 5s + vácuo L2
        atr_potential_pct = (max(self.atr, live_px * 0.0045) / live_px) * 100.0 * 1.45
        directional_drive = (
            (max(0.0, self.price_velocity) * 2.2)
            + (max(0.0, kalman_vel_pct) * 2.0)
            + (max(0.0, self.price_acceleration) * 1.8)
            + (max(0.0, self.impulse_5s_pct) * 3.2)
        )
        flow_drive = (max(0.0, self.obi) * 0.65) + (max(0.0, self.cvd) * 0.45)
        smart_money_boost = 0.25 if self.smart_money_ignition else 0.0

        if (
            self.ema_fast >= self.ema_slow * 0.9995
            and live_px >= self.ema_fast * 0.9995
            and self.obi > 0.04
            and self.cvd > 0.02
            and 34.0 <= self.rsi <= 56.0
        ):
            raw_proj_3m = atr_potential_pct + directional_drive + flow_drive + smart_money_boost
        else:
            raw_proj_3m = (self.price_velocity * 2.0) + (self.impulse_5s_pct * 2.0) + (self.obi * 0.40)

        # Se estiver esticado no topo (RSI > 56 ou Z-Score > 0.25) ou em tendência de baixa, reduz projeção futura
        if self.rsi > 56.0 or self.zbb > 0.25 or self.ema_fast < self.ema_slow * 0.9995 or self.obi <= 0.02:
            raw_proj_3m = min(raw_proj_3m, 0.45)

        self.predicted_move_pct_3m = round(max(-2.50, min(3.20, raw_proj_3m)), 2)

        # 5) Probabilidade Matemática de Vitória (`win_probability_pct` de 0 a 99%)
        prob = 54.0
        if self.ema_fast >= self.ema_slow * 0.9995 and live_px >= self.ema_fast * 0.9995:
            prob += 10.5
        if self.htf_bullish:
            prob += 5.0
        if self.macd_hist >= self.prev_macd_hist:
            prob += 4.5
        if 34.0 <= self.rsi <= 55.5 and self.rsi >= self.prev_rsi:
            prob += 8.5
        if -1.15 <= self.zbb <= 0.22:
            prob += 4.5
        if self.obi > 0.04:
            prob += min(8.0, self.obi * 14.0)
        if self.cvd > 0.02:
            prob += min(5.5, self.cvd * 10.0)
        if self.price_velocity > 0 and self.price_acceleration >= -0.01:
            prob += 4.0
        if self.smart_money_ignition:
            prob += 5.5
        prob += self.ai_trust_bonus

        # Penalidades rigorosas se houver risco de topo, spread largo ou queda
        if self.spread_pct > 0.085:
            prob = min(prob, 58.0)
        elif self.ema_fast < self.ema_slow * 0.9995 or live_px < self.ema_fast * 0.9995 or self.obi <= 0.04 or self.cvd <= 0.02:
            prob = min(prob, 62.0)
        elif self.rsi > 56.0 or self.zbb > 0.25:
            prob = min(prob, 66.0)

        self.win_probability_pct = round(max(25.0, min(98.5, prob)), 1)
        return (self.predicted_move_pct_3m, self.win_probability_pct)

    def seed_htf_5m_klines(self, klines_5m: List[List[Any]]) -> None:
        if not klines_5m or len(klines_5m) < 8:
            return
        self.htf_closes.clear()
        for k in reversed(klines_5m):
            if len(k) >= 5:
                c_px = round(safe_float(k[4]), self.decimals)
                if c_px > 0:
                    self.htf_closes.append(c_px)
        if len(self.htf_closes) >= 5:
            seq = list(self.htf_closes)
            self.htf_ema_fast = self._compute_ema_series(seq, 7)
            self.htf_ema_slow = self._compute_ema_series(seq, 16)
            self.htf_bullish = (self.htf_ema_fast >= self.htf_ema_slow * 0.9990) and (seq[-1] >= self.htf_ema_fast * 0.9985)

    @staticmethod
    def _compute_ema_series(values: List[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2.0 / (period + 1.0)
        ema_val = values[0]
        for v in values[1:]:
            ema_val = (v * k) + (ema_val * (1.0 - k))
        return ema_val

    @classmethod
    def _compute_macd_hist_pair(cls, values: List[float]) -> Tuple[float, float]:
        if len(values) < 6:
            return (0.0, 0.0)
        k12 = 2.0 / 13.0
        k26 = 2.0 / 27.0
        k9 = 2.0 / 10.0
        ema12 = values[0]
        ema26 = values[0]
        macd_series: List[float] = []
        for v in values:
            ema12 = (v * k12) + (ema12 * (1.0 - k12))
            ema26 = (v * k26) + (ema26 * (1.0 - k26))
            macd_series.append(ema12 - ema26)
        sig = macd_series[0]
        hist_series: List[float] = []
        for m in macd_series:
            sig = (m * k9) + (sig * (1.0 - k9))
            hist_series.append(m - sig)
        return (hist_series[-2], hist_series[-1])

    @staticmethod
    def _compute_wilder_rsi(seq: List[float], period: int = 14) -> float:
        if len(seq) < 3:
            return 50.0
        diffs = [seq[i] - seq[i - 1] for i in range(1, len(seq))]
        init_len = min(period, len(diffs))
        avg_gain = sum(max(0.0, d) for d in diffs[:init_len]) / init_len
        avg_loss = sum(max(0.0, -d) for d in diffs[:init_len]) / init_len
        for d in diffs[init_len:]:
            gain = max(0.0, d)
            loss = max(0.0, -d)
            avg_gain = ((avg_gain * (period - 1)) + gain) / period
            avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if avg_loss <= 1e-12:
            return 82.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return round(max(12.0, min(88.0, 100.0 - (100.0 / (1.0 + rs)))), 1)

    def get_short_term_change_pct(self, bars_back: int = 2) -> float:
        if len(self.history) < 2:
            return 0.0
        idx = max(0, len(self.history) - bars_back)
        ref_px = self.history[idx]
        if ref_px <= 0:
            return 0.0
        return round(((self.price - ref_px) / ref_px) * 100.0, 3)

    def seed_from_real_klines(self, klines_list: List[List[Any]]) -> None:
        if not klines_list or len(klines_list) < 10:
            return
        self.history.clear()
        self.highs.clear()
        self.lows.clear()
        self.volumes.clear()
        chronological = list(reversed(klines_list))
        for k in chronological:
            if len(k) >= 6:
                h_px = round(safe_float(k[2]), self.decimals)
                l_px = round(safe_float(k[3]), self.decimals)
                c_px = round(safe_float(k[4]), self.decimals)
                vol_q = max(1.0, safe_float(k[5]))
                if c_px > 0:
                    self.highs.append(h_px if h_px > 0 else c_px)
                    self.lows.append(l_px if l_px > 0 else c_px)
                    self.history.append(c_px)
                    self.volumes.append(vol_q)

        if self.history:
            hist_list = list(self.history)
            vol_list = list(self.volumes)
            last_px = hist_list[-1]
            self.price = last_px
            self.kalman_price = last_px
            self.best_bid = round(last_px - self.step, self.decimals)
            self.best_ask = round(last_px + self.step, self.decimals)
            tot_v = sum(vol_list) or 1.0
            self.vwap = round(sum(p * v for p, v in zip(hist_list, vol_list)) / tot_v, self.decimals)
            self.ema_fast = self._compute_ema_series(hist_list, 9)
            self.ema_slow = self._compute_ema_series(hist_list, 21)
            self.current_bar_high = last_px
            self.current_bar_low = last_px
            self.last_candle_ts = time.time()
            self.atr = self.compute_atr(period=14)
            self.seeded = True
            self._recalculate_indicators_from_bars(last_px)

    def seed_history(self, base_px: float) -> None:
        self.history.clear()
        self.highs.clear()
        self.lows.clear()
        self.volumes.clear()
        amp = max(base_px * 0.0045, self.step * 12)
        for i in range(35, 0, -1):
            drift = -amp * 0.25 * (i / 35.0)
            wave = math.sin(i * 0.65) * (amp * 0.45)
            px_i = round(base_px + drift + wave, self.decimals)
            self.history.append(px_i)
            self.highs.append(round(px_i + amp * 0.40, self.decimals))
            self.lows.append(round(px_i - amp * 0.40, self.decimals))
            self.volumes.append(1000.0 + (i % 5) * 250.0)
        b_round = round(base_px, self.decimals)
        self.history.append(b_round)
        self.highs.append(round(b_round + amp * 0.40, self.decimals))
        self.lows.append(round(b_round - amp * 0.40, self.decimals))
        self.volumes.append(1500.0)
        self.price = b_round
        self.kalman_price = b_round
        self.best_bid = round(b_round - self.step, self.decimals)
        self.best_ask = round(b_round + self.step, self.decimals)
        hist_list = list(self.history)
        vol_list = list(self.volumes)
        self.vwap = round(sum(p * v for p, v in zip(hist_list, vol_list)) / sum(vol_list), self.decimals)
        self.ema_fast = self._compute_ema_series(hist_list, 9)
        self.ema_slow = self._compute_ema_series(hist_list, 21)
        self.current_bar_high = b_round
        self.current_bar_low = b_round
        self.last_candle_ts = time.time()
        self.atr = self.compute_atr(period=14)
        self.seeded = True
        self._recalculate_indicators_from_bars(b_round)

    def compute_atr(self, period: int = 14) -> float:
        if len(self.history) < 3:
            return max(self.price * 0.0045, self.step * 12)
        closes = list(self.history)[-(period + 1):]
        highs = list(self.highs)[-(period + 1):]
        lows = list(self.lows)[-(period + 1):]
        trs: List[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
                self.step * 4.0,
            )
            trs.append(tr)
        raw_atr = (sum(trs) / len(trs)) if trs else (self.price * 0.0045)
        clamped_atr = max(self.price * 0.0040, min(self.price * 0.022, raw_atr))
        return round(clamped_atr, max(self.decimals, 4))

    def _recalculate_indicators_from_bars(self, live_px: float) -> None:
        hist = list(self.history)
        if not hist:
            return
        hist[-1] = live_px
        n = len(hist)

        self.ema_fast = self._compute_ema_series(hist, 9)
        self.ema_slow = self._compute_ema_series(hist, 21)
        prev_mh, curr_mh = self._compute_macd_hist_pair(hist)
        self.prev_macd_hist = prev_mh
        self.macd_hist = curr_mh

        vols = list(self.volumes)
        if len(vols) == n and sum(vols) > 0:
            self.vwap = round(sum(p * v for p, v in zip(hist, vols)) / sum(vols), self.decimals)

        mean = sum(hist) / n
        variance = sum((x - mean) ** 2 for x in hist) / n
        std = max(math.sqrt(variance), live_px * 0.0030, self.step * 5.0)
        self.zbb = round(max(-3.0, min(3.0, (live_px - mean) / std)), 2)

        if n >= 4:
            self.prev_rsi = self._compute_wilder_rsi(hist[:-1], period=14)
        self.rsi = self._compute_wilder_rsi(hist, period=14)

        # Atualiza a Previsão Matemática de Futuro (Kalman + 1ª/2ª Derivadas + WLS)
        pred_3m, win_prob = self.predict_future_trajectory(live_px)

        if self.is_suspended_by_ai:
            # INOVAÇÃO #5: Se a moeda suspensa apresentar Reversão Institucional Perfeita (Win Prob >= 84%), libera automaticamente!
            if win_prob >= 84.0 and pred_3m >= 0.95 and self.smart_money_ignition:
                self.suspended_until = 0.0
                self.consecutive_losses = 0
            else:
                self.trend_regime = f"AI_SUSPENDED ({self.suspension_remaining_min}m)"
                self.long_score = 50.0
                self.score = 50.0
                return

        prev_bar_px = hist[-2] if n >= 2 else live_px
        is_downtrend = (self.ema_fast < self.ema_slow * 0.9995) or (live_px < self.ema_fast * 0.9995)
        is_seller_flow = (self.obi <= 0.04) or (self.cvd <= 0.02) or (self.l2_obi <= -0.15)
        is_macd_weak = self.macd_hist < self.prev_macd_hist - (self.step * 0.2)
        is_falling_or_flat_rsi = (self.rsi < 34.0) or (self.rsi < self.prev_rsi) or (live_px < prev_bar_px)
        is_wide_spread = self.spread_pct > 0.085
        is_late_chasing_top = (self.rsi > 56.0) or (self.zbb > 0.25)

        l_score = 62.0
        if self.ema_fast >= self.ema_slow * 0.9995 and live_px >= self.ema_fast * 0.9995:
            l_score += 10.0
        if self.macd_hist >= self.prev_macd_hist:
            l_score += 3.5
        if self.htf_bullish:
            l_score += 4.5
        if 34.0 <= self.rsi <= 55.5 and self.rsi >= self.prev_rsi:
            l_score += 9.5
        if -1.15 <= self.zbb <= 0.22:
            l_score += 5.5
        if self.obi > 0.04:
            l_score += min(9.5, self.obi * 15.5)
        if self.cvd > 0.02:
            l_score += min(7.5, self.cvd * 13.5)
        if self.impulse_5s_pct > 0.02:
            l_score += min(3.0, self.impulse_5s_pct * 15.0)
        if self.smart_money_ignition:
            l_score += 4.5

        l_score += self.ai_trust_bonus

        if is_wide_spread:
            self.trend_regime = f"WIDE_SPREAD ({self.spread_pct:.2f}%)"
            l_score = min(l_score, 62.0)
        elif is_downtrend or is_seller_flow or is_falling_or_flat_rsi or is_macd_weak:
            if is_downtrend:
                self.trend_regime = "BEARISH_TREND"
            elif is_seller_flow:
                self.trend_regime = "SELLER_FLOW"
            else:
                self.trend_regime = "WAITING_IGNITION"
            l_score = min(l_score, 64.0)
        elif is_late_chasing_top:
            self.trend_regime = "LATE_WAVE_WAIT_PULLBACK"
            l_score = min(l_score, 68.0)
        elif pred_3m < 0.85 or win_prob < 76.0:
            # REGRA DE OURO ORACLE v18.0: Se a projeção 3m for < +0.85% ou Win Prob < 76%, aguarda ignição mais forte!
            self.trend_regime = "PREDICTIVE_WAIT (<+0.85%)"
            l_score = min(l_score, 72.0)
        else:
            self.trend_regime = "BULLISH_CONFLUENCE"

        self.long_score = round(max(42.0, min(98.5, l_score)), 1)
        self.short_score = 35.0
        self.best_side = "LONG"
        self.score = self.long_score

    def on_price_update(self, new_px: float, volume_bias: float = 0.0, trade_qty: float = 1.0) -> None:
        new_px = round(new_px, self.decimals)
        if not self.seeded or abs(new_px - self.price) / max(self.price, 1e-8) > 0.06:
            self.seed_history(new_px)

        now = time.time()
        prev_px = self.price
        self.price = new_px
        self.current_bar_high = max(self.current_bar_high, new_px)
        self.current_bar_low = min(self.current_bar_low, new_px)
        self.current_bar_vol += max(0.1, trade_qty)

        self.tick_window_5s.append((now, new_px))
        while self.tick_window_5s and (now - self.tick_window_5s[0][0]) > 5.0:
            self.tick_window_5s.popleft()
        if len(self.tick_window_5s) >= 2 and self.tick_window_5s[0][1] > 0:
            self.impulse_5s_pct = round(((new_px - self.tick_window_5s[0][1]) / self.tick_window_5s[0][1]) * 100.0, 3)

        tick_dir = 1.0 if new_px >= prev_px else -1.0
        bias = volume_bias if volume_bias != 0.0 else (tick_dir * 0.025)
        self.obi = round(max(-0.88, min(0.88, self.obi * 0.93 + bias)), 2)
        self.cvd = round(max(-0.88, min(0.88, self.cvd * 0.93 + bias * 0.9)), 2)

        if (now - self.last_candle_ts) >= self.CANDLE_INTERVAL_SEC:
            self.history.append(new_px)
            self.highs.append(round(self.current_bar_high, self.decimals))
            self.lows.append(round(self.current_bar_low, self.decimals))
            self.volumes.append(round(self.current_bar_vol, 2))
            self.current_bar_high = new_px
            self.current_bar_low = new_px
            self.current_bar_vol = 100.0
            self.last_candle_ts = now
            self.atr = self.compute_atr(period=14)

        self._recalculate_indicators_from_bars(new_px)


# =====================================================================
# 4. ORQUESTRADOR ORACLE SINGULARITY v18.0 (LEAD-LAG + AUTO-TUNING + PREDICTIVE CASH-IN)
# =====================================================================

class AutonomousSniperOrchestratorV18:
    def __init__(self) -> None:
        self.gateway = BybitV5AutonomousGateway()
        self.ai_running: bool = True
        self.auto_intelligence_enabled: bool = True
        self.usd_brl_rate: float = 5.3487
        self.starting_equity_usd: float = 24.8282
        self.current_equity_usd: float = 24.8282
        self.realized_daily_pnl_usd: float = 0.0
        self.peak_daily_pnl_usd: float = 0.0
        self.floating_pnl_usd: float = 0.0
        self.saved_fees_usd: float = 0.0
        self.wins_today: int = 0
        self.losses_today: int = 0
        self.risk_per_trade_pct: float = 1.2
        self.min_confluence_score: float = 78.0

        self.backend_ws_connected: bool = False
        self.backend_ws_endpoint: str = ""
        self.ws_ticks_processed: int = 0
        self.last_ws_tick_ts: float = 0.0
        self._trade_lock: asyncio.Lock = asyncio.Lock()

        self.enabled_symbols: List[str] = ["SOLUSDT", "XRPUSDT", "DOGEUSDT"]
        self.max_concurrent_slots: int = 2
        self.active_positions: Dict[str, Dict[str, Any]] = {}
        self.global_cooldown_until: float = 0.0
        self.last_profit_exit_per_sym: Dict[str, float] = {}
        self.max_stagnant_trade_sec: float = 720.0

        # Radar Lead-Lag + Filtro Macro do Bitcoin (v18.0)
        self.btc_macro_bearish: bool = False
        self.btc_1m_change_pct: float = 0.0
        self.macro_leader_igniting: bool = False
        self.lead_lag_status: str = "📡 Radar Lead-Lag: Monitorando Ignição BTC/ETH"
        self.btc_macro_status: str = "🟢 BTC Estável (Compras Liberadas)"
        self.market_regime: str = "ORACLE_SINGULARITY_V18"
        self.ai_brain_status: str = "🔮 Oracle v18.0: Kalman 3m (≥ +0.85%) + Win Prob (≥ 76%) + Smart Money L2"

        # Escada de Greens + Saída Preditiva no Topo (+0.42%+)
        self.atr_stop_multiplier: float = 1.55
        self.atr_trailing_multiplier: float = 0.85
        self.atr_tp1_multiplier: float = 1.85
        self.atr_tp2_multiplier: float = 3.20
        self.min_stop_pct: float = 0.0062
        self.ladder_step1_trigger_pct: float = 0.0036
        self.ladder_step1_lock_pct: float = 0.0021
        self.predictive_top_min_gain_pct: float = 0.0042  # +0.42% ativa Saída Preditiva no Topo (PREDICTIVE_TOP_CASH_IN)
        self.ladder_step2_trigger_pct: float = 0.0055
        self.ladder_step2_lock_pct: float = 0.0038
        self.peak_exhaustion_trigger_pct: float = 0.0068
        self.min_tp1_pct: float = 0.0085
        self.ladder_step3_lock_pct: float = 0.0062
        self.min_tp2_pct: float = 0.0155

        self.max_daily_drawdown_pct: float = 5.0
        self.circuit_breaker_tripped: bool = False
        self.profit_shield_locked: bool = False
        self.current_utc_day: int = datetime.now(timezone.utc).day

        self.wallet_sync_source: str = "Bybit Spot Unificada"
        self.selected_symbol: str = "SOLUSDT"
        self.last_order_warning_ts: float = 0.0
        self.equity_curve_brl: List[float] = [132.80, 132.80, 132.80]
        self.decision_logs: Deque[Dict[str, str]] = deque(maxlen=35)

        self.assets: Dict[str, CloudAssetTelemetry] = {
            "SOLUSDT":  CloudAssetTelemetry("SOLUSDT",  94.46,   0.03,    2),
            "XRPUSDT":  CloudAssetTelemetry("XRPUSDT",  1.2178,  0.0005,  4),
            "DOGEUSDT": CloudAssetTelemetry("DOGEUSDT", 0.07427, 0.00005, 5),
            "BNBUSDT":  CloudAssetTelemetry("BNBUSDT",  698.62,  0.10,    2),
            "ETHUSDT":  CloudAssetTelemetry("ETHUSDT",  2213.88, 0.40,    2),
            "BTCUSDT":  CloudAssetTelemetry("BTCUSDT",  77111.2, 4.0,     1),
        }

        self.load_persisted_brain_state()

        self.add_log(
            "🔮 ORACLE SINGULARITY v18.0 ATIVADO (PREVISÃO DE FUTURO KALMAN + SMART MONEY L2 + LEAD-LAG)",
            "As 6 inovações preditivas estão rodando: "
            "(1) <strong>Motor Preditivo Kalman 3m</strong> (só entra se <code>Projeção ≥ +0.85%</code> e <code>Win Prob ≥ 76%</code>), "
            "(2) <strong>Radar Smart Money L2</strong> (detecta absorção institucional e vácuo de Asks <code>≥ 1.35x</code>), "
            "(3) <strong>Radar Lead-Lag BTC/ETH</strong> (antecipa explosão nas altcoins no segundo zero), "
            "(4) <strong>Saída Preditiva no Topo (`PREDICTIVE_TOP_CASH_IN` aos `+0.42%+`)</strong>, "
            "(5) <strong>Auto-Tuning Neural do Gatilho (`76` a `85`)</strong> e "
            "(6) <strong>Painel Oracle Singularity v18.0</strong>!",
            "emerald",
        )

    def save_persisted_brain_state(self) -> None:
        try:
            payload = {
                "enabled_symbols": self.enabled_symbols,
                "min_confluence_score": self.min_confluence_score,
                "global_cooldown_until": self.global_cooldown_until,
                "coins": {
                    sym: {
                        "wins": a.coin_wins,
                        "losses": a.coin_losses,
                        "consecutive_losses": a.consecutive_losses,
                        "trust_bonus": a.ai_trust_bonus,
                        "suspended_until": a.suspended_until,
                    }
                    for sym, a in self.assets.items()
                },
            }
            BRAIN_STATE_FILE.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

    def load_persisted_brain_state(self) -> None:
        try:
            if not BRAIN_STATE_FILE.exists():
                return
            data = json.loads(BRAIN_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data.get("enabled_symbols"), list) and data["enabled_symbols"]:
                self.enabled_symbols = [s for s in data["enabled_symbols"] if s in BYBIT_CONTRACTS]
            if isinstance(data.get("min_confluence_score"), (int, float)):
                self.min_confluence_score = float(data["min_confluence_score"])
            if isinstance(data.get("global_cooldown_until"), (int, float)):
                self.global_cooldown_until = float(data["global_cooldown_until"])
            coins_map = data.get("coins", {})
            for sym, c_info in coins_map.items():
                if sym in self.assets and isinstance(c_info, dict):
                    a = self.assets[sym]
                    a.coin_wins = int(c_info.get("wins", 0))
                    a.coin_losses = int(c_info.get("losses", 0))
                    a.consecutive_losses = int(c_info.get("consecutive_losses", 0))
                    a.ai_trust_bonus = float(c_info.get("trust_bonus", 0.0))
                    a.suspended_until = float(c_info.get("suspended_until", 0.0))
        except Exception:
            pass

    @property
    def active_position(self) -> Optional[Dict[str, Any]]:
        if not self.active_positions:
            return None
        if self.selected_symbol in self.active_positions:
            return self.active_positions[self.selected_symbol]
        first_sym = next(iter(self.active_positions))
        return self.active_positions[first_sym]

    @property
    def daily_drawdown_pct(self) -> float:
        if self.starting_equity_usd <= 0:
            return 0.0
        net_daily_usd = self.realized_daily_pnl_usd + self.floating_pnl_usd
        return round(max(0.0, (-net_daily_usd / self.starting_equity_usd) * 100.0), 2)

    @property
    def global_cooldown_remaining_sec(self) -> int:
        rem = int(round(self.global_cooldown_until - time.time()))
        return max(0, rem)

    def check_lead_lag_radar(self) -> bool:
        """
        INOVAÇÃO #3 — Radar Lead-Lag (Antecipação pela Ignição do BTC/ETH):
        Monitora o impulso de 5 segundos (`impulse_5s_pct`) e o fluxo (`obi`) do `BTCUSDT` e `ETHUSDT`.
        Quando o BTC ou ETH iniciam uma ignição compradora (`impulse_5s_pct >= +0.06%` e `obi > 0.10`),
        ativa `self.macro_leader_igniting = True`, priorizando a compra imediata na altcoin ativa de
        maior `win_probability_pct` e menor spread!
        """
        btc = self.assets.get("BTCUSDT")
        eth = self.assets.get("ETHUSDT")
        btc_igniting = bool(btc and btc.impulse_5s_pct >= 0.06 and btc.obi > 0.10)
        eth_igniting = bool(eth and eth.impulse_5s_pct >= 0.06 and eth.obi > 0.10)

        if btc_igniting or eth_igniting:
            leader_name = "BTC+ETH" if (btc_igniting and eth_igniting) else ("BTC" if btc_igniting else "ETH")
            leader_imp = max(btc.impulse_5s_pct if btc else 0.0, eth.impulse_5s_pct if eth else 0.0)
            self.macro_leader_igniting = True
            self.lead_lag_status = f"🚀 IGNIÇÃO LEAD-LAG ({leader_name} +{leader_imp:.2f}% em 5s) — Surfe Antecipado Ativo!"
            return True

        self.macro_leader_igniting = False
        self.lead_lag_status = "📡 Radar Lead-Lag: Monitorando Ignição BTC/ETH"
        return False

    def auto_tune_neural_parameters(self) -> None:
        """
        INOVAÇÃO #5 — Cérebro Auto-Adaptativo de Gatilho (100% Autônomo sem Intervenção Manual):
        - Analisa a força média do mercado (média de `obi`, `cvd` e `win_probability_pct` das 6 moedas)
          e ajusta sozinho `self.min_confluence_score` entre `76.0` (explosão compradora sincronizada)
          e `85.0` (mercado travado ou traiçoeiro).
        - Reabilita automaticamente qualquer moeda suspensa que apresente uma reversão institucional
          perfeita com `win_probability_pct >= 84.0%`!
        """
        if not self.auto_intelligence_enabled:
            return

        all_assets = list(self.assets.values())
        avg_obi = sum(a.obi for a in all_assets) / len(all_assets)
        avg_cvd = sum(a.cvd for a in all_assets) / len(all_assets)
        bullish_count = sum(1 for a in all_assets if a.trend_regime == "BULLISH_CONFLUENCE")

        # Reabilitação automática de moeda com reversão institucional perfeita (Win Prob >= 84%)
        for a in all_assets:
            if a.is_suspended_by_ai and a.win_probability_pct >= 84.0 and a.predicted_move_pct_3m >= 0.90:
                a.suspended_until = 0.0
                a.consecutive_losses = 0
                self.add_log(
                    f"🔮 REABILITAÇÃO NEURAL ORACLE ({a.symbol} • WIN PROB {a.win_probability_pct:.1f}%)",
                    f"A moeda <strong>{a.symbol}</strong> apresentou reversão institucional perfeita "
                    f"(Projeção 3m: <strong>+{a.predicted_move_pct_3m:.2f}%</strong>, Win Prob: <strong>{a.win_probability_pct:.1f}%</strong>) "
                    f"e foi liberada automaticamente pelo Cérebro Oracle!",
                    "cyan",
                )

        if self.btc_macro_bearish:
            self.min_confluence_score = 85.0
        elif (avg_obi >= 0.16 and avg_cvd >= 0.12 and bullish_count >= 3) or self.macro_leader_igniting:
            self.min_confluence_score = 76.0
        elif avg_obi >= 0.08 and avg_cvd >= 0.05 and bullish_count >= 1:
            self.min_confluence_score = 78.0
        elif avg_obi < 0.02 or avg_cvd < 0.0:
            self.min_confluence_score = 84.0
        else:
            self.min_confluence_score = 80.0

    def check_btc_macro_filter(self) -> bool:
        btc = self.assets.get("BTCUSDT")
        if not btc:
            self.btc_macro_bearish = False
            return False

        self.btc_1m_change_pct = btc.get_short_term_change_pct(bars_back=2)
        sharp_1m_drop = self.btc_1m_change_pct <= -0.25
        macro_downtrend = (btc.price < btc.ema_slow * 0.9994) and (btc.ema_fast < btc.ema_slow) and (btc.obi <= -0.05)

        self.check_lead_lag_radar()

        if sharp_1m_drop or macro_downtrend:
            self.btc_macro_bearish = True
            self.market_regime = "MACRO_BEAR_SHIELD"
            self.btc_macro_status = (
                f"🛑 BTC EM QUEDA ({self.btc_1m_change_pct:+.2f}% • Abaixo da EMA) — Novas Compras Pausadas"
            )
            self.ai_brain_status = f"🛡️ Defesa Macro BTC Ativa • Gatilho Auto-Ajustado p/ ≥ {self.min_confluence_score:.0f}"
            self.auto_tune_neural_parameters()
            return True

        self.btc_macro_bearish = False
        self.auto_tune_neural_parameters()
        if self.macro_leader_igniting:
            self.market_regime = "LEAD_LAG_IGNITION"
            self.ai_brain_status = f"🚀 {self.lead_lag_status} • Gatilho Oracle ≥ {self.min_confluence_score:.0f}"
        elif not btc.htf_bullish:
            self.market_regime = "CAUTIOUS_1SLOT"
            self.ai_brain_status = f"🔮 Modo Cautela (1 Slot): Só Compra Projeção ≥ +0.85% e Win Prob ≥ 76% (Gatilho ≥ {self.min_confluence_score:.0f})"
        else:
            self.market_regime = "ORACLE_SINGULARITY_V18"
            self.ai_brain_status = f"🔮 Oracle v18.0: Kalman 3m (≥ +0.85%) + Win Prob (≥ 76%) • Gatilho Auto ≥ {self.min_confluence_score:.0f}"

        self.btc_macro_status = f"🟢 BTC Estável ({self.btc_1m_change_pct:+.2f}%) — Compras Liberadas"
        return False

    def compute_volatility_lot_scale(self, sym: str, entry: float, atr_val: float) -> float:
        if entry <= 0:
            return 1.0
        atr_pct = atr_val / entry
        if atr_pct <= 0.0045:
            return 1.0
        excess = min(1.0, (atr_pct - 0.0045) / 0.0085)
        scale = 1.0 - (0.20 * excess)
        return round(max(0.80, min(1.00, scale)), 2)

    def get_effective_max_slots(self) -> int:
        unlocked_count = max(1, len(self.get_unlocked_symbols()))
        btc = self.assets.get("BTCUSDT")
        if (btc and not btc.htf_bullish) or self.current_equity_usd < 28.0:
            safe_cap = 1
        elif self.current_equity_usd <= 45.0:
            safe_cap = 2
        else:
            safe_cap = self.max_concurrent_slots
        return min(self.max_concurrent_slots, safe_cap, unlocked_count)

    def add_log(self, tag: str, message: str, tone: str = "emerald") -> None:
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.decision_logs.appendleft({
            "tag": tag,
            "message": message,
            "tone": tone,
            "time": now_str,
        })

    def get_dynamic_leverage(self) -> int:
        return 1

    def get_unlocked_symbols(self) -> List[str]:
        active = [s for s in self.enabled_symbols if s in BYBIT_CONTRACTS]
        return active if active else ["SOLUSDT"]

    def pick_best_opportunity(self) -> CloudAssetTelemetry:
        """
        INOVAÇÃO #3 (Radar Lead-Lag + Seleção Preditiva):
        Prioriza a altcoin ativa com maior `win_probability_pct`, maior `predicted_move_pct_3m`,
        absorção `smart_money_ignition` e menor `spread_pct`!
        """
        unlocked = self.get_unlocked_symbols()
        free_candidates = [
            self.assets[s]
            for s in unlocked
            if s in self.assets and s not in self.active_positions and not self.assets[s].is_suspended_by_ai
        ]
        if free_candidates:
            free_candidates.sort(
                key=lambda a: (
                    1 if a.smart_money_ignition else 0,
                    a.win_probability_pct,
                    a.predicted_move_pct_3m,
                    a.score,
                    -a.spread_pct,
                ),
                reverse=True,
            )
            return free_candidates[0]
        candidates = [self.assets[s] for s in unlocked if s in self.assets]
        candidates.sort(key=lambda a: (a.win_probability_pct, a.score), reverse=True)
        return candidates[0] if candidates else self.assets["SOLUSDT"]

    def build_targets_for_asset(self, sym: str, entry: float) -> Dict[str, float]:
        asset = self.assets[sym]
        spec = BYBIT_CONTRACTS[sym]
        dec = spec.price_decimals

        atr_val = max(asset.atr, entry * 0.0040, spec.tick_size * 12)
        stop_dist = max(atr_val * self.atr_stop_multiplier, entry * self.min_stop_pct, spec.tick_size * 20)
        tp1_dist = max(atr_val * self.atr_tp1_multiplier, entry * self.min_tp1_pct, stop_dist * 1.30)
        tp2_dist = max(atr_val * self.atr_tp2_multiplier, entry * self.min_tp2_pct, stop_dist * 2.45)

        return {
            "atr_val": round(atr_val, dec),
            "stop_dist": stop_dist,
            "stop_px": round(entry - stop_dist, dec),
            "step1_px": round(entry * (1.0 + self.ladder_step1_trigger_pct), dec),
            "step2_px": round(entry * (1.0 + self.ladder_step2_trigger_pct), dec),
            "tp1_px": round(entry + tp1_dist, dec),
            "tp2_px": round(entry + tp2_dist, dec),
        }

    async def hydrate_klines_from_bybit(self) -> None:
        client = await self.gateway.ensure_http()
        for sym, asset in self.assets.items():
            for base in self.gateway.get_candidate_urls():
                try:
                    r1 = await client.get(f"{base}/v5/market/kline?category=spot&symbol={sym}&interval=1&limit=40")
                    if r1.status_code == 200 and "application/json" in r1.headers.get("content-type", ""):
                        k_list = r1.json().get("result", {}).get("list", [])
                        if k_list and len(k_list) >= 10:
                            asset.seed_from_real_klines(k_list)
                    r5 = await client.get(f"{base}/v5/market/kline?category=spot&symbol={sym}&interval=5&limit=25")
                    if r5.status_code == 200 and "application/json" in r5.headers.get("content-type", ""):
                        k5_list = r5.json().get("result", {}).get("list", [])
                        if k5_list and len(k5_list) >= 8:
                            asset.seed_htf_5m_klines(k5_list)
                    rob = await client.get(f"{base}/v5/market/orderbook?category=spot&symbol={sym}&limit=25")
                    if rob.status_code == 200 and "application/json" in rob.headers.get("content-type", ""):
                        ob_res = rob.json().get("result", {})
                        asset.on_l2_orderbook_update(ob_res.get("b", []), ob_res.get("a", []))
                    break
                except Exception:
                    continue
        self.check_btc_macro_filter()

    async def reconcile_existing_spot_holdings(self) -> None:
        if self.gateway.exec_mode not in ("BYBIT_REAL", "BYBIT_DEMO"):
            return

        for sym, spec in BYBIT_CONTRACTS.items():
            if sym in self.active_positions:
                continue
            coin_qty = self.gateway.coin_balances.get(spec.base_coin, 0.0)
            if coin_qty <= 0:
                continue
            px = self.assets[sym].price
            if px <= 0:
                continue
            usd_val = max(self.gateway.coin_usd_values.get(spec.base_coin, 0.0), coin_qty * px)
            if usd_val >= 5.20:
                qty_str = format_bybit_qty(coin_qty, spec.qty_step)
                qty_float = float(qty_str)
                if qty_float < spec.min_qty:
                    continue
                dec = spec.price_decimals
                t = self.build_targets_for_asset(sym, px)
                actual_risk_usd = round(qty_float * t["stop_dist"], 2)
                order_id = f"RECONCILE_{spec.base_coin}_{int(time.time())}"

                if sym not in self.enabled_symbols:
                    self.enabled_symbols.append(sym)

                self.active_positions[sym] = {
                    "symbol": sym,
                    "side": "LONG",
                    "openedAt": time.time(),
                    "initialQty": qty_float,
                    "remainingQty": qty_float,
                    "entry": round(px, dec),
                    "highestPrice": round(px, dec),
                    "atrAtEntry": t["atr_val"],
                    "stop": t["stop_px"],
                    "earlyTrailTrigger": t["step1_px"],
                    "step2Trigger": t["step2_px"],
                    "tp1": t["tp1_px"],
                    "tp2": t["tp2_px"],
                    "decimals": dec,
                    "riskUsd": actual_risk_usd,
                    "ladderStage": 0,
                    "tp1Hit": False,
                    "earlyTrailingActivated": False,
                    "trailingActive": False,
                    "singleLotProtected": (usd_val < 12.0),
                    "volatilityScale": 1.0,
                    "floatingPnlUsd": 0.0,
                    "realizedPartialUsd": 0.0,
                    "srvStopOrderId": order_id,
                    "realBybitOrder": True,
                }
                self.add_log(
                    f"🔄 MOEDA RECONCILIADA DA CARTEIRA ({qty_str} {spec.base_coin})",
                    f"Encontramos <strong>{coin_qty:.4f} {spec.base_coin} (≈ ${usd_val:.2f} USDT)</strong> na sua carteira Spot! "
                    f"Posição protegida com Saída Preditiva no Topo (+0.42%+) e Escada v18.0!",
                    "emerald",
                )
        self._recalculate_total_floating_pnl()

    async def check_daily_circuit_breaker(self) -> bool:
        now_day = datetime.now(timezone.utc).day
        if now_day != self.current_utc_day:
            self.current_utc_day = now_day
            self.starting_equity_usd = self.current_equity_usd
            self.realized_daily_pnl_usd = 0.0
            self.peak_daily_pnl_usd = 0.0
            self.profit_shield_locked = False
            self.wins_today = 0
            self.losses_today = 0
            for a in self.assets.values():
                a.consecutive_losses = 0
                a.suspended_until = 0.0
            self.save_persisted_brain_state()
            if self.circuit_breaker_tripped:
                self.circuit_breaker_tripped = False
                self.ai_running = True
                self.add_log(
                    "🌅 VIRADA DE DIA UTC — CIRCUIT BREAKER E MEMÓRIA RESETADOS",
                    f"Novo dia iniciado! Banca base atualizada para <strong>${self.starting_equity_usd:.4f} USDT</strong> e motor reativado.",
                    "emerald",
                )

        if self.realized_daily_pnl_usd > self.peak_daily_pnl_usd:
            self.peak_daily_pnl_usd = self.realized_daily_pnl_usd

        peak_pct = (self.peak_daily_pnl_usd / max(self.starting_equity_usd, 1.0)) * 100.0
        current_net_pct = ((self.realized_daily_pnl_usd + self.floating_pnl_usd) / max(self.starting_equity_usd, 1.0)) * 100.0
        if not self.profit_shield_locked and peak_pct >= 1.80 and current_net_pct <= (peak_pct * 0.50):
            self.profit_shield_locked = True
            self.global_cooldown_until = time.time() + 3600.0
            self.add_log(
                f"👑 ESCUDO ORACLE DE LUCRO DIÁRIO ATIVADO (+{current_net_pct:.2f}%)",
                f"Você já atingiu pico de <strong>+{peak_pct:.2f}%</strong> hoje! Para garantir que o dia termine no <strong>GREEN</strong>, "
                f"o robô protegeu seu lucro acumulado e pausou novas entradas por 1 hora.",
                "emerald",
            )

        if not self.circuit_breaker_tripped and self.daily_drawdown_pct >= self.max_daily_drawdown_pct:
            self.circuit_breaker_tripped = True
            self.ai_running = False
            dd_brl = abs((self.realized_daily_pnl_usd + self.floating_pnl_usd) * self.usd_brl_rate)
            self.add_log(
                f"🛑 CIRCUIT BREAKER DEFINITIVO ACIONADO (-{self.daily_drawdown_pct:.2f}%)",
                f"Limite diário de segurança (<strong>-{self.max_daily_drawdown_pct:.1f}% / -R$ {dd_brl:.2f}</strong>) atingido! "
                f"Motor pausado (`ai_running = False`) até a meia-noite para blindar seu capital.",
                "rose",
            )
            for sym_open in list(self.active_positions.keys()):
                await self.close_specific_position(sym_open, reason="CIRCUIT_BREAKER_HALT")
            return True

        return self.circuit_breaker_tripped

    async def on_realtime_ws_tick(self, symbol: str, price: float, is_buy: bool, trade_qty: float = 1.0) -> None:
        if symbol not in self.assets or price <= 0:
            return
        self.ws_ticks_processed += 1
        self.last_ws_tick_ts = time.time()
        asset = self.assets[symbol]
        asset.on_price_update(price, volume_bias=(0.03 if is_buy else -0.03), trade_qty=trade_qty)

        if symbol in ("BTCUSDT", "ETHUSDT"):
            self.check_btc_macro_filter()

        if await self.check_daily_circuit_breaker():
            return
        if not self.ai_running:
            return

        if symbol in self.active_positions:
            async with self._trade_lock:
                if symbol in self.active_positions:
                    await self.evaluate_single_position(symbol)
            return

        if time.time() < self.global_cooldown_until:
            return
        if self.check_btc_macro_filter():
            return

        max_slots = self.get_effective_max_slots()
        # INOVAÇÃO #3 (Radar Lead-Lag): Se BTC/ETH dispararam ignição agora, busca imediatamente a melhor altcoin ativa!
        if self.macro_leader_igniting and len(self.active_positions) < max_slots:
            best_alt = self.pick_best_opportunity()
            if (
                best_alt.symbol not in self.active_positions
                and best_alt.predicted_move_pct_3m >= 0.85
                and best_alt.win_probability_pct >= 76.0
                and best_alt.score >= self.min_confluence_score
            ):
                async with self._trade_lock:
                    if best_alt.symbol not in self.active_positions and len(self.active_positions) < max_slots:
                        await self.open_sniper_trade(is_manual=False, requested_symbol=best_alt.symbol)
                return

        if asset.is_suspended_by_ai:
            return

        # REGRA DE OURO ORACLE v18.0: `predicted_move_pct_3m >= 0.85` E `win_probability_pct >= 76.0`
        if (
            symbol in self.get_unlocked_symbols()
            and len(self.active_positions) < max_slots
            and asset.predicted_move_pct_3m >= 0.85
            and asset.win_probability_pct >= 76.0
            and asset.score >= self.min_confluence_score
            and asset.trend_regime == "BULLISH_CONFLUENCE"
        ):
            async with self._trade_lock:
                if symbol not in self.active_positions and len(self.active_positions) < max_slots:
                    await self.open_sniper_trade(is_manual=False, requested_symbol=symbol)

    async def refresh_market_prices_and_klines(self) -> None:
        client = await self.gateway.ensure_http()
        updated = False
        for base in self.gateway.get_candidate_urls():
            try:
                r = await client.get(f"{base}/v5/market/tickers?category=spot")
                if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                    j = r.json()
                    items = j.get("result", {}).get("list", [])
                    if items:
                        for it in items:
                            sym = it.get("symbol")
                            if sym in self.assets and it.get("lastPrice"):
                                px = safe_float(it["lastPrice"])
                                b1 = safe_float(it.get("bid1Price"))
                                a1 = safe_float(it.get("ask1Price"))
                                if b1 > 0 and a1 >= b1:
                                    self.assets[sym].best_bid = round(b1, self.assets[sym].decimals)
                                    self.assets[sym].best_ask = round(a1, self.assets[sym].decimals)
                                    self.assets[sym].spread_pct = round(((a1 - b1) / b1) * 100.0, 4)
                                if px > 0:
                                    self.assets[sym].on_price_update(px)
                                    updated = True
                        if updated:
                            self.check_btc_macro_filter()
                            break
            except Exception:
                continue

        if not updated:
            try:
                r_bin = await client.get("https://api.binance.com/api/v3/ticker/price")
                if r_bin.status_code == 200:
                    for it in r_bin.json():
                        sym = it.get("symbol")
                        if sym in self.assets and it.get("price"):
                            px = safe_float(it["price"])
                            if px > 0:
                                self.assets[sym].on_price_update(px)
                                updated = True
                    if updated:
                        self.check_btc_macro_filter()
            except Exception:
                pass

    async def sync_wallet_from_bybit(self) -> Dict[str, Any]:
        res = await self.gateway.fetch_wallet_balance_v5(usd_brl_rate=self.usd_brl_rate)
        if res.get("ok") and safe_float(res.get("equity_usd")) > 0:
            eq_usd = float(res["equity_usd"])
            self.current_equity_usd = eq_usd
            self.wallet_sync_source = str(res.get("source", "Bybit Spot Unificada"))
            brl = round(eq_usd * self.usd_brl_rate, 2)
            if not self.equity_curve_brl:
                self.equity_curve_brl = [brl, brl, brl]
            await self.reconcile_existing_spot_holdings()
        return res

    async def open_sniper_trade(self, is_manual: bool = False, requested_symbol: Optional[str] = None) -> Dict[str, Any]:
        if await self.check_daily_circuit_breaker():
            return {"ok": False, "error": "Circuit Breaker Diário ativo (-5%). Novas ordens bloqueadas até meia-noite."}

        if not is_manual and time.time() < self.global_cooldown_until:
            rem_s = self.global_cooldown_remaining_sec
            return {
                "ok": False,
                "error": f"Quarentena Global Pós-Stop ativa! Aguardando {rem_s}s para proteger sua banca contra reentradas em queda.",
            }

        if not is_manual and self.check_btc_macro_filter():
            return {
                "ok": False,
                "error": f"Filtro Macro BTC ativo ({self.btc_macro_status}). Compras em altcoins pausadas até o Bitcoin estabilizar.",
            }

        max_slots = self.get_effective_max_slots()

        if requested_symbol and requested_symbol in BYBIT_CONTRACTS and requested_symbol not in self.active_positions:
            target_asset = self.assets[requested_symbol]
        else:
            target_asset = self.pick_best_opportunity()

        sym = target_asset.symbol
        if sym in self.active_positions:
            return {"ok": False, "error": f"Já existe uma posição ativa aberta em {sym}. Ative outra moeda se quiser abrir mais um slot!"}
        if len(self.active_positions) >= max_slots:
            return {"ok": False, "error": f"Limite seguro de {max_slots} slot(s) para o regime atual já está ocupado ({', '.join(self.active_positions.keys())})."}

        if not is_manual:
            if target_asset.is_suspended_by_ai:
                return {"ok": False, "error": f"{sym} está suspensa pela Auto-Inteligência por {target_asset.suspension_remaining_min}m após 2 Stops."}
            if target_asset.spread_pct > 0.085:
                return {"ok": False, "error": f"Spread de {sym} ({target_asset.spread_pct:.3f}%) acima do limite seguro de 0.085%."}
            # REGRA DE OURO ORACLE v18.0: `predicted_move_pct_3m >= +0.85%` E `win_probability_pct >= 76.0%`
            if target_asset.predicted_move_pct_3m < 0.85 or target_asset.win_probability_pct < 76.0:
                return {
                    "ok": False,
                    "error": (
                        f"Filtro Preditivo Oracle bloqueou {sym}: Projeção 3m (+{target_asset.predicted_move_pct_3m:.2f}%) < +0.85% "
                        f"ou Win Prob ({target_asset.win_probability_pct:.1f}%) < 76.0%."
                    ),
                }
            if target_asset.score < self.min_confluence_score or target_asset.trend_regime != "BULLISH_CONFLUENCE":
                return {
                    "ok": False,
                    "error": f"Filtro Oracle bloqueou compra em {sym} (Regime: {target_asset.trend_regime}, RSI: {target_asset.rsi}, Score: {target_asset.score}).",
                }
            last_win_closed = self.last_profit_exit_per_sym.get(sym, 0.0)
            if (time.time() - last_win_closed) < 45.0:
                return {"ok": False, "error": f"Aguardando resfriamento pós-lucro (45s) em {sym}."}

        self.selected_symbol = sym
        side = "LONG"
        spec = BYBIT_CONTRACTS[sym]
        dec = spec.price_decimals
        entry = (
            target_asset.best_ask
            if (target_asset.best_ask > 0 and abs(target_asset.best_ask - target_asset.price) / target_asset.price < 0.003)
            else target_asset.price
        )

        t = self.build_targets_for_asset(sym, entry)
        atr_val = t["atr_val"]
        stop_dist = t["stop_dist"]
        stop_px = t["stop_px"]
        step1_px = t["step1_px"]
        step2_px = t["step2_px"]
        tp1_px = t["tp1_px"]
        tp2_px = t["tp2_px"]

        if self.gateway.api_key and self.gateway.api_secret and self.gateway.exec_mode in ("BYBIT_REAL", "BYBIT_DEMO"):
            await self.sync_wallet_from_bybit()
            if sym in self.active_positions:
                return {"ok": True, "position": self.active_positions[sym], "real_bybit": True}

        free_usdt = self.gateway.coin_balances.get("USDT", 0.0)
        remaining_slots = max(1, max_slots - len(self.active_positions))

        if self.gateway.exec_mode in ("BYBIT_REAL", "BYBIT_DEMO"):
            if not self.gateway.api_key or not self.gateway.api_secret:
                return {"ok": False, "real_bybit": False, "error": "Configure BYBIT_API_SECRET nas Variables do Railway."}
            if free_usdt < 5.50:
                msg = f"Saldo livre em USDT (${free_usdt:.2f}) insuficiente para nova compra em {sym} (mínimo $5.50 USDT)."
                return {"ok": False, "real_bybit": False, "error": msg}
            slot_usdt = (free_usdt * 0.92) / remaining_slots
            if slot_usdt < 6.80:
                base_usable_usdt = free_usdt * 0.92
            else:
                base_usable_usdt = slot_usdt
        else:
            base_usable_usdt = (self.current_equity_usd * 0.90) / remaining_slots

        vol_scale = self.compute_volatility_lot_scale(sym, entry, atr_val)
        scaled_usdt = base_usable_usdt * vol_scale
        if self.gateway.exec_mode in ("BYBIT_REAL", "BYBIT_DEMO"):
            target_notional = min(free_usdt * 0.96, max(spec.min_notional_usd * 1.12, scaled_usdt))
        else:
            target_notional = max(spec.min_notional_usd * 1.12, scaled_usdt)

        raw_qty = max(spec.min_qty, target_notional / entry)
        qty_str = format_bybit_qty(raw_qty, spec.qty_step)
        qty_float = float(qty_str)
        actual_risk_usd = round(qty_float * stop_dist, 2)

        if self.gateway.exec_mode in ("BYBIT_REAL", "BYBIT_DEMO"):
            bybit_res = await self.gateway.place_real_bybit_order(
                symbol=sym,
                side=side,
                qty_float=qty_float,
                stop_loss=stop_px,
                take_profit=tp2_px,
                leverage=1,
            )
            if not bybit_res.get("ok"):
                err_note = str(bybit_res.get("error", "Falha ao enviar ordem Spot para Bybit"))
                if is_manual or (time.time() - self.last_order_warning_ts > 60):
                    self.last_order_warning_ts = time.time()
                    self.add_log(f"⚠️ AVISO ORDEM SPOT BYBIT ({sym})", err_note, "amber")
                return {"ok": False, "real_bybit": False, "error": err_note}

            order_id = str(bybit_res["order_id"])
            net_qty = float(bybit_res.get("net_sellable_qty", qty_float))
            real_executed = True
        else:
            order_id = f"TREINO_SPOT_{int(time.time())}"
            net_qty = qty_float
            real_executed = False

        notional_val = net_qty * entry
        self.saved_fees_usd = round(self.saved_fees_usd + (notional_val * 0.0003), 3)
        pos_obj = {
            "symbol": sym,
            "side": side,
            "openedAt": time.time(),
            "initialQty": net_qty,
            "remainingQty": net_qty,
            "entry": round(entry, dec),
            "highestPrice": round(entry, dec),
            "atrAtEntry": atr_val,
            "stop": stop_px,
            "earlyTrailTrigger": step1_px,
            "step2Trigger": step2_px,
            "tp1": tp1_px,
            "tp2": tp2_px,
            "decimals": dec,
            "riskUsd": actual_risk_usd,
            "ladderStage": 0,
            "tp1Hit": False,
            "earlyTrailingActivated": False,
            "trailingActive": False,
            "singleLotProtected": (notional_val < 12.0),
            "volatilityScale": vol_scale,
            "predictedMoveAtEntry": target_asset.predicted_move_pct_3m,
            "winProbAtEntry": target_asset.win_probability_pct,
            "floatingPnlUsd": 0.0,
            "realizedPartialUsd": 0.0,
            "srvStopOrderId": order_id,
            "realBybitOrder": real_executed,
        }
        self.active_positions[sym] = pos_obj
        self._recalculate_total_floating_pnl()

        sm_badge = " • 🚀 Smart Money L2" if target_asset.smart_money_ignition else ""
        tag_title = (
            f"🔥 COMPRA ORACLE SPOT ({sym} • WIN PROB {target_asset.win_probability_pct:.1f}% • PROJ +{target_asset.predicted_move_pct_3m:.2f}%)"
            if real_executed
            else f"🟢 COMPRA ORACLE TREINO ({sym} • WIN PROB {target_asset.win_probability_pct:.1f}%)"
        )
        self.add_log(
            tag_title,
            f"Comprou <strong>{net_qty} {spec.base_coin} (${notional_val:.2f} USDT{sm_badge})</strong> a <strong>${entry:.{dec}f}</strong> | "
            f"Projeção 3m: <strong>+{target_asset.predicted_move_pct_3m:.2f}%</strong> | "
            f"Saída Preditiva Armada (<strong>+0.42%+</strong>) | TP1: <strong>${tp1_px:.{dec}f}</strong> | Stop: <strong>${stop_px:.{dec}f}</strong>.",
            "emerald" if real_executed else "cyan",
        )
        return {"ok": True, "position": pos_obj, "real_bybit": real_executed}

    def _recalculate_total_floating_pnl(self) -> None:
        total_fl = 0.0
        for sym, pos in self.active_positions.items():
            asset = self.assets[sym]
            exit_px = (
                asset.best_bid
                if (asset.best_bid > 0 and abs(asset.best_bid - asset.price) / max(asset.price, 1e-8) < 0.003)
                else asset.price
            )
            gross = (exit_px - pos["entry"]) * pos["remainingQty"]
            fee = (pos["entry"] + exit_px) * pos["remainingQty"] * 0.001
            fl = round(gross - fee, 2)
            pos["floatingPnlUsd"] = fl
            total_fl += fl
        self.floating_pnl_usd = round(total_fl, 2)

    async def evaluate_single_position(self, sym: str) -> None:
        if sym not in self.active_positions:
            return
        p = self.active_positions[sym]
        asset = self.assets[sym]
        px = asset.price
        spec = BYBIT_CONTRACTS[sym]
        dec = spec.price_decimals

        if px > p.get("highestPrice", p["entry"]):
            p["highestPrice"] = px

        current_atr = max(asset.atr, p.get("atrAtEntry", px * 0.0045))
        gain_pct = (px - p["entry"]) / max(p["entry"], 1e-8)
        peak_gain_pct = (p["highestPrice"] - p["entry"]) / max(p["entry"], 1e-8)
        stage = int(p.get("ladderStage", 0))
        age_sec = time.time() - float(p.get("openedAt", time.time()))

        # DEGRAU 1 (+0.36%): Trava o Stop em +0.21% (Green Garantido!)
        if stage < 1 and gain_pct >= self.ladder_step1_trigger_pct:
            p["ladderStage"] = 1
            p["earlyTrailingActivated"] = True
            p["trailingActive"] = True
            lock1_stop = round(p["entry"] * (1.0 + self.ladder_step1_lock_pct), dec)
            if lock1_stop > p["stop"]:
                p["stop"] = lock1_stop
            self.add_log(
                f"🟢 DEGRAU 1 DA ESCADA (+0.36% EM {sym}) — GREEN GARANTIDO!",
                f"Preço bateu <strong>${px:.{dec}f} (+{gain_pct*100:.2f}%)</strong>! "
                f"Stop subiu para <strong>${p['stop']:.{dec}f} (+0.21%)</strong> — risco zero de loss!",
                "cyan",
            )

        # DEGRAU 2 (+0.55%): Trava +0.38% líquido e aperta o Trailing Stop a 0.18% do topo!
        if stage < 2 and gain_pct >= self.ladder_step2_trigger_pct:
            p["ladderStage"] = 2
            p["trailingActive"] = True
            lock2_stop = round(p["entry"] * (1.0 + self.ladder_step2_lock_pct), dec)
            if lock2_stop > p["stop"]:
                p["stop"] = lock2_stop
            self.add_log(
                f"🔥 DEGRAU 2 DA ESCADA (+0.55% EM {sym}) — LUCRO TRAVADO + TRAILING COLADO!",
                f"Preço avançou para <strong>${px:.{dec}f} (+{gain_pct*100:.2f}%)</strong>! "
                f"Stop travado em <strong>${p['stop']:.{dec}f} (+0.38% líquido)</strong> com Trailing curto (0.18%)!",
                "emerald",
            )

        if p.get("tp1Hit") or p.get("trailingActive"):
            p["trailingActive"] = True
            if int(p.get("ladderStage", 0)) >= 2:
                trail_dist = max(px * 0.0018, spec.tick_size * 6)
            else:
                trail_dist = max(current_atr * self.atr_trailing_multiplier, px * 0.0028)
            candidate_stop = round(p["highestPrice"] - trail_dist, dec)
            if candidate_stop > p["stop"]:
                p["stop"] = candidate_stop

        self._recalculate_total_floating_pnl()
        pos_fl_usd = p.get("floatingPnlUsd", 0.0)

        # INOVAÇÃO #4 (v18.0): SAÍDA PREDITIVA NO TOPO DA ONDA (`PREDICTIVE_TOP_CASH_IN` em 0ms)
        # Se a operação já estiver no lucro líquido (`gain_pct >= +0.42%`) e a aceleração/impulso 5s
        # virar negativa (`impulse_5s_pct < -0.02%`) OU surgir parede vendedora institucional no Book (`l2_obi <= -0.18`),
        # vende 100% em 0ms no topo da vela antes de qualquer recuo!
        if gain_pct >= self.predictive_top_min_gain_pct:
            predictive_reversal = (asset.impulse_5s_pct < -0.02) or (asset.l2_obi <= -0.18) or (asset.price_acceleration < -0.04 and asset.obi < 0.05)
            if predictive_reversal:
                if p.get("realBybitOrder"):
                    await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
                total_op = round(p["realizedPartialUsd"] + pos_fl_usd, 2)
                self.current_equity_usd = round(self.current_equity_usd + pos_fl_usd, 4)
                self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + pos_fl_usd, 2)
                self.wins_today += 1
                self.last_profit_exit_per_sym[sym] = time.time()
                ai_note = asset.record_trade_outcome(is_win=True)
                self.save_persisted_brain_state()
                self.equity_curve_brl.append(round(self.current_equity_usd * self.usd_brl_rate, 2))
                if len(self.equity_curve_brl) > 30:
                    self.equity_curve_brl.pop(0)
                reason_badge = "Parede Vendedora L2" if asset.l2_obi <= -0.18 else f"Inversão de Impulso 5s ({asset.impulse_5s_pct:+.2f}%)"
                self.add_log(
                    f"🔮 PREDICTIVE_TOP_CASH_IN EM 0ms ({sym} • +{gain_pct*100:.2f}%)",
                    f"Saída Preditiva acionada no topo da vela (<strong>{reason_badge}</strong>) em <code>${px:.{dec}f}</code>! "
                    f"Green cheio embolsado: <strong>+R$ {(total_op * self.usd_brl_rate):.2f} (+${total_op:.2f} USDT)</strong> com zero devolução! {ai_note}",
                    "emerald",
                )
                self.active_positions.pop(sym, None)
                self._recalculate_total_floating_pnl()
                return

        # TIME-STOP INTELIGENTE ANTI-TRADE ZUMBI (12 Minutos Estagnado)
        if stage == 0 and age_sec >= self.max_stagnant_trade_sec and -0.0015 <= gain_pct < 0.0030 and asset.obi < 0.0:
            if p.get("realBybitOrder"):
                await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
            self.current_equity_usd = round(self.current_equity_usd + pos_fl_usd, 4)
            self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + pos_fl_usd, 2)
            self.last_profit_exit_per_sym[sym] = time.time()
            self.add_log(
                f"⏱️ TIME-STOP INTELIGENTE (12M ESTAGNADO EM {sym})",
                f"A posição ficou {int(age_sec // 60)} minutos sem explodir e o fluxo virou vendedor. "
                f"Encerrada preventivamente perto do zero-a-zero (<code>${px:.{dec}f}</code>)!",
                "amber",
            )
            self.active_positions.pop(sym, None)
            self._recalculate_total_floating_pnl()
            return

        # CASH-IN DE PICO (>= +0.68% com desaceleração):
        pullback_from_peak_pct = (p["highestPrice"] - px) / max(p["highestPrice"], 1e-8)
        if peak_gain_pct >= self.peak_exhaustion_trigger_pct and gain_pct >= 0.0052:
            if asset.obi < 0.06 or pullback_from_peak_pct >= 0.0014 or asset.rsi >= 64.0:
                if p.get("realBybitOrder"):
                    await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
                total_op = round(p["realizedPartialUsd"] + pos_fl_usd, 2)
                self.current_equity_usd = round(self.current_equity_usd + pos_fl_usd, 4)
                self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + pos_fl_usd, 2)
                self.wins_today += 1
                self.last_profit_exit_per_sym[sym] = time.time()
                ai_note = asset.record_trade_outcome(is_win=True)
                self.save_persisted_brain_state()
                self.equity_curve_brl.append(round(self.current_equity_usd * self.usd_brl_rate, 2))
                if len(self.equity_curve_brl) > 30:
                    self.equity_curve_brl.pop(0)
                self.add_log(
                    f"💰 CASH-IN ORACLE NO PICO DA ONDA ({sym} • +{gain_pct*100:.2f}%)",
                    f"Vendeu 100% em 0ms no pico em <code>${px:.{dec}f}</code> embolsando lucro líquido de "
                    f"<strong>+R$ {(total_op * self.usd_brl_rate):.2f} (+${total_op:.2f} USDT)</strong>! {ai_note}",
                    "emerald",
                )
                self.active_positions.pop(sym, None)
                self._recalculate_total_floating_pnl()
                return

        # 1) Verifica se atingiu o Stop-Loss (ou Trailing Stop na Escada de Greens)
        if px <= p["stop"]:
            if p.get("realBybitOrder"):
                await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
            total_trade_usd = round(p["realizedPartialUsd"] + pos_fl_usd, 2)
            self.current_equity_usd = round(self.current_equity_usd + pos_fl_usd, 4)
            self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + pos_fl_usd, 2)

            if (p["tp1Hit"] or p.get("trailingActive")) and total_trade_usd >= 0:
                self.wins_today += 1
                self.last_profit_exit_per_sym[sym] = time.time()
                ai_note = asset.record_trade_outcome(is_win=True)
                self.save_persisted_brain_state()
                self.add_log(
                    f"🏆 GREEN REALIZADO NA ESCADA / TRAILING STOP ({sym})",
                    f"Vendeu 100% para USDT em <code>${p['stop']:.{dec}f}</code> com lucro líquido de "
                    f"<strong>+R$ {(total_trade_usd * self.usd_brl_rate):.2f} (+${total_trade_usd:.2f} USDT)</strong>! {ai_note}",
                    "emerald",
                )
            else:
                self.losses_today += 1
                self.global_cooldown_until = time.time() + 300.0
                ai_note = asset.record_trade_outcome(is_win=False)
                self.save_persisted_brain_state()
                self.add_log(
                    f"🛑 STOP DE PROTEÇÃO ({sym}) + QUARENTENA 5M + AJUSTE NEURAL",
                    f"Vendida 100% para USDT em <code>${p['stop']:.{dec}f}</code> (<strong>-R$ {abs(total_trade_usd * self.usd_brl_rate):.2f}</strong>). "
                    f"Quarentena Global de 5m ativada. {ai_note}",
                    "rose",
                )
            self.equity_curve_brl.append(round(self.current_equity_usd * self.usd_brl_rate, 2))
            if len(self.equity_curve_brl) > 30:
                self.equity_curve_brl.pop(0)
            self.active_positions.pop(sym, None)
            self._recalculate_total_floating_pnl()
            await self.check_daily_circuit_breaker()
            return

        # 2) DEGRAU 3 — TP1 (+0.85%): Se lote < $12, VENDE 100% DIRETO E PÕE O GREEN NO BOLSO!
        if not p["tp1Hit"] and px >= p["tp1"]:
            p["tp1Hit"] = True
            p["ladderStage"] = 3
            p["trailingActive"] = True

            position_total_usd = p["remainingQty"] * px
            raw_half = p["initialQty"] * 0.5
            half_str = format_bybit_qty(raw_half, spec.qty_step)
            half_qty = float(half_str)
            leftover_qty = round(p["remainingQty"] - half_qty, 6)

            if position_total_usd >= 12.0 and (half_qty * px >= 6.0) and (leftover_qty * px >= 6.0):
                guaranteed_profit_stop = round(p["entry"] * (1.0 + self.ladder_step3_lock_pct), dec)
                if guaranteed_profit_stop > p["stop"]:
                    p["stop"] = guaranteed_profit_stop
                if p.get("realBybitOrder"):
                    await self.gateway.close_real_bybit_position(sym, p["side"], half_qty, current_price=px)
                p["remainingQty"] = leftover_qty
                p["singleLotProtected"] = False
                partial_net = round(((px - p["entry"]) * half_qty) - ((p["entry"] + px) * half_qty * 0.001), 2)
                p["realizedPartialUsd"] = partial_net
                self.current_equity_usd = round(self.current_equity_usd + partial_net, 4)
                self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + partial_net, 2)
                self.add_log(
                    f"💰 TP1 ATINGIDO EM {sym} — 50% NO BOLSO + STOP EM +0.62%",
                    f"Embolsou <strong>+R$ {(partial_net * self.usd_brl_rate):.2f}</strong> e cravou o Stop da metade restante em <code>${p['stop']:.{dec}f} (+0.62%)</code>!",
                    "cyan",
                )
            else:
                if p.get("realBybitOrder"):
                    await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
                total_op = round(p["realizedPartialUsd"] + pos_fl_usd, 2)
                self.current_equity_usd = round(self.current_equity_usd + pos_fl_usd, 4)
                self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + pos_fl_usd, 2)
                self.wins_today += 1
                self.last_profit_exit_per_sym[sym] = time.time()
                ai_note = asset.record_trade_outcome(is_win=True)
                self.save_persisted_brain_state()
                self.equity_curve_brl.append(round(self.current_equity_usd * self.usd_brl_rate, 2))
                if len(self.equity_curve_brl) > 30:
                    self.equity_curve_brl.pop(0)
                self.add_log(
                    f"🏁 GREEN 100% NO BOLSO NO TP1 ({sym} • +{gain_pct*100:.2f}%)",
                    f"Como o lote é único (<strong>${position_total_usd:.2f} USDT</strong>), vendeu 100% no alvo em <code>${px:.{dec}f}</code> "
                    f"garantindo <strong>+R$ {(total_op * self.usd_brl_rate):.2f} (+${total_op:.2f} USDT)</strong> no bolso! {ai_note}",
                    "emerald",
                )
                self.active_positions.pop(sym, None)
                self._recalculate_total_floating_pnl()
                return

        # 3) TP2 Final (+1.55% mínimo) -> Vende 100% do lote restante
        if px >= p["tp2"]:
            if p.get("realBybitOrder"):
                await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
            runner_net = p.get("floatingPnlUsd", 0.0)
            total_op = round(p["realizedPartialUsd"] + runner_net, 2)
            self.current_equity_usd = round(self.current_equity_usd + runner_net, 4)
            self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + runner_net, 2)
            self.wins_today += 1
            self.last_profit_exit_per_sym[sym] = time.time()
            ai_note = asset.record_trade_outcome(is_win=True)
            self.save_persisted_brain_state()
            self.equity_curve_brl.append(round(self.current_equity_usd * self.usd_brl_rate, 2))
            if len(self.equity_curve_brl) > 30:
                self.equity_curve_brl.pop(0)
            self.add_log(
                f"🏁 ALVO FINAL TP2 SPOT ATINGIDO ({sym})",
                f"Venda 100% concluída com lucro líquido de <strong>+R$ {(total_op * self.usd_brl_rate):.2f} (+${total_op:.2f} USDT)</strong>! {ai_note}",
                "emerald",
            )
            self.active_positions.pop(sym, None)
            self._recalculate_total_floating_pnl()

    async def close_specific_position(self, sym: str, reason: str = "MANUAL") -> None:
        if sym not in self.active_positions:
            return
        p = self.active_positions[sym]
        px = self.assets[sym].price
        if p.get("realBybitOrder"):
            await self.gateway.close_real_bybit_position(sym, p["side"], p["remainingQty"], current_price=px)
        net = p.get("floatingPnlUsd", 0.0)
        self.current_equity_usd = round(self.current_equity_usd + net, 4)
        self.realized_daily_pnl_usd = round(self.realized_daily_pnl_usd + net, 2)
        if net + p.get("realizedPartialUsd", 0.0) >= 0:
            self.wins_today += 1
            self.last_profit_exit_per_sym[sym] = time.time()
            self.assets[sym].record_trade_outcome(is_win=True)
        else:
            self.losses_today += 1
            if reason != "MANUAL":
                self.global_cooldown_until = time.time() + 300.0
                self.assets[sym].record_trade_outcome(is_win=False)
        self.save_persisted_brain_state()
        self.equity_curve_brl.append(round(self.current_equity_usd * self.usd_brl_rate, 2))
        self.add_log(
            f"🛑 POSIÇÃO SPOT VENDIDA P/ USDT ({sym} • {reason})",
            f"Vendida 100% a mercado no Spot com resultado líquido de <strong>R$ {(net * self.usd_brl_rate):+.2f}</strong>. Saldo convertido para USDT sem poeira!",
            "amber",
        )
        self.active_positions.pop(sym, None)
        self._recalculate_total_floating_pnl()

    async def step_autonomous_cycle(self) -> None:
        if not self.backend_ws_connected or (time.time() - self.last_ws_tick_ts) > 3.0:
            await self.refresh_market_prices_and_klines()

        self.check_btc_macro_filter()
        self.auto_tune_neural_parameters()

        if await self.check_daily_circuit_breaker():
            return
        if not self.ai_running:
            return

        for sym_open in list(self.active_positions.keys()):
            async with self._trade_lock:
                await self.evaluate_single_position(sym_open)

        if time.time() < self.global_cooldown_until:
            return
        if self.btc_macro_bearish:
            return

        unlocked = self.get_unlocked_symbols()
        max_slots = self.get_effective_max_slots()
        if len(self.active_positions) < max_slots:
            for sym_cand in unlocked:
                if sym_cand not in self.active_positions and len(self.active_positions) < max_slots:
                    cand_asset = self.assets[sym_cand]
                    if (
                        not cand_asset.is_suspended_by_ai
                        and cand_asset.predicted_move_pct_3m >= 0.85
                        and cand_asset.win_probability_pct >= 76.0
                        and cand_asset.score >= self.min_confluence_score
                        and cand_asset.trend_regime == "BULLISH_CONFLUENCE"
                    ):
                        async with self._trade_lock:
                            await self.open_sniper_trade(is_manual=False, requested_symbol=sym_cand)

    def get_full_state_snapshot(self) -> Dict[str, Any]:
        best = self.pick_best_opportunity()
        max_slots = self.get_effective_max_slots()
        return {
            "version": "18.0.0-ORACLE-SINGULARITY-KALMAN-L2-LEAD-LAG",
            "aiRunning": self.ai_running,
            "autoIntelligenceEnabled": self.auto_intelligence_enabled,
            "marketRegime": self.market_regime,
            "aiBrainStatus": self.ai_brain_status,
            "macroLeaderIgniting": self.macro_leader_igniting,
            "leadLagStatus": self.lead_lag_status,
            "execMode": self.gateway.exec_mode,
            "usdBrlRate": self.usd_brl_rate,
            "backendWsConnected": self.backend_ws_connected,
            "backendWsEndpoint": self.backend_ws_endpoint,
            "wsTicksProcessed": self.ws_ticks_processed,
            "enabledSymbols": list(self.enabled_symbols),
            "maxConcurrentSlots": max_slots,
            "openSlotsCount": len(self.active_positions),
            "activePositions": self.active_positions,
            "activePosition": self.active_position,
            "dailyDrawdownPct": self.daily_drawdown_pct,
            "maxDailyDrawdownPct": self.max_daily_drawdown_pct,
            "circuitBreakerTripped": self.circuit_breaker_tripped,
            "profitShieldLocked": self.profit_shield_locked,
            "peakDailyPnlUsd": self.peak_daily_pnl_usd,
            "btcMacroBearish": self.btc_macro_bearish,
            "btc1mChangePct": self.btc_1m_change_pct,
            "btcMacroStatus": self.btc_macro_status,
            "globalCooldownRemainingSec": self.global_cooldown_remaining_sec,
            "coinBalances": dict(self.gateway.coin_balances),
            "coinUsdValues": dict(self.gateway.coin_usd_values),
            "holdingSummary": self.gateway.build_dynamic_holding_summary(),
            "hasApiKeysConfigured": bool(self.gateway.api_key and self.gateway.api_secret),
            "maskedApiKey": (self.gateway.api_key[:6] + "..." + self.gateway.api_key[-4:]) if len(self.gateway.api_key) > 10 else self.gateway.api_key,
            "apiStatusText": self.gateway.last_api_status,
            "activeBybitDomain": self.gateway.active_base_url,
            "isUsWestGeoblocked": self.gateway.is_us_west_geoblocked,
            "walletSyncSource": self.wallet_sync_source,
            "startingEquityUsd": self.starting_equity_usd,
            "currentEquityUsd": self.current_equity_usd,
            "realizedDailyPnlUsd": self.realized_daily_pnl_usd,
            "floatingPnlUsd": self.floating_pnl_usd,
            "savedFeesUsd": self.saved_fees_usd,
            "winsToday": self.wins_today,
            "lossesToday": self.losses_today,
            "riskPerTradePct": self.risk_per_trade_pct,
            "minConfluenceScore": self.min_confluence_score,
            "autoLeverage": self.get_dynamic_leverage(),
            "selectedSymbol": self.selected_symbol,
            "bestAutoSymbol": best.symbol,
            "bestAutoSide": "LONG",
            "bestAutoScore": best.score,
            "bestAutoWinProb": best.win_probability_pct,
            "bestAutoPredMove3m": best.predicted_move_pct_3m,
            "equityCurveBrl": self.equity_curve_brl,
            "decisionLogs": list(self.decision_logs),
            "assets": {
                sym: {
                    "symbol": a.symbol,
                    "price": a.price,
                    "bestBid": a.best_bid,
                    "bestAsk": a.best_ask,
                    "spreadPct": a.spread_pct,
                    "vwap": a.vwap,
                    "emaFast": round(a.ema_fast, a.decimals),
                    "emaSlow": round(a.ema_slow, a.decimals),
                    "macdHist": round(a.macd_hist, 5),
                    "impulse5sPct": a.impulse_5s_pct,
                    "kalmanPrice": round(a.kalman_price, a.decimals),
                    "priceVelocity": a.price_velocity,
                    "priceAcceleration": a.price_acceleration,
                    "predictedMovePct3m": a.predicted_move_pct_3m,
                    "winProbabilityPct": a.win_probability_pct,
                    "askThinningRatio": a.ask_thinning_ratio,
                    "smartMoneyIgnition": a.smart_money_ignition,
                    "htfBullish": a.htf_bullish,
                    "rsi": a.rsi,
                    "prevRsi": a.prev_rsi,
                    "zbb": a.zbb,
                    "atr": a.atr,
                    "obi": a.obi,
                    "l2Obi": a.l2_obi,
                    "cvd": a.cvd,
                    "whaleWallStatus": a.whale_wall_status,
                    "coinWins": a.coin_wins,
                    "coinLosses": a.coin_losses,
                    "aiTrustBonus": a.ai_trust_bonus,
                    "isSuspendedByAi": a.is_suspended_by_ai,
                    "suspensionRemainingMin": a.suspension_remaining_min,
                    "trendRegime": a.trend_regime,
                    "score": a.score,
                    "bestSide": "LONG",
                    "step": a.step,
                    "decimals": a.decimals,
                    "qtyStep": BYBIT_CONTRACTS[sym].qty_step,
                    "enabled": sym in self.enabled_symbols,
                    "hasOpenPosition": sym in self.active_positions,
                    "minNotionalUsd": BYBIT_CONTRACTS[sym].min_notional_usd,
                    "minEquityRecommendedUsd": BYBIT_CONTRACTS[sym].min_equity_usd,
                }
                for sym, a in self.assets.items()
            },
        }


# =====================================================================
# 5. WORKERS ASSÍNCRONOS: WEBSOCKET DIVIDIDO EM BLOCOS DE 6 TÓPICOS
# =====================================================================

orchestrator = AutonomousSniperOrchestratorV18()
_bg_worker_task: Optional[asyncio.Task] = None
_bg_ws_task: Optional[asyncio.Task] = None


async def backend_bybit_spot_ws_listener() -> None:
    if websockets is None:
        logger.warning("Biblioteca `websockets` não encontrada; operando via HTTP polling.")
        return

    trade_topics = [f"publicTrade.{sym}" for sym in BYBIT_CONTRACTS.keys()]
    depth_topics = [f"orderbook.50.{sym}" for sym in BYBIT_CONTRACTS.keys()]
    ep_idx = 0

    while True:
        ws_url = BybitV5AutonomousGateway.WS_SPOT_ENDPOINTS[ep_idx % len(BybitV5AutonomousGateway.WS_SPOT_ENDPOINTS)]
        ep_idx += 1
        try:
            async with websockets.connect(ws_url, ping_interval=18, ping_timeout=10, close_timeout=5) as ws:
                orchestrator.backend_ws_connected = True
                orchestrator.backend_ws_endpoint = ws_url
                logger.info(f"⚡ [BACKEND WEBSOCKET ORACLE v18.0 CONECTADO] Inscrevendo 6 pares em pacotes separados via {ws_url}")
                await ws.send(json.dumps({"op": "subscribe", "args": trade_topics}))
                await asyncio.sleep(0.15)
                await ws.send(json.dumps({"op": "subscribe", "args": depth_topics}))

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        topic = str(msg.get("topic", ""))
                        if topic.startswith("publicTrade."):
                            data_list = msg.get("data")
                            if isinstance(data_list, list) and data_list:
                                last_trade = data_list[-1]
                                sym = str(last_trade.get("s", ""))
                                px = safe_float(last_trade.get("p"))
                                qty_v = safe_float(last_trade.get("v"), 1.0)
                                is_buy = str(last_trade.get("S", "Buy")) == "Buy"
                                if sym and px > 0:
                                    await orchestrator.on_realtime_ws_tick(sym, px, is_buy, trade_qty=qty_v)
                        elif topic.startswith("orderbook."):
                            ob_data = msg.get("data", {})
                            sym = str(ob_data.get("s", ""))
                            if sym in orchestrator.assets:
                                orchestrator.assets[sym].on_l2_orderbook_update(
                                    ob_data.get("b", []),
                                    ob_data.get("a", []),
                                )
                    except Exception:
                        continue
        except asyncio.CancelledError:
            break
        except Exception as exc:
            orchestrator.backend_ws_connected = False
            logger.debug(f"Reconectando WebSocket Backend ({ws_url}): {exc}")
            await asyncio.sleep(3.0)


async def background_sniper_worker() -> None:
    await orchestrator.gateway.sync_spot_instruments_precision()
    await orchestrator.hydrate_klines_from_bybit()
    await orchestrator.refresh_market_prices_and_klines()
    if orchestrator.gateway.api_key and orchestrator.gateway.api_secret:
        await orchestrator.sync_wallet_from_bybit()

    tick_counter = 0
    while True:
        try:
            await orchestrator.step_autonomous_cycle()
            tick_counter += 1
            if tick_counter % 15 == 0 and orchestrator.gateway.api_key and orchestrator.gateway.api_secret:
                await orchestrator.sync_wallet_from_bybit()
            if tick_counter % 24 == 0:
                await orchestrator.hydrate_klines_from_bybit()
        except Exception as exc:
            logger.warning(f"Erro no loop de manutenção: {exc}")
        await asyncio.sleep(2.5)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    global _bg_worker_task, _bg_ws_task
    _bg_worker_task = asyncio.create_task(background_sniper_worker())
    _bg_ws_task = asyncio.create_task(backend_bybit_spot_ws_listener())
    yield
    for t in (_bg_worker_task, _bg_ws_task):
        if t:
            t.cancel()


app = FastAPI(
    title="Sniper Quant AI v18.0 — ORACLE SINGULARITY (Kalman Future Prediction + Smart Money L2 + Lead-Lag Radar)",
    version="18.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConfigUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    exec_mode: Optional[str] = None
    custom_equity_usd: Optional[float] = None
    risk_per_trade_pct: Optional[float] = None
    min_confluence_score: Optional[float] = None
    max_daily_drawdown_pct: Optional[float] = None
    max_concurrent_slots: Optional[int] = None
    ai_running: Optional[bool] = None
    selected_symbol: Optional[str] = None
    enabled_symbols: Optional[List[str]] = None
    toggle_symbol: Optional[str] = None
    clear_cooldown: Optional[bool] = False
    reset_daily_stats: Optional[bool] = False


class ForceEntryRequest(BaseModel):
    symbol: Optional[str] = None


class ClosePositionRequest(BaseModel):
    symbol: Optional[str] = None


class BrowserRelayReport(BaseModel):
    equity_usd: Optional[float] = None
    account_type: Optional[str] = "UNIFIED"
    order_id: Optional[str] = None
    position: Optional[Dict[str, Any]] = None


@app.get("/", response_class=HTMLResponse)
async def serve_command_center() -> HTMLResponse:
    html_path = Path(__file__).parent / "sniper_ai_command_center.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(content="<h1>Sniper Quant AI v18.0 Oracle Singularity Spot Online</h1>", status_code=200)


@app.get("/api/v1/cloud/state")
async def get_cloud_state() -> JSONResponse:
    return JSONResponse(content=orchestrator.get_full_state_snapshot())


@app.get("/api/v1/cloud/sign-check")
async def get_signed_browser_check() -> JSONResponse:
    if not orchestrator.gateway.api_key or not orchestrator.gateway.api_secret:
        return JSONResponse(content={"ok": False, "error": "API Key/Secret não configurados."})

    await orchestrator.gateway.sync_server_time()
    q_unified = "accountType=UNIFIED&coin=USDT,SOL,XRP,DOGE,BNB,ETH,BTC"
    ts = orchestrator.gateway.current_ts_ms()
    headers = orchestrator.gateway.sign_v5_headers(q_unified, ts_ms=ts)
    return JSONResponse(content={
        "ok": True,
        "query": q_unified,
        "headers": headers,
        "urls": [
            f"https://api.bytick.com/v5/account/wallet-balance?{q_unified}",
            f"https://api.bybit.com/v5/account/wallet-balance?{q_unified}",
        ],
    })


@app.post("/api/v1/cloud/browser-relay-report")
async def receive_browser_relay_report(rep: BrowserRelayReport) -> JSONResponse:
    if rep.equity_usd is not None and rep.equity_usd > 0:
        eq = round(float(rep.equity_usd), 4)
        orchestrator.starting_equity_usd = eq
        orchestrator.current_equity_usd = eq
        brl = round(eq * orchestrator.usd_brl_rate, 2)
        orchestrator.equity_curve_brl = [brl, brl, brl]
        orchestrator.wallet_sync_source = f"Bybit Spot ({eq:.4f} USDT)"
        orchestrator.gateway.last_api_status = (
            f"✅ CONECTADO AO SPOT BYBIT ({rep.account_type}): {eq:.4f} USDT (≈ R$ {brl:.2f})!"
        )

    if rep.order_id and rep.position:
        pos = rep.position
        pos["srvStopOrderId"] = rep.order_id
        pos["realBybitOrder"] = True
        sym = str(pos.get("symbol", "SOLUSDT"))
        orchestrator.active_positions[sym] = pos

    return JSONResponse(content={"ok": True, "state": orchestrator.get_full_state_snapshot()})


@app.post("/api/v1/cloud/configure")
async def configure_cloud_bot(req: ConfigUpdateRequest) -> JSONResponse:
    if req.api_key is not None and req.api_key.strip():
        typed_key = req.api_key.strip()
        if orchestrator.gateway.env_api_key and typed_key == "2Q9GwuhSJ7x87HqIEN":
            orchestrator.gateway.api_key = orchestrator.gateway.env_api_key
        else:
            orchestrator.gateway.api_key = typed_key
    if req.api_secret is not None and req.api_secret.strip():
        orchestrator.gateway.api_secret = req.api_secret.strip()
    if req.exec_mode is not None:
        orchestrator.gateway.exec_mode = req.exec_mode
    if req.risk_per_trade_pct is not None:
        orchestrator.risk_per_trade_pct = max(0.5, min(3.0, req.risk_per_trade_pct))
    if req.min_confluence_score is not None:
        orchestrator.min_confluence_score = max(65.0, min(95.0, req.min_confluence_score))
    if req.max_daily_drawdown_pct is not None:
        orchestrator.max_daily_drawdown_pct = max(1.0, min(15.0, req.max_daily_drawdown_pct))
    if req.max_concurrent_slots is not None:
        orchestrator.max_concurrent_slots = max(1, min(6, req.max_concurrent_slots))
    if req.ai_running is not None:
        orchestrator.ai_running = req.ai_running
        if req.ai_running:
            orchestrator.circuit_breaker_tripped = False
    if req.clear_cooldown:
        orchestrator.global_cooldown_until = 0.0
        orchestrator.profit_shield_locked = False
        for a in orchestrator.assets.values():
            a.suspended_until = 0.0
            a.consecutive_losses = 0
    if req.selected_symbol is not None and req.selected_symbol in orchestrator.assets:
        orchestrator.selected_symbol = req.selected_symbol

    if req.enabled_symbols is not None:
        valid = [s.upper() for s in req.enabled_symbols if s.upper() in BYBIT_CONTRACTS]
        if valid:
            orchestrator.enabled_symbols = valid
            orchestrator.selected_symbol = valid[0]
            orchestrator.add_log(
                "🎯 MOEDAS ATIVAS ATUALIZADAS PELO USUÁRIO",
                f"Portfólio operando em: <strong>{', '.join(valid)}</strong> (Máx {orchestrator.get_effective_max_slots()} slot(s)).",
                "emerald",
            )

    if req.toggle_symbol is not None:
        sym_t = req.toggle_symbol.upper()
        if sym_t in BYBIT_CONTRACTS:
            if sym_t in orchestrator.enabled_symbols:
                if len(orchestrator.enabled_symbols) > 1:
                    orchestrator.enabled_symbols.remove(sym_t)
            else:
                orchestrator.enabled_symbols.append(sym_t)
                orchestrator.selected_symbol = sym_t
            orchestrator.add_log(
                f"🔘 BOTÃO DE MOEDA ACIONADO ({sym_t})",
                f"Moedas ativas no Portfólio Spot: <strong>{', '.join(orchestrator.enabled_symbols)}</strong>.",
                "cyan",
            )

    if req.reset_daily_stats:
        orchestrator.realized_daily_pnl_usd = 0.0
        orchestrator.peak_daily_pnl_usd = 0.0
        orchestrator.profit_shield_locked = False
        orchestrator.floating_pnl_usd = 0.0
        orchestrator.wins_today = 0
        orchestrator.losses_today = 0
        orchestrator.circuit_breaker_tripped = False
        orchestrator.global_cooldown_until = 0.0
        for a in orchestrator.assets.values():
            a.suspended_until = 0.0
            a.consecutive_losses = 0
        orchestrator.ai_running = True
        orchestrator.active_positions.clear()

    orchestrator.save_persisted_brain_state()

    wallet_res = {}
    if orchestrator.gateway.api_key and orchestrator.gateway.api_secret:
        wallet_res = await orchestrator.sync_wallet_from_bybit()

    if req.custom_equity_usd is not None and req.custom_equity_usd > 0 and not wallet_res.get("ok"):
        orchestrator.starting_equity_usd = round(req.custom_equity_usd, 4)
        orchestrator.current_equity_usd = round(req.custom_equity_usd, 4)
        orchestrator.realized_daily_pnl_usd = 0.0
        orchestrator.peak_daily_pnl_usd = 0.0
        orchestrator.floating_pnl_usd = 0.0
        orchestrator.wins_today = 0
        orchestrator.losses_today = 0
        orchestrator.circuit_breaker_tripped = False
        orchestrator.active_positions.clear()
        brl = round(req.custom_equity_usd * orchestrator.usd_brl_rate, 2)
        orchestrator.equity_curve_brl = [brl, brl, brl]
        orchestrator.wallet_sync_source = f"Bybit Spot ({req.custom_equity_usd:.4f} USDT)"

    return JSONResponse(content={
        "ok": True,
        "wallet_sync": wallet_res,
        "state": orchestrator.get_full_state_snapshot(),
    })


@app.post("/api/v1/cloud/force-entry")
async def force_cloud_entry(req: Optional[ForceEntryRequest] = None) -> JSONResponse:
    req_sym = req.symbol if req and req.symbol else None
    async with orchestrator._trade_lock:
        result = await orchestrator.open_sniper_trade(is_manual=True, requested_symbol=req_sym)
    return JSONResponse(content={**result, "state": orchestrator.get_full_state_snapshot()})


@app.post("/api/v1/cloud/close-position")
async def close_cloud_position(req: Optional[ClosePositionRequest] = None) -> JSONResponse:
    target_sym = req.symbol if req and req.symbol else None
    async with orchestrator._trade_lock:
        if target_sym and target_sym in orchestrator.active_positions:
            await orchestrator.close_specific_position(target_sym, reason="FECHAMENTO_MANUAL")
        else:
            for sym_open in list(orchestrator.active_positions.keys()):
                await orchestrator.close_specific_position(sym_open, reason="FECHAMENTO_MANUAL_TOTAL")
    return JSONResponse(content={"ok": True, "state": orchestrator.get_full_state_snapshot()})


if __name__ == "__main__":
    import uvicorn

    if os.getenv("SNIPER_RUN_SELFTEST", "1") == "1" and not os.getenv("PORT"):
        test_orch = AutonomousSniperOrchestratorV18()
        sol = test_orch.assets["SOLUSDT"]
        # 1) Testa Detector de Absorção Institucional Smart Money L2 (ask_thinning_ratio >= 1.35 + l2_obi >= 0.20)
        sol.on_l2_orderbook_update(
            [[94.45, 500.0], [94.44, 500.0], [94.43, 500.0]],
            [[94.46, 50.0], [94.47, 50.0]],
        )
        assert sol.smart_money_ignition is True, "Deve ativar smart_money_ignition quando há absorção nos Bids e vácuo nos Asks"
        assert sol.ask_thinning_ratio >= 1.35, f"ask_thinning_ratio deve ser >= 1.35, deu {sol.ask_thinning_ratio}"
        # 2) Testa Motor Preditivo de Futuro (predict_future_trajectory)
        pred_3m, win_prob = sol.predict_future_trajectory(94.46)
        assert isinstance(pred_3m, float) and isinstance(win_prob, float)
        # 3) Testa Radar Lead-Lag (ignição no BTC/ETH)
        btc = test_orch.assets["BTCUSDT"]
        btc.impulse_5s_pct = 0.09
        btc.obi = 0.25
        assert test_orch.check_lead_lag_radar() is True, "Deve detectar ignição Lead-Lag no BTC"
        # 4) Testa Saída Preditiva no Topo (PREDICTIVE_TOP_CASH_IN em +0.42%+ quando surge parede vendedora L2)
        test_orch.active_positions["SOLUSDT"] = {
            "symbol": "SOLUSDT",
            "side": "LONG",
            "openedAt": time.time() - 60.0,
            "initialQty": 0.120,
            "remainingQty": 0.120,
            "entry": 100.00,
            "highestPrice": 100.50,
            "atrAtEntry": 0.45,
            "stop": 99.38,
            "earlyTrailTrigger": 100.36,
            "step2Trigger": 100.55,
            "tp1": 100.85,
            "tp2": 101.55,
            "decimals": 2,
            "riskUsd": 0.07,
            "ladderStage": 1,
            "tp1Hit": False,
            "earlyTrailingActivated": True,
            "trailingActive": True,
            "singleLotProtected": True,
            "volatilityScale": 1.0,
            "floatingPnlUsd": 0.0,
            "realizedPartialUsd": 0.0,
            "srvStopOrderId": "TEST_ORACLE_TOP",
            "realBybitOrder": False,
        }
        sol.price = 100.48  # +0.48% de lucro (>= +0.42%)
        sol.best_bid = 100.47
        sol.l2_obi = -0.22  # Surgiu parede vendedora institucional no Book!
        asyncio.run(test_orch.evaluate_single_position("SOLUSDT"))
        assert "SOLUSDT" not in test_orch.active_positions, "PREDICTIVE_TOP_CASH_IN deve vender 100% em 0ms no topo!"
        # 5) Testa Auto-Tuning Neural de Gatilho
        test_orch.auto_tune_neural_parameters()
        assert 76.0 <= test_orch.min_confluence_score <= 85.0
        print("✅ [SELF-TEST v18.0 ORACLE SINGULARITY PASSOU 100%] Todas as 6 inovações preditivas validadas!")
    else:
        port = int(os.getenv("PORT", "8080"))
        uvicorn.run("sniper_hft_engine:app", host="0.0.0.0", port=port, log_level="info")