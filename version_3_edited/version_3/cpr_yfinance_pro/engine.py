from __future__ import annotations
import csv, io, json, logging, time, urllib.request, random
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).parent
CACHE=ROOT/'.cache'; CACHE.mkdir(exist_ok=True)
ET=ZoneInfo('America/New_York')
SECTORS=['Technology','Financial Services','Healthcare','Consumer Cyclical','Consumer Defensive','Industrials','Energy','Utilities','Real Estate','Basic Materials','Communication Services']
NASDAQ='https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt'
OTHER='https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt'

def cpr(high,low,close):
    p=(high+low+close)/3; bc=(high+low)/2; tc=2*p-bc
    return {'low':round(min(bc,tc),4),'high':round(max(bc,tc),4),'pivot':round(p,4)}

def overlap(a,b):
    lo=max(a['low'],b['low']); hi=min(a['high'],b['high'])
    return {'low':round(lo,4),'high':round(hi,4)} if lo<=hi else None

def previous_periods(now=None):
    now=now or datetime.now(ET)
    d=now.date(); monday=d-timedelta(days=d.weekday()); month=d.replace(day=1)
    # Strictly completed calendar week and month; never use current unfinished periods.
    return monday-timedelta(days=7),monday, (month-timedelta(days=1)).replace(day=1),month

def _download_text(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 CPR-Research/1.0'})
    with urllib.request.urlopen(req,timeout=20) as r:return r.read().decode('utf-8-sig')

def universe():
    cache=CACHE/'universe.json'
    if cache.exists() and time.time()-cache.stat().st_mtime<86400:
        return json.loads(cache.read_text())
    rows=[]
    for url,nasdaq in [(NASDAQ,True),(OTHER,False)]:
        try:
            raw=_download_text(url)
        except Exception:
            if cache.exists():
                logging.exception('Exchange listings unavailable; using cached universe')
                return json.loads(cache.read_text())
            raise
        for r in csv.DictReader(io.StringIO(raw),delimiter='|'):
            sym=(r.get('Symbol') if nasdaq else r.get('ACT Symbol') or r.get('NASDAQ Symbol') or '').strip()
            if not sym or sym.startswith('File Creation') or not all(c.isalnum() or c in '.-' for c in sym):continue
            if nasdaq:
                if r.get('Test Issue')=='Y' or r.get('ETF')=='Y' or r.get('NextShares')=='Y':continue
                exchange='NASDAQ'
            else:
                if r.get('Test Issue')=='Y' or r.get('ETF')=='Y' or r.get('Exchange') not in ('N','A'):continue
                exchange='NYSE' if r.get('Exchange')=='N' else 'NYSE American'
            rows.append({'symbol':sym.replace('.','-'),'exchange':exchange})
    rows=list({r['symbol']:r for r in rows}.values()); rows.sort(key=lambda x:x['symbol'])
    cache.write_text(json.dumps(rows));return rows

def _extract(df,sym):
    if df is None or df.empty:return None
    if isinstance(df.columns,pd.MultiIndex):
        if sym in df.columns.get_level_values(0):return df[sym].dropna(how='all')
        if sym in df.columns.get_level_values(1):return df.xs(sym,axis=1,level=1).dropna(how='all')
        return None
    return df.dropna(how='all')

def _ohlc(frame,start,end):
    d=frame[(frame.index.date>=start)&(frame.index.date<end)].dropna(subset=['High','Low','Close'])
    if d.empty:return None
    return float(d['High'].max()),float(d['Low'].min()),float(d['Close'].iloc[-1])

def multiweek_score(weeks, monthly, historical_widths):
    """Scores completed calendar-week CPRs within the active month; no lookahead."""
    if not weeks:return None
    widths=[max(0.0,w['high']-w['low']) for w in weeks]
    inside=[monthly['low']<=w['low'] and w['high']<=monthly['high'] for w in weeks]
    monthly_score=35*sum(inside)/len(weeks)
    pairs=[]
    for a,b in zip(weeks,weeks[1:]):
        joint=overlap(a,b)
        triple=overlap(joint,monthly) if joint else None
        pairs.append(1.0 if triple else 0.0)
    pair_score=30*sum(pairs)/len(pairs) if pairs else 0.0
    current=widths[-1]
    hist=[w for w in historical_widths if w>0]
    if len(hist)>=4:
        reference=float(pd.Series(hist).median())
        compression=max(0.0,min(1.0,1-current/reference))
    else:compression=0.0
    compression_score=25*compression
    scale=max(monthly['high']-monthly['low'],float(pd.Series(hist).median()) if hist else 0.0,1e-9)
    pivot_distance=abs(weeks[-1]['pivot']-monthly['pivot'])
    pivot_score=10*max(0.0,1-pivot_distance/scale)
    total=round(monthly_score+pair_score+compression_score+pivot_score,1)
    return {'strength':total,'monthlyAlignment':round(monthly_score,1),
            'weekOverlap':round(pair_score,1),'compression':round(compression_score,1),
            'pivotAlignment':round(pivot_score,1),'weeksObserved':len(weeks),
            'weeksInside':sum(inside),'overlappingPairs':int(sum(pairs)),
            'pairCount':len(pairs),'currentWidth':round(current,5),
            'medianHistoricalWidth':round(float(pd.Series(hist).median()),5) if hist else None}

def completed_weekly_cprs(frame, month_start, end_week):
    # Week boundaries are Mondays; exclude all incomplete weeks.
    first=month_start-timedelta(days=month_start.weekday())
    cursor=first; observed=[]; history=[]
    earliest=frame.index.min().date()
    history_start=earliest-timedelta(days=earliest.weekday())
    while history_start<end_week:
        end=history_start+timedelta(days=7)
        values=_ohlc(frame,history_start,end)
        if values:
            cp=cpr(*values)
            if history_start>=first and end>month_start:
                observed.append((history_start,cp))
            elif history_start<first:history.append(cp['high']-cp['low'])
        history_start=end
    return observed,history

def analyze(frame,symbol,exchange,sector,now=None,min_adv=1_000_000):
    if frame is None or frame.empty:return None
    frame=frame.copy();frame.index=pd.to_datetime(frame.index)
    if frame.index.tz is not None:frame.index=frame.index.tz_convert(ET).tz_localize(None)
    frame=frame.sort_index(); frame=frame[~frame.index.duplicated(keep='last')]
    ws,we,ms,me=previous_periods(now)
    # ADV20: last 20 completed daily sessions, excluding the current ET session.
    today=(now or datetime.now(ET)).date()
    completed=frame[frame.index.date<today].dropna(subset=['Volume'])
    if len(completed)<20:return None
    adv=float(completed['Volume'].tail(20).mean())
    if adv<=min_adv:return None
    # The active month's CPR comes from the previous completed month.
    # Weekly CPRs use fully completed weeks whose Monday is in the current month.
    month_start=today.replace(day=1)
    observed,historical=completed_weekly_cprs(frame,month_start,we)
    m=_ohlc(frame,ms,me)
    if not observed or not m:return None
    mc=cpr(*m);weekly=[w for _,w in observed]
    score=multiweek_score(weekly,mc,historical)
    wc=weekly[-1];o=overlap(wc,mc)
    if o is None:return None
    score['weekDates']=[str(d) for d,_ in observed]
    return {'symbol':symbol,'exchange':exchange,'sector':sector,'adv':round(adv),
            'close':round(float(completed['Close'].iloc[-1]),2),
            'weekly':wc,'monthly':mc,'overlap':o,'strength':score['strength'],
            'scoreBreakdown':score}

def get_sectors(symbols,progress=None):
    path=CACHE/'sectors.json'
    try: saved=json.loads(path.read_text()) if path.exists() else {}
    except Exception:saved={}
    result={};changed=False
    for i,sym in enumerate(symbols):
        old=saved.get(sym)
        if old and time.time()-old.get('ts',0)<30*86400:
            result[sym]=old['sector'];continue
        try:
            info=yf.Ticker(sym).get_info(); sector=info.get('sector') or 'Unknown'
        except Exception as e:
            logging.warning('Sector unavailable %s: %s',sym,e);sector='Unknown'
        result[sym]=sector;saved[sym]={'sector':sector,'ts':time.time()};changed=True
        if changed and i%25==0:path.write_text(json.dumps(saved))
        if progress and i%10==0:progress('Resolving sectors',i+1,len(symbols),len(symbols))
    if changed:path.write_text(json.dumps(saved))
    return result

def _fetch_batch(symbols, start, end, attempts=2):
    """Download with bounded retries; caller can isolate failed batches."""
    for attempt in range(attempts):
        try:
            data=yf.download(symbols,start=start.isoformat(),end=end.isoformat(),interval='1d',
                             auto_adjust=False,threads=min(4,len(symbols)),progress=False,
                             group_by='ticker',timeout=12)
            if data is not None and not data.empty:return data
        except Exception as exc:
            logging.warning('Yahoo batch attempt %s failed: %s',attempt+1,exc)
        if attempt+1<attempts:time.sleep(1.5*(attempt+1))
    return None

def scan(progress=None,limit=None,sector='All',min_adv=1_000_000):
    if sector!='All' and sector not in SECTORS:raise ValueError('Invalid sector')
    if progress:progress('Loading NYSE / NASDAQ listings',0,0,0)
    listings=universe()
    if limit:listings=listings[:limit]
    ws,we,ms,me=previous_periods()
    start=min(ws,ms)-timedelta(days=150)
    end=datetime.now(ET).date()+timedelta(days=1)
    matches=[];scanned=0;failed=0;qualified=0
    batch_size=25
    for offset in range(0,len(listings),batch_size):
        batch=listings[offset:offset+batch_size]
        symbols=[r['symbol'] for r in batch]
        if progress:progress(f'Downloading Yahoo prices · batch {offset//batch_size+1}',offset,len(listings),len(matches))
        data=_fetch_batch(symbols,start,end)
        for listing in batch:
            sym=listing['symbol'];frame=_extract(data,sym)
            if frame is None or frame.empty:
                failed+=1;continue
            scanned+=1
            try:row=analyze(frame,sym,listing['exchange'],'Unknown',min_adv=min_adv)
            except Exception as exc:
                logging.warning('Cannot calculate CPR for %s: %s',sym,exc);failed+=1;continue
            if row:qualified+=1;matches.append(row)
        if progress:progress('Calculating weekly / monthly CPR',min(offset+batch_size,len(listings)),len(listings),len(matches))
        time.sleep(.3)
    if matches:
        if progress:progress('Resolving sectors for CPR matches',0,len(matches),len(matches))
        resolved=get_sectors([r['symbol'] for r in matches],progress)
        for r in matches:r['sector']=resolved.get(r['symbol'],'Unknown')
    # Keep all matches so the dashboard sector selector can filter instantly without rescanning.
    matches.sort(key=lambda x:(-x['strength'],-x['adv']))
    if progress:progress('Finalizing results',len(listings),len(listings),len(matches))
    return {'rows':matches,'stats':{'universe':len(listings),'downloaded':scanned,'failed':failed,
            'matches':len(matches),'minAdv':min_adv,'sectorRequested':sector},
            'periods':{'week':f'completed weeks in {datetime.now(ET).date().strftime("%B %Y")}','month':f'{ms} to {me-timedelta(days=1)}'},
            'generatedAt':datetime.now(ET).isoformat(),'sector':'All'}
