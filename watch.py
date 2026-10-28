"""Bob the Builder - wallet watcher.

Reads the competition wallet's balances from public BNB Chain nodes and posts a
Telegram message whenever they change (a buy, a sell, a gas top-up). Read-only:
it never touches the bot or the wallet. Runs on GitHub Actions every 10 minutes.

Needs two GitHub secrets: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

WALLET = "0x1e503E96A0dFA62Ccfd3Bf9c6Dde19B84Cb41F12"
TOKENS = {                                   # symbol -> contract (all 18 decimals)
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    "MSFTB": "0x80106cb3ead06659a5ad19df39d9b4733863b9b0",
    "GOOGLB": "0x3f53de71c126bdabae20f9cd64848d317f6c3238",
    "SKHYB": "0xca750ef65f295bbecd685abf54e82caf297bdb61",
}
RPCS = ["https://bsc-dataseed.bnbchain.org", "https://bsc-rpc.publicnode.com", "https://bsc-dataseed1.defibit.io"]
STATE = Path("state/balances.json")
DUST = {"USDT": 0.01, "BNB": 0.002}          # ignore smaller changes (gas, rounding)
DEFAULT_DUST = 1e-6


def rpc(method: str, params: list):
    last = None
    for url in RPCS:
        try:
            req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                          "params": params}).encode(),
                                         {"Content-Type": "application/json", "User-Agent": "bob-watcher"})
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.loads(r.read())
            if "result" in out:
                return out["result"]
            last = out.get("error")
        except Exception as e:                # try the next node
            last = e
    raise RuntimeError(f"all BNB Chain nodes failed: {last}")


def balances() -> dict[str, float]:
    b = {"BNB": int(rpc("eth_getBalance", [WALLET, "latest"]), 16) / 1e18}
    data_prefix = "0x70a08231" + WALLET[2:].lower().rjust(64, "0")          # balanceOf(WALLET)
    for sym, addr in TOKENS.items():
        b[sym] = int(rpc("eth_call", [{"to": addr, "data": data_prefix}, "latest"]), 16) / 1e18
    return b


def describe(old: dict, new: dict) -> str | None:
    changes = {k: new[k] - old.get(k, 0.0) for k in new
               if abs(new[k] - old.get(k, 0.0)) >= DUST.get(k, DEFAULT_DUST)}
    if not changes:
        return None
    stocks = {k: v for k, v in changes.items() if k in TOKENS and k != "USDT"}
    usdt = changes.get("USDT", 0.0)
    headline = []
    for sym, d in stocks.items():
        if d > 0:
            headline.append(f"BUY {sym}" + (f" for {-usdt:.2f} USDT" if usdt < 0 and len(stocks) == 1 else ""))
        else:
            headline.append(f"SELL {sym}" + (f" for {usdt:.2f} USDT" if usdt > 0 and len(stocks) == 1 else ""))
    if not stocks and "BNB" in changes and changes["BNB"] > 0:
        headline.append("Gas top-up (USDT to BNB)")
    if not headline:
        headline.append("Wallet changed")
    lines = [f"Bob the Builder: {', '.join(headline)}", ""]
    for k, d in changes.items():
        lines.append(f"{k}: {d:+.6g} (now {new[k]:.6g})")
    lines.append("")
    lines.append(holdings(new))
    lines.append(f"https://bscscan.com/address/{WALLET}")
    return "\n".join(lines)


def holdings(b: dict) -> str:
    return "Holdings: " + ", ".join(f"{k} {v:.6g}" for k, v in b.items() if v > 0)


def telegram(text: str):
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 json.dumps({"chat_id": chat, "text": text,
                                             "disable_web_page_preview": True}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if not json.loads(r.read()).get("ok"):
            raise RuntimeError("Telegram refused the message")


def main():
    new = balances()
    old = json.loads(STATE.read_text()) if STATE.exists() else None
    if old is None:
        msg = "Bob the Builder watcher is on. You'll get a message here for every trade.\n\n" + holdings(new)
    elif "--test" in sys.argv:
        msg = "Test message from the Bob the Builder watcher.\n\n" + holdings(new)
    else:
        msg = describe(old, new)
    if msg:
        telegram(msg)
        print(msg)
    else:
        print("No change.", holdings(new))
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(new))


if __name__ == "__main__":
    main()
