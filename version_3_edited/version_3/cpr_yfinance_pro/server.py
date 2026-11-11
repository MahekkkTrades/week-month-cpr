from __future__ import annotations
import json,logging,os,threading,traceback,time,hmac,ipaddress,urllib.request,urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from engine import scan,SECTORS
ROOT=Path(__file__).parent;LOCK=threading.RLock();ET=ZoneInfo('America/New_York')
STATE={'phase':'idle','progress':None,'result':None,'error':None,'lastScanAt':None,'startedAt':None,'nextAutoScanAt':None}
AUTO_REFRESH_MINUTES=max(15,int(os.getenv('CPR_REFRESH_MINUTES','60')))
AUTO_ENABLED=os.getenv('CPR_AUTO_REFRESH','1')=='1'
DEFAULT_LIMIT=int(os.getenv('CPR_SCAN_LIMIT','100'))
UPDATE_TOKEN=os.getenv('CPR_UPDATE_TOKEN','')
UPDATE_TARGET=os.getenv('CPR_UPDATE_URL','').rstrip('/')
DATA_DIR=Path(os.getenv('CPR_DATA_DIR',str(ROOT/'.cache')))
DATA_DIR.mkdir(parents=True,exist_ok=True)
VERSION_FILE=DATA_DIR/'version.json'
def read_version():
    try:return json.loads(VERSION_FILE.read_text())
    except Exception:return {'version':None,'message':None,'publishedAt':None}
def save_version(message):
    old=read_version()
    try:major,minor,patch=[int(x) for x in str(old.get('version') or '2.0.0').split('.')]
    except Exception:major,minor,patch=2,0,0
    patch+=1
    if patch>=10:minor+=1;patch=0
    version=f'{major}.{minor}.{patch}'
    item={'version':version,'message':message[:1000],'publishedAt':datetime.now(ET).isoformat()}
    VERSION_FILE.write_text(json.dumps(item))
    return item

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
def snapshot():
    with LOCK:return json.loads(json.dumps(STATE))
def progress(stage,done,total,matches):
    with LOCK:STATE['progress']={'stage':stage,'done':done,'total':total,'matches':matches,'updatedAt':datetime.now(ET).isoformat()}
def worker(sector,limit):
    try:
        result=scan(progress=progress,sector=sector,limit=limit)
        with LOCK:STATE.update(phase='complete',result=result,error=None,lastScanAt=datetime.now(ET).isoformat())
        logging.info('Scan completed: %s matches',len(result['rows']))
    except Exception as e:
        logging.error('Scan failed: %s\n%s',e,traceback.format_exc())
        with LOCK:STATE.update(phase='error',error=str(e),lastScanAt=datetime.now(ET).isoformat())
def start_scan(sector='All',limit=None):
    with LOCK:
        if STATE['phase']=='scanning':return False
        STATE.update(phase='scanning',startedAt=datetime.now(ET).isoformat(),
                     progress={'stage':'Loading exchange listings','done':0,'total':0,'matches':0},error=None)
    logging.info('Starting Yahoo CPR scan: sector=%s limit=%s',sector,limit)
    threading.Thread(target=worker,args=(sector,limit),daemon=True).start()
    return True

def auto_refresh_loop():
    # CPR periods only change at week/month boundaries, but hourly refresh
    # updates the 20-day liquidity screen and handles newly available daily bars.
    while True:
        time.sleep(AUTO_REFRESH_MINUTES*60)
        if AUTO_ENABLED:
            start_scan('All',DEFAULT_LIMIT if DEFAULT_LIMIT>0 else None)

class Handler(BaseHTTPRequestHandler):
    def respond(self,code,payload,ctype='application/json; charset=utf-8'):
        body=json.dumps(payload).encode() if isinstance(payload,(dict,list)) else payload
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=='/api/status':return self.respond(200,{'scan':snapshot(),'provider':'Yahoo Finance','sectors':SECTORS})
        if p=='/api/version':return self.respond(200,read_version())
        mapping={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8')}
        if p=='/favicon.ico':return self.respond(204,b'','image/x-icon')
        if p not in mapping:return self.respond(404,{'error':'Not found'})
        name,ctype=mapping[p];return self.respond(200,(ROOT/name).read_bytes(),ctype)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>4096:return self.respond(413,{'error':'Payload too large'})
            data=json.loads(self.rfile.read(n) or b'{}')
        except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'Invalid request'})
        if path=='/api/version/publish':
            message=str(data.get('message','')).strip()
            if not message:return self.respond(400,{'error':'An update message is required'})
            if not UPDATE_TOKEN:return self.respond(503,{'error':'Set CPR_UPDATE_TOKEN on the server before publishing updates'})
            supplied=self.headers.get('X-Update-Token','')
            # The browser never receives the secret; the local server adds it when forwarding.
            if UPDATE_TARGET:
                try:
                    if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                        return self.respond(403,{'error':'Publishing from the local machine only'})
                except ValueError:return self.respond(403,{'error':'Publishing from the local machine only'})
                target=UPDATE_TARGET+'/api/version/publish'
                body=json.dumps({'message':message,'clientVersion':data.get('clientVersion')}).encode()
                req=urllib.request.Request(target,data=body,headers={'Content-Type':'application/json','X-Update-Token':UPDATE_TOKEN},method='POST')
                try:
                    with urllib.request.urlopen(req,timeout=15) as response:
                        return self.respond(response.status,response.read())
                except urllib.error.HTTPError as exc:
                    return self.respond(exc.code,{'error':exc.read().decode('utf-8','replace')[:500]})
                except Exception as exc:return self.respond(502,{'error':f'Could not reach update server: {exc}'})
            if not hmac.compare_digest(supplied,UPDATE_TOKEN):return self.respond(401,{'error':'Invalid update authorization'})
            return self.respond(200,save_version(message))
        if path!='/api/scan':return self.respond(404,{'error':'Not found'})
        sector=data.get('sector','All');limit=data.get('limit',None)
        if sector!='All' and sector not in SECTORS:return self.respond(400,{'error':'Invalid sector'})
        if limit is not None and (type(limit)!=int or not 1<=limit<=10000):return self.respond(400,{'error':'Invalid scan limit'})
        if not start_scan(sector,limit):return self.respond(409,{'error':'Scan already running'})
        return self.respond(202,{'accepted':True})
if __name__=='__main__':
    port=int(os.getenv('PORT','8000'));print(f'CPR Atlas running at http://127.0.0.1:{port}',flush=True)
    threading.Thread(target=auto_refresh_loop,daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
