#!/usr/bin/env python3
"""
家庭财富驾驶舱 · 自动抓取便宜信号
用 GitHub Actions 定时运行，抓取实时行情，计算四个便宜信号，输出 signals.json
"""
import json, os, sys, math
import warnings; warnings.filterwarnings('ignore')
import urllib.request

def http_get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

def http_get_bytes(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

# ============ 1. 腾讯行情接口（实时价格，支持CORS/GBK） ============
def tencent_quote(codes):
    """codes: 逗号分隔，返回 {code: {name, price, prev, pct}}"""
    url = f"https://qt.gtimg.cn/q={codes}"
    # 腾讯返回 GBK，需要先以字节读再解码
    raw = http_get_bytes(url)
    data = raw.decode('gbk', errors='ignore')
    result = {}
    for line in data.split(';'):
        line = line.strip()
        if '="' not in line:
            continue
        key = line.split('=')[0].replace('v_', '').strip()
        val = line.split('"')[1]
        f = val.split('~')
        if len(f) < 5 or f[1] == '':
            continue
        try:
            result[key] = {
                'name': f[1],
                'price': float(f[3]),
                'prev': float(f[4]),
                'pct': float(f[32]) if len(f) > 32 and f[32] else 0.0
            }
        except:
            continue
    return result

# ============ 2. akshare 数据（服务器端） ============
def akshare_data():
    import akshare as ak
    out = {}
    # 10年国债收益率
    try:
        df = ak.bond_zh_us_rate()
        out['cn10y'] = float(df['中国国债收益率10年'].dropna().iloc[-1])
    except Exception as e:
        out['cn10y_err'] = str(e)
    # 沪深300股息率（中证指数官网）
    try:
        df = ak.stock_zh_index_value_csindex(symbol='000300')
        out['csi300_div'] = float(df['股息率1'].dropna().iloc[0])
        out['csi300_pe'] = float(df['市盈率1'].dropna().iloc[0])
        out['csi300_date'] = str(df['日期'].dropna().iloc[0])
    except Exception as e:
        out['csi300_err'] = str(e)
    # 纳指100 历史（算回撤）
    try:
        df = ak.index_us_stock_sina(symbol='.NDX')
        closes = df['close'].dropna()
        recent_high = float(closes.max())
        cur = float(closes.iloc[-1])
        out['ndx_price'] = cur
        out['ndx_high'] = recent_high
        out['ndx_drawdown'] = round((cur - recent_high) / recent_high * 100, 2)
        out['ndx_date'] = str(df['date'].iloc[-1])
    except Exception as e:
        out['ndx_err'] = str(e)
    return out

# ============ 3. 主流程 ============
def main():
    result = {'updated': None, 'signals': {}}
    
    # 腾讯实时行情
    try:
        q = tencent_quote('usNDX,usINX,sh000300,hkHSTECH')
        result['quotes'] = q
    except Exception as e:
        result['quotes_err'] = str(e)
    
    # akshare 深度数据
    ak = akshare_data()
    result['ak'] = ak
    
    # ===== 组装四个便宜信号 =====
    sig = {}
    quotes = result.get('quotes', {})
    akd = ak
    
    # 信号1: 纳指100回撤
    if 'ndx_drawdown' in akd:
        dd = akd['ndx_drawdown']
        sig['ndx_drawdown'] = dd
        sig['ndx_drawdown_pct'] = abs(dd)  # 正值表示回撤幅度
        sig['ndx_action'] = 'buy' if abs(dd) >= 15 else ('watch' if abs(dd) >= 8 else 'hold')
    elif 'usNDX' in quotes:
        # 没有历史数据时用腾讯现价（回撤未知）
        sig['ndx_price'] = quotes['usNDX']['price']
    
    # 信号2: 沪深300股息率
    if 'csi300_div' in akd:
        div = akd['csi300_div']
        sig['csi300_div'] = round(div, 2)
        sig['csi300_div_action'] = 'buy' if div >= 3.5 else ('watch' if div >= 3.0 else 'hold')
        sig['csi300_pe'] = akd.get('csi300_pe')
        sig['csi300_date'] = akd.get('csi300_date')
    
    # 信号3: 港股科技（用恒生科技价格偏离，PB分位需要历史，用替代）
    if 'hkHSTECH' in quotes:
        sig['hk_price'] = quotes['hkHSTECH']['price']
        sig['hk_pct'] = quotes['hkHSTECH']['pct']
        # 简单替代：用单日/近期涨跌作为参考（真正的PB分位需历史数据）
    
    # 信号4: 股债性价比 = 沪深300股息率 - 10年国债收益率
    if 'csi300_div' in akd and 'cn10y' in akd:
        bond = akd['cn10y']
        spread = akd['csi300_div'] - bond
        sig['bond_yield'] = round(bond, 3)
        sig['equity_bond_spread'] = round(spread, 2)
        sig['spread_action'] = 'buy' if spread >= 2.0 else ('watch' if spread >= 0.5 else 'hold')
    
    result['signals'] = sig
    
    # 时间戳
    from datetime import datetime
    result['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 输出
    out_path = os.path.join(os.path.dirname(__file__), 'signals.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("signals.json 生成成功")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
