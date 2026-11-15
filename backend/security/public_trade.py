"""Bounded read-only customs catalog projection; no private follows or collectors."""
from datetime import date, datetime
import math
from pathlib import Path
import re
import sqlite3
from fastapi import HTTPException
from pipeline.trade_catalog import DEFAULT_FOLLOWS, PUBLIC_NAMES
from pipeline.trade_metrics import derive, table_from_inputs, _month_grid

COLUMNS={'hs_code','period','export_usd','import_usd','fetched_at'}


def _authorize(action,table,column,database,source):
    if action==sqlite3.SQLITE_SELECT:return sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_READ and database=='main' and table=='trade_stats' and column in COLUMNS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def trade_connection(path=None):
    if path is None:
        from config import DB_PATH
        path=DB_PATH
    conn=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    try:
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        conn.set_authorizer(_authorize)
        return conn
    except BaseException:
        conn.close();raise


def month_before(period,back):
    year,month=divmod(int(period[:4])*12+int(period[5:])-1-back,12)
    return f'{year:04d}-{month+1:02d}'


def stored_trade(flow='export',period=None,months=60,path=None,*,_highlights=None):
    today=date.today().strftime('%Y-%m')
    if flow not in {'export','import'} or months not in {24,60} or (period is not None and
            (not re.fullmatch(r'[1-9][0-9]{3}-(0[1-9]|1[0-2])',period) or period>today or period<'1900-01')):
        raise HTTPException(422,'Invalid trade selection')
    conn=None
    try:
        conn=trade_connection(path)
        latest=[]
        available_periods=set()
        for hs,_,_ in DEFAULT_FOLLOWS:
            row=conn.execute('SELECT period FROM trade_stats WHERE hs_code=? AND period<=? ORDER BY period DESC LIMIT 1',(hs,today)).fetchone()
            if row:latest.append(row['period'])
        latest_period=max(latest,default=None)
        if latest_period and not re.fullmatch(r'[1-9][0-9]{3}-(0[1-9]|1[0-2])',latest_period):
            raise ValueError('Invalid stored month')
        if latest_period:
            for hs,_,_ in DEFAULT_FOLLOWS:
                available_periods.update(r['period'] for r in conn.execute(
                    'SELECT period FROM trade_stats WHERE hs_code=? AND period>=? AND period<=? ORDER BY period DESC LIMIT 240',
                    (hs,month_before(latest_period,239),latest_period)))
        if any(not re.fullmatch(r'[1-9][0-9]{3}-(0[1-9]|1[0-2])',p) for p in available_periods):
            raise ValueError('Invalid stored month')
        selected=period or latest_period
        raw={};fetched={}
        if selected:
            for hs,_,_ in DEFAULT_FOLLOWS:
                rows=conn.execute('SELECT period,export_usd,import_usd,fetched_at FROM trade_stats '
                    'WHERE hs_code=? AND period>=? AND period<=? ORDER BY period DESC LIMIT 240',
                    (hs,month_before(selected,239),selected)).fetchall()[::-1]
                raw[hs]=[]
                for r in rows:
                    if not re.fullmatch(r'[1-9][0-9]{3}-(0[1-9]|1[0-2])',r['period']):raise ValueError('Invalid stored month')
                    for key in ('export_usd','import_usd'):
                        value=r[key]
                        if value is not None and (not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
                            raise ValueError('Invalid stored value')
                    raw[hs].append({key:r[key] for key in ('period','export_usd','import_usd')})
                stamps=[r['fetched_at'] for r in rows if valid_timestamp(r['fetched_at'])]
                fetched[hs]=max(stamps,default=None)
        return project(raw,fetched,flow,selected,latest_period,months,sorted(available_periods,reverse=True),highlights=_highlights)
    except (OSError,sqlite3.Error,ValueError,TypeError):
        raise HTTPException(503,'Trade observations unavailable') from None
    finally:
        if conn is not None:conn.close()


def project(raw,fetched,flow,period,latest_period,months,periods,*,highlights=None):
    meta={'flow':flow,'period':period,'latest_period':latest_period,'periods':periods,'months':months,
          'unit':'USD','valuation':'FOB' if flow=='export' else 'CIF','source':'관세청 품목별 수출입실적',
          'source_url':'https://www.data.go.kr/data/15101609/openapi.do',
          'note':'고정 11개 품목의 저장 관측입니다. 전체 무역 총액이 아닙니다. 저장시각은 재취득·저장 시각이며 공표·정정일이 아닙니다. 수집기가 결측·해석 실패를 0으로 저장할 수 있어 저장된 0의 실제 여부는 확인되지 않았습니다. 부분 결측 합계는 관측 소계이고 기여도 분모는 전년비 증감액이 있는 상위 품목만 포함합니다. 원천 정정으로 값이 바뀔 수 있습니다.',
          'fetched_at':max((v for v in fetched.values() if v),default=None)}
    if highlights is not None:
        from pipeline.trade_metrics import highlights_from_table
        catalog=[{'hs_code':hs,'item_name':PUBLIC_NAMES.get(hs,name),'group_label':group} for hs,name,group in DEFAULT_FOLLOWS]
        table=table_from_inputs(catalog,raw,periods,period,flow,**highlights['options'])
        result=highlights_from_table(table,flow,highlights['limit'],highlights['rank'])
        top=[r for r in table['rows'] if not r.get('nested_in')]
        observed=sum(r.get('value') is not None for r in top)
        result.update(scope='public_catalog',observed_count=observed,total_count=len(top) if top else len(catalog),
                      partial=observed<len(top) if top else True,total_usd=result['total_usd'] if observed else None)
        for group in result['groups']:
            members=[r for r in top if (r.get('group_label') or '미분류')==group['group_label']]
            known=[r['value'] for r in members if r.get('value') is not None]
            group.update(value=sum(known) if known else None,observed_count=len(known),total_count=len(members),partial=len(known)<len(members))
        result['groups'].sort(key=lambda g:-(g['value'] or 0))
        return result
    if not period or not periods:
        return {**meta,'empty':True,'partial':False,'rows':[],'total':aggregate([]),'groups':[]}
    catalog=[{'hs_code':hs,'item_name':PUBLIC_NAMES.get(hs,name),'group_label':group} for hs,name,group in DEFAULT_FOLLOWS]
    table=table_from_inputs(catalog,raw,periods,period,flow)
    grid=_month_grid(month_before(period,months-1),period)
    rows=[]
    for row in table['rows']:
        hs=row['hs_code'];series=derive(raw.get(hs,[]),flow);by={r['period']:r for r in series}
        metric={k:row.get(k) for k in ('value','mom','yoy','qoq','yoy3m','z','delta_usd','contribution')}
        metric.update(period=period,flag=row['flag'],reason=row['reason'])
        if metric['delta_usd'] is None:metric['contribution']=None
        original={r['period']:r for r in raw.get(hs,[])}
        def point(p):
            out={'period':p,**{k:by.get(p,{}).get(k) for k in ('value','mom','yoy','qoq','yoy3m')}}
            exp,imp=original.get(p,{}).get('export_usd'),original.get(p,{}).get('import_usd')
            window=[by.get(month_before(p,b),{}).get('value') for b in range(12)]
            out.update(export_usd=exp,import_usd=imp,balance_usd=exp-imp if exp is not None and imp is not None else None,
                       ma12=sum(window)/12 if all(v is not None for v in window) else None)
            return out
        metric.update({k:v for k,v in point(period).items() if k in ('export_usd','import_usd','balance_usd','ma12')})
        # Legacy classification conflates an absent comparison with a real zero.
        # The public projection preserves missing observations instead of calling them new.
        if metric['value'] is None:
            metric.update(flag='none',reason='기준월 관측 없음')
        elif metric['flag']=='new':
            base=by.get(month_before(period,12),{}).get('value')
            if base is None:metric.update(flag='none',reason='전년 동월 관측 누락')
            elif base==0:metric.update(reason='저장된 전년 비교값이 0입니다. 원자료의 실제 0 여부는 확인되지 않았습니다.')
        rows.append({**{k:row[k] for k in ('hs_code','item_name','group_label','nested_in')},
            'fetched_at':fetched.get(hs),'missing':metric['value'] is None,'metrics':metric,
            'series':[point(p) for p in grid]})
    groups=[]
    for label in sorted({r['group_label'] for r in rows}):
        group_rows=[r for r in rows if r['group_label']==label]
        groups.append({'group_label':label,**aggregate([r for r in group_rows if not r['nested_in']])})
    return {**meta,'empty':not any(r['metrics']['value'] is not None for r in rows),
            'partial':any(any(p['value'] is None for p in row['series']) for row in rows),'rows':rows,
            'total':aggregate([r for r in rows if not r['nested_in']]),'groups':groups}


def aggregate(rows):
    values=[r['metrics']['value'] for r in rows if r['metrics']['value'] is not None]
    return {'value':sum(values) if values else None,'observed_count':len(values),
            'total_count':len(rows),'partial':len(values)<len(rows)}


def valid_timestamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)?',value):return False
    try:datetime.fromisoformat(value.replace('Z','+00:00'));return True
    except ValueError:return False


def stored_highlights(period=None, flow='export', limit=8, rank='contribution', *, mode='zscore', metric='yoy', z_threshold=None, min_usd=None, path=None):
    if (not 1<=limit<=100 or rank not in {'contribution','intensity'} or mode not in {'zscore','fixed'}
            or metric not in {'mom','yoy','qoq','yoy3m'} or
            any(v is not None and (not math.isfinite(v) or v<0) for v in (z_threshold,min_usd))):
        raise HTTPException(422,'Invalid public trade selection')
    return stored_trade(flow,period,60,path,_highlights={'limit':limit,'rank':rank,
        'options':dict(mode=mode,metric=metric,z_threshold=z_threshold,min_usd=min_usd)})
