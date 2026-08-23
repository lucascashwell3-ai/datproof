"""Keyless live feed for the ticker strip → data/ticker.json. Safe to re-run; keeps last good values on failure."""
import json, datetime as dt, pathlib, sys
import httpx
OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "ticker.json"
UA = {"User-Agent": "DATproof lucascashwell3@gmail.com"}
def get(url):
    return httpx.get(url, headers=UA, timeout=15).raise_for_status()
def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    out = dict(prev)
    try:
        spot = float(get("https://api.coinbase.com/v2/prices/BTC-USD/spot").json()["data"]["amount"])
        y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        ydy = float(get(f"https://api.coinbase.com/v2/prices/BTC-USD/spot?date={y}").json()["data"]["amount"])
        out.update(btc_usd=spot, btc_change_24h=(spot - ydy) / ydy * 100)
    except Exception as e:
        print("price fetch failed:", e, file=sys.stderr)
    try:
        out["block_height"] = int(get("https://blockstream.info/api/blocks/tip/height").text)
    except Exception as e:
        print("block fetch failed:", e, file=sys.stderr)
    out["as_of"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out))
if __name__ == "__main__":
    main()
