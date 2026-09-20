"""FairRoute desktop demo server. Run: python server.py (localhost:8501)."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import gemini_assistant
import demo_story

from fairroute import StreetRouter, TransitRouter, evaluate_resource, with_literal_street_legs
from access_evidence import access_evidence, verification_checklist
from journey import SORT_OPTIONS, category_matches, itinerary_steps, option_result, rank_results, schedule_notice, trip_summary
from planner import optimize_interventions, INTERVENTIONS, MOBILITY_PROFILES, evaluate_manual_intervention, profile_access_grid, summarize_grid, synthetic_origins
from resource_adapter import combine_with_curated, fetch_fci_resources

ROOT = Path(__file__).parent
DATA = ROOT / 'data'


@lru_cache(maxsize=1)
def router():
    return TransitRouter.from_json(DATA / 'transit_network.json')


@lru_cache(maxsize=1)
def streets():
    return StreetRouter.from_json(DATA / 'street_network.json')


@lru_cache(maxsize=1)
def catalog():
    curated = pd.read_csv(DATA / 'resources.csv', dtype=str).fillna('')
    try:
        live, meta = fetch_fci_resources()
        rows = combine_with_curated(live, curated)
        meta.update(status='connected', supplement_count=len(rows)-len(live))
    except Exception:
        try:
            snapshot=json.loads((DATA/'resource_snapshot.json').read_text())
            rows=combine_with_curated(pd.DataFrame(snapshot['resources']),curated)
            meta={**snapshot['metadata'],'status':'snapshot','supplement_count':len(rows)-len(snapshot['resources'])}
        except (OSError,ValueError,KeyError):
            rows = combine_with_curated(pd.DataFrame(), curated)
            meta = dict(status='fallback', loaded=0, supplement_count=len(rows))
    return rows.to_dict('records'), meta


def locations():
    return pd.read_csv(DATA / 'start_locations.csv').to_dict('records')


def numeric(value, low, high, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a number.')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a number.') from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')
    return number


def validate_search(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected search settings.')
    origin = payload.get('origin', [29.645567, -82.322697])
    if not isinstance(origin, list) or len(origin) != 2:
        raise ValueError('Choose a valid starting point.')
    modes = payload.get('modes', ['RTS bus', 'Walk'])
    if not isinstance(modes, list) or not modes or any(m not in ['RTS bus','Walk','Bike / micromobility'] for m in modes):
        raise ValueError('Choose at least one valid travel mode.')
    needs = payload.get('access_needs', [])
    if not isinstance(needs, list) or any(n not in ['Step-free entrance','Accessible restroom'] for n in needs):
        raise ValueError('Choose valid access requirements.')
    sort = payload.get('sort', SORT_OPTIONS[0])
    if sort not in SORT_OPTIONS:
        raise ValueError('Choose a valid sort order.')
    return dict(origin=(numeric(origin[0],-90,90,'Latitude'),numeric(origin[1],-180,180,'Longitude')),
        demo_story=bool(payload.get('demo_story',False)),
        origin_name=str(payload.get('origin_name','Map starting point'))[:120],
        category=str(payload.get('category','Food assistance'))[:100], resource_id=str(payload.get('resource_id',''))[:150],
        query=str(payload.get('query',''))[:150].strip().casefold(), modes=modes,
        max_minutes=int(numeric(payload.get('max_minutes',45),15,90,'Trip limit')),
        max_walk=numeric(payload.get('max_walk',.5),.1,1,'Walking limit'),
        walk_speed=numeric(payload.get('walk_speed',3),1,4,'Walking pace'),
        wheelchair_transit=bool(payload.get('wheelchair_transit',False)), access_needs=needs,
        confirmed_only=bool(payload.get('confirmed_only',False)), include_demo=bool(payload.get('include_demo',False)), sort=sort)


def evaluate_search(search, geometry=False):
    all_rows, meta = catalog()
    if search['demo_story']:
        all_rows=demo_story.resources()
    candidates = [r for r in all_rows if (search['include_demo'] or meta['status']=='fallback' or 'demonstration' not in r.get('source','').lower())
        and category_matches(r,search['category'])
        and (not search['resource_id'] or r['resource_id']==search['resource_id'])
        and (not search['query'] or search['query'] in (r['name']+' '+r.get('description','')+' '+r.get('address','')).casefold())]
    transit = router().build_plan(search['origin'],search['max_walk'],search['walk_speed'],
        wheelchair_needed=search['wheelchair_transit'],max_minutes=search['max_minutes']+40) if 'RTS bus' in search['modes'] else None
    rows = [evaluate_resource(r,search['origin'],search['modes'],search['max_walk'],search['max_minutes'],search['walk_speed'],
        search['access_needs'],router(),transit,search['wheelchair_transit'],include_geometry=geometry) for r in candidates]
    ranked = rank_results(rows,search['sort'],search['wheelchair_transit'])
    hidden = 0
    if search['confirmed_only'] and (search['access_needs'] or search['wheelchair_transit']):
        hidden = sum(r['status']=='confirm' for r in ranked)
        ranked = [r for r in ranked if r['status']=='reachable']
    return rows, ranked, hidden


def public_row(row, search):
    out = {k:v for k,v in row.items() if k not in ['best_option','travel_options']}
    option = row.get('best_option')
    out['best_option'] = {k:v for k,v in asdict(option).items() if k!='legs'} if option else None
    out['access_evidence'] = access_evidence(row,search,option) if option else None
    out['options'] = []
    for i, opt in enumerate(row.get('travel_options',[])):
        rated = option_result(row,opt,search['wheelchair_transit'])
        if search['confirmed_only'] and (search['access_needs'] or search['wheelchair_transit']) and rated['status']=='confirm':
            continue
        out['options'].append(dict(index=i, **{k:v for k,v in asdict(opt).items() if k!='legs'},burden=rated['burden'],status=rated['status']))
    out['option_index'] = next((i for i,o in enumerate(row.get('travel_options',[])) if o==option),0)
    return out


def bootstrap():
    rows,meta=catalog()
    return dict(assistant_configured=bool(gemini_assistant.configuration()[0]),locations=locations(),categories=sorted({c.strip() for r in rows for c in r.get('categories',r['category']).split('|')}),
        metadata=meta,schedule_notice=schedule_notice(router().meta),transit_metadata=router().meta,route_count=len(router().routes),
        resource_count=len(rows), live_count=sum('demonstration' not in r.get('source','').lower() for r in rows),
        profiles=[asdict(p) for p in MOBILITY_PROFILES],interventions=[asdict(i) for i in INTERVENTIONS])


def search_api(payload):
    search=validate_search(payload)
    rows,ranked,hidden=evaluate_search(search)
    return dict(matches=[public_row(r,search) for r in ranked],
        excluded=[dict(name=r['name'],reason=r.get('unavailable_reason','Does not fit these settings.')) for r in rows if r['status'] in ['outside_limit','does_not_match']],
        checked=len(rows),hidden=hidden,origin=search['origin'],notice=schedule_notice(router().meta))


def journey_api(payload):
    search=validate_search(payload)
    _,ranked,_=evaluate_search(search,geometry=True)
    if not ranked:
        raise ValueError('This service no longer fits your current settings.')
    row=ranked[0]
    idx=payload.get('option_index', next(i for i,o in enumerate(row['travel_options']) if o==row['best_option']))
    if not isinstance(idx,int) or not 0<=idx<len(row['travel_options']):
        raise ValueError('Choose an available travel option.')
    row=option_result(row,row['travel_options'][idx],search['wheelchair_transit'])
    if search['confirmed_only'] and (search['access_needs'] or search['wheelchair_transit']) and row['status']=='confirm':
        raise ValueError('This option has unconfirmed access.')
    option=with_literal_street_legs(row['best_option'],streets(),wheelchair=search['wheelchair_transit'])
    legs=[]
    for leg,step in zip(option.legs,itinerary_steps(option,router())):
        color=router().routes.get(leg.route_id,{}).get('color','#277db6') if leg.kind=='bus' else ('#e4ac30' if leg.kind=='bike' else '#309774')
        legs.append(dict(**step,geometry=leg.geometry,color=color,geometry_source=leg.geometry_source))
    evidence=access_evidence(row,search,option)
    return dict(resource=public_row(row,search),legs=legs,summary=trip_summary(search,row,router()),verification_checklist=verification_checklist(row,evidence))


@lru_cache(maxsize=20)
def gaps_api(category,profile_id):
    profiles={p.id:p for p in MOBILITY_PROFILES}
    if profile_id not in profiles:
        raise ValueError('Choose a valid mobility profile.')
    resources,meta=catalog()
    resources=[r for r in resources if meta['status']=='fallback' or 'demonstration' not in r.get('source','').lower()]
    candidates=[r for r in resources if category_matches(r,category)]
    # A category-selected resource may have this category as a secondary tag.
    candidates=[{**r,'category':category} for r in candidates]
    rows=profile_access_grid(router(),candidates,synthetic_origins(router()),profiles[profile_id])
    return dict(rows=rows,summary=summarize_grid(rows),profile=asdict(profiles[profile_id]))


@lru_cache(maxsize=6)
def scenario_api(intervention_id):
    item=next((i for i in INTERVENTIONS if i.id==intervention_id),None)
    if item is None:
        raise ValueError('Choose an available intervention.')
    return evaluate_manual_intervention(router(),catalog()[0],synthetic_origins(router()),locations(),item)


@lru_cache(maxsize=6)
def planning_api(budget=24):
    if budget not in [12,16,24,28,32,40]: raise ValueError('Choose a supported budget.')
    return optimize_interventions(router(),catalog()[0],locations(),budget)


def assistant_api(payload):
    search=validate_search(payload.get('search',{}))
    selected=str(payload.get('selected') or '')[:150]
    def dispatch(name,args):
        if not isinstance(args,dict): raise ValueError('Invalid assistant tool arguments.')
        if name=='find_resources':
            settings=dict(search)
            settings['origin']=list(search['origin'])
            settings['resource_id']=''
            profile=args.get('profile','current')
            if profile not in ['current','standard','limited','stepfree']: raise ValueError('Invalid profile.')
            if profile!='current':
                limited=profile!='standard'
                settings.update(max_walk=.15 if limited else .5,walk_speed=1.25 if limited else 3,
                    modes=['RTS bus','Walk'],wheelchair_transit=profile=='stepfree',
                    access_needs=['Step-free entrance'] if profile=='stepfree' else [],confirmed_only=False)
            for field in ['category','query']:
                if field in args: settings[field]=str(args[field])[:150]
            if settings['category'] not in ['All resource types',*bootstrap()['categories']]: raise ValueError('Unknown resource category.')
            result=search_api(settings)
            public=[{k:r[k] for k in ['resource_id','name','category','burden','best_option','access_evidence','source']} for r in result['matches'][:6]]
            return {'matches':public,'count':len(result['matches']),'notice':result['notice']},{'type':'search','settings':settings}
        if name=='explain_trip':
            if not selected: return {'message':'No journey selected. Ask the user to choose one.'},None
            data=journey_api({**search,'origin':list(search['origin']),'resource_id':selected})
            row=data['resource']
            return {k:row[k] for k in ['name','best_option','burden','access_evidence','source']},None
        if name=='show_access_gaps':
            profile=args.get('profile','typical')
            data=gaps_api(search['category'],profile)
            return {'summary':data['summary'],'profile':data['profile'],'sample_count':len(data['rows'])},{'type':'gaps','profile':profile}
        if name=='compare_plans':
            budget=args.get('budget',24)
            data=planning_api(budget)
            return {k:{f:data[k][f] for f in ['average_score','minimum_score','cost_units','interventions']} for k in ['efficiency','fairness']},{'type':'planning','budget':budget}
        raise ValueError('Unsupported tool.')
    # Explicit user text and non-location preferences only. The current coordinates remain local.
    context={k:search[k] for k in ['category','modes','max_minutes','max_walk','walk_speed','access_needs','wheelchair_transit']}
    context['available_categories']=bootstrap()['categories']
    return gemini_assistant.respond(payload.get('message',''),dispatch,context)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'web'),**kwargs)

    def log_message(self,*args):
        pass  # Search origins and URL parameters are never logged.

    def json_response(self,data,status=200):
        body=json.dumps(data,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path=='/api/bootstrap':
                return self.json_response(bootstrap())
            if path=='/api/network':
                return self.json_response([dict(path=s['path'],color=router().routes.get(s['route'],{}).get('color','#888'),name=router().routes.get(s['route'],{}).get('short_name',s['route'])) for s in router().route_shapes()])
            if path.startswith('/api/'):
                return self.json_response({'error':'Not found'},404)
            super().do_GET()
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            self.json_response({'error':'Could not load the data. Please try again.'},500)

    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':
            return self.json_response({'error':'Same-origin requests only.'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<20000:
                raise ValueError('Invalid request size.')
            payload=json.loads(self.rfile.read(size))
            if self.path=='/api/search': result=search_api(payload)
            elif self.path=='/api/journey': result=journey_api(payload)
            elif self.path=='/api/gaps': result=gaps_api(str(payload.get('category','Food assistance')),str(payload.get('profile','typical')))
            elif self.path=='/api/assistant': result=assistant_api(payload)
            elif self.path=='/api/planning': result=planning_api(payload.get('budget',24))
            elif self.path=='/api/scenario': result=scenario_api(str(payload.get('intervention','')))
            else: return self.json_response({'error':'Not found'},404)
            self.json_response(result)
        except (ValueError,TypeError,KeyError,AttributeError) as error:
            self.json_response({'error':str(error) or 'Invalid settings.'},400)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            self.json_response({'error':'The calculation could not finish. Try again.'},500)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8501)
    args=parser.parse_args()
    print(f'FairRoute desktop: http://localhost:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
