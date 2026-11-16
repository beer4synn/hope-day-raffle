"""Hope Day: persistent, single-instance raffle behind an HTTPS reverse proxy."""
import os, re, json, time, secrets, hashlib, hmac, sqlite3, unicodedata, io
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse
from contextlib import contextmanager

ROOT = Path(__file__).parent
QUOTAS = {1:1, 2:5, 3:3, 4:3}
class Problem(Exception):
    def __init__(self, status, message): self.status, self.message = status, message

def normalize_phone(value):
    if not isinstance(value,str) or len(value)>40: raise Problem(400,'휴대폰 번호를 확인해 주세요.')
    value=unicodedata.normalize('NFKC',value).strip()
    if not re.fullmatch(r'[+0-9()\s.-]+',value): raise Problem(400,'휴대폰 번호를 확인해 주세요.')
    value=re.sub(r'[^0-9+]','',value)
    if value.startswith('+82'): value='0'+value[3:]
    elif value.startswith('0082'): value='0'+value[4:]
    if not re.fullmatch(r'010\d{8}',value): raise Problem(400,'010으로 시작하는 휴대폰 번호 11자리를 입력해 주세요.')
    return value

class Store:
    def __init__(self,path,key):
        self.path,self.key=str(path),key
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),is_open INTEGER NOT NULL DEFAULT 0,view TEXT NOT NULL DEFAULT 'waiting',rank INTEGER NOT NULL DEFAULT 4);
            INSERT OR IGNORE INTO settings(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY AUTOINCREMENT,nickname TEXT NOT NULL,phone_hash TEXT NOT NULL UNIQUE,ending TEXT NOT NULL,receipt_hash TEXT NOT NULL UNIQUE,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS draws(rank INTEGER PRIMARY KEY CHECK(rank BETWEEN 1 AND 4),created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS winners(entry_id INTEGER PRIMARY KEY REFERENCES entries(id),rank INTEGER NOT NULL REFERENCES draws(rank),position INTEGER NOT NULL,UNIQUE(rank,position));
            CREATE TABLE IF NOT EXISTS prizes(rank INTEGER PRIMARY KEY CHECK(rank BETWEEN 1 AND 4),name TEXT NOT NULL DEFAULT '상품 미정');
            INSERT OR IGNORE INTO prizes(rank) VALUES(1),(2),(3),(4);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(ip_hash TEXT PRIMARY KEY,count INTEGER NOT NULL,until REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,created REAL NOT NULL);
            ''')
        os.chmod(self.path,0o600)
    @contextmanager
    def db(self,write=False):
        db=sqlite3.connect(self.path,timeout=20,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            if write: db.commit()
        except BaseException:
            if write: db.rollback()
            raise
        finally: db.close()
    def digest(self,value): return hmac.new(self.key,value.encode(),hashlib.sha256).hexdigest()
    def audit(self,db,action): db.execute('INSERT INTO audit(action,created) VALUES(?,?)',(action,time.time()))
    def register(self,nickname,phone,consent):
        if consent is not True: raise Problem(400,'현장 표시 안내에 동의해 주세요.')
        if not isinstance(nickname,str): raise Problem(400,'별명을 입력해 주세요.')
        nickname=unicodedata.normalize('NFKC',nickname).strip()
        if not 1<=len(nickname)<=16 or any(unicodedata.category(c).startswith('C') for c in nickname): raise Problem(400,'별명은 1~16자이며 제어 문자를 사용할 수 없습니다.')
        phone=normalize_phone(phone); token=secrets.token_urlsafe(32)
        with self.db(True) as db:
            if not db.execute('SELECT is_open FROM settings').fetchone()[0]: raise Problem(409,'지금은 접수가 마감되어 있습니다.')
            try:
                cur=db.execute('INSERT INTO entries(nickname,phone_hash,ending,receipt_hash,created) VALUES(?,?,?,?,?)',(nickname,self.digest(phone),phone[-4:],self.digest(token),time.time()))
            except sqlite3.IntegrityError: raise Problem(409,'이미 접수된 번호입니다. 기존 접수 완료 화면을 확인해 주세요.')
            return {'number':cur.lastrowid,'nickname':nickname,'ending':phone[-4:],'receipt':token}
    def receipt(self,token):
        with self.db() as db:
            r=db.execute('SELECT id AS number,nickname,ending FROM entries WHERE receipt_hash=?',(self.digest(token),)).fetchone()
            if not r: raise Problem(404,'접수증을 찾을 수 없습니다.')
            return dict(r)
    def snapshot(self):
        with self.db() as db:
            db.execute('BEGIN')
            s=dict(db.execute('SELECT is_open,view,rank FROM settings').fetchone())
            s['count']=db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
            s['recent']=[dict(r) for r in db.execute('SELECT id AS number,nickname,ending FROM entries ORDER BY id DESC LIMIT 3')]
            s['results']={str(rank):[dict(r) for r in db.execute('SELECT e.id AS number,e.nickname,e.ending FROM winners w JOIN entries e ON e.id=w.entry_id WHERE w.rank=? ORDER BY w.position',(rank,))] for rank in QUOTAS}
            s['prizes']={str(r['rank']):r['name'] for r in db.execute('SELECT * FROM prizes')}
            db.commit(); return s
    def change(self,action,data):
        with self.db(True) as db:
            if action=='registration':
                if not isinstance(data.get('open'),bool): raise Problem(400,'접수 상태를 확인해 주세요.')
                if data['open'] and db.execute('SELECT COUNT(*) FROM draws').fetchone()[0]: raise Problem(409,'추첨 시작 후에는 접수를 다시 열 수 없습니다.')
                db.execute('UPDATE settings SET is_open=?',(int(data['open']),))
            elif action=='screen':
                rank=data.get('rank'); view=data.get('view')
                if type(rank)!=int or rank not in QUOTAS or view not in ('waiting','draw'): raise Problem(400,'화면 설정을 확인해 주세요.')
                db.execute('UPDATE settings SET view=?,rank=?',(view,rank))
            elif action=='prize':
                rank=data.get('rank'); name=data.get('name')
                if type(rank)!=int or rank not in QUOTAS or not isinstance(name,str) or not 1<=len(name.strip())<=80: raise Problem(400,'상품명은 1~80자로 입력해 주세요.')
                if db.execute('SELECT 1 FROM draws WHERE rank=?',(rank,)).fetchone(): raise Problem(409,'추첨이 끝난 등수의 상품은 변경할 수 없습니다.')
                db.execute('UPDATE prizes SET name=? WHERE rank=?',(name.strip(),rank))
            else: raise Problem(404,'지원하지 않는 작업입니다.')
            self.audit(db,action)
        return self.snapshot()
    def draw(self,rank):
        if type(rank)!=int or rank not in QUOTAS: raise Problem(400,'등수를 확인해 주세요.')
        with self.db(True) as db:
            if not db.execute('SELECT 1 FROM draws WHERE rank=?',(rank,)).fetchone():
                s=db.execute('SELECT * FROM settings').fetchone()
                if s['is_open']: raise Problem(409,'접수를 마감한 뒤 추첨해 주세요.')
                if s['view']!='draw' or s['rank']!=rank: raise Problem(409,'먼저 해당 등수의 추첨 화면을 열어 주세요.')
                pool=[r[0] for r in db.execute('SELECT id FROM entries WHERE id NOT IN(SELECT entry_id FROM winners)')]
                if len(pool)<QUOTAS[rank]: raise Problem(409,'추첨 가능한 참가자가 부족합니다.')
                picked=secrets.SystemRandom().sample(pool,QUOTAS[rank])
                db.execute('INSERT INTO draws VALUES(?,?)',(rank,time.time()))
                db.executemany('INSERT INTO winners(entry_id,rank,position) VALUES(?,?,?)',[(eid,rank,pos) for pos,eid in enumerate(picked)])
                self.audit(db,'draw:'+str(rank))
        return self.snapshot()
    def login(self,password,expected,ip):
        now=time.time(); ip_hash=self.digest(ip)
        # Password hash is computed before transaction to avoid locking registration during PBKDF2.
        salt,encoded=expected.split('$'); actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
        valid=hmac.compare_digest(actual,encoded)
        with self.db(True) as db:
            a=db.execute('SELECT count,until FROM attempts WHERE ip_hash=?',(ip_hash,)).fetchone()
            if a and a['until']>now and a['count']>=5: raise Problem(429,'로그인 시도가 많습니다. 10분 뒤 다시 시도해 주세요.')
            if not valid:
                count=a['count']+1 if a and a['until']>now else 1
                db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(ip_hash,count,now+600))
            else:
                token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
                db.execute('DELETE FROM attempts WHERE ip_hash=?',(ip_hash,))
                db.execute('DELETE FROM sessions WHERE expires<?',(now,))
                db.execute('INSERT INTO sessions VALUES(?,?,?)',(self.digest(token),csrf,now+12*3600))
                self.audit(db,'login')
                return token,csrf
        raise Problem(401,'운영자 비밀번호가 올바르지 않습니다.')
    def session(self,token):
        with self.db() as db:
            r=db.execute('SELECT csrf FROM sessions WHERE token_hash=? AND expires>?',(self.digest(token),time.time())).fetchone()
            if not r: raise Problem(401,'운영자 로그인이 필요합니다.')
            return r['csrf']

class App(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,store,password_hash,origin,secure=True):
        self.store,self.password_hash,self.origin,self.secure=store,password_hash,origin,secure
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)
    def log_message(self,*args): pass # Never log POST bodies, receipt tokens or cookies.
    def send(self,status,body,kind='application/json; charset=utf-8',extra=None):
        if not isinstance(body,bytes): body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        headers={'Content-Type':kind,'Content-Length':str(len(body)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}
        if self.server.secure: headers['Strict-Transport-Security']='max-age=31536000'
        headers.update(extra or {})
        for k,v in headers.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def token(self):
        try:
            c=SimpleCookie(self.headers.get('Cookie','')); return c['hope_session'].value if 'hope_session' in c else ''
        except Exception: return ''
    def auth(self,write=False):
        csrf=self.server.store.session(self.token())
        if write and not hmac.compare_digest(csrf,self.headers.get('X-CSRF-Token','')): raise Problem(403,'보안 토큰이 올바르지 않습니다.')
        return csrf
    def do_GET(self):
        try:
            p=urlparse(self.path).path
            if p=='/health': return self.send(200,{'ok':True})
            if p=='/api/status':
                with self.server.store.db() as db: opened=bool(db.execute('SELECT is_open FROM settings').fetchone()[0])
                return self.send(200,{'open':opened})
            if p=='/api/admin/state': self.auth(); return self.send(200,self.server.store.snapshot())
            if p=='/api/admin/session': return self.send(200,{'csrf':self.auth()})
            if p=='/qr.png':
                self.auth()
                import qrcode
                out=io.BytesIO(); qrcode.make(self.server.origin+'/').save(out,format='PNG')
                return self.send(200,out.getvalue(),'image/png')
            allowed={'/':'index.html','/admin':'admin.html','/display':'display.html','/app.js':'app.js','/style.css':'style.css','/original.css':'original.css','/logo.png':'assets/logo.png'}
            if p=='/display': self.auth()
            if p not in allowed or not (ROOT/allowed[p]).exists(): raise Problem(404,'페이지를 찾을 수 없습니다.')
            kind='text/html; charset=utf-8' if allowed[p].endswith('.html') else 'text/css; charset=utf-8' if p.endswith('.css') else 'application/javascript; charset=utf-8' if p.endswith('.js') else 'image/png'
            return self.send(200,(ROOT/allowed[p]).read_bytes(),kind)
        except Problem as e: self.send(e.status,{'error':e.message})
        except Exception: self.send(500,{'error':'서버 오류입니다. 운영자에게 문의해 주세요.'})
    def do_POST(self):
        try:
            if self.headers.get('Origin')!=self.server.origin: raise Problem(403,'접속 주소를 확인해 주세요.')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise Problem(415,'JSON 요청만 지원합니다.')
            try: length=int(self.headers.get('Content-Length','0'))
            except ValueError: raise Problem(400,'잘못된 요청입니다.')
            if not 0<length<=4096: raise Problem(413,'요청 크기를 확인해 주세요.')
            try: d=json.loads(self.rfile.read(length))
            except (ValueError,UnicodeError): raise Problem(400,'잘못된 요청입니다.')
            if not isinstance(d,dict): raise Problem(400,'잘못된 요청입니다.')
            p=urlparse(self.path).path; store=self.server.store
            if p=='/api/register': return self.send(201,store.register(d.get('nickname'),d.get('phone'),d.get('consent')))
            if p=='/api/receipt':
                t=d.get('receipt','')
                if not isinstance(t,str) or len(t)>100: raise Problem(400,'잘못된 접수증입니다.')
                return self.send(200,store.receipt(t))
            if p=='/api/login':
                password=d.get('password','')
                if not isinstance(password,str) or len(password)>256: raise Problem(400,'비밀번호를 확인해 주세요.')
                token,csrf=store.login(password,self.server.password_hash,self.client_address[0])
                return self.send(200,{'csrf':csrf},extra={'Set-Cookie':'hope_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'+('; Secure' if self.server.secure else '')})
            self.auth(True)
            if p=='/api/admin/logout':
                with store.db(True) as db: db.execute('DELETE FROM sessions WHERE token_hash=?',(store.digest(self.token()),))
                return self.send(200,{'ok':True},extra={'Set-Cookie':'hope_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+('; Secure' if self.server.secure else '')})
            if p=='/api/admin/draw': return self.send(200,store.draw(d.get('rank')))
            if p.startswith('/api/admin/'): return self.send(200,store.change(p.rsplit('/',1)[1],d))
            raise Problem(404,'지원하지 않는 작업입니다.')
        except Problem as e: self.send(e.status,{'error':e.message})
        except Exception: self.send(500,{'error':'서버 오류입니다. 운영자에게 문의해 주세요.'})

def main():
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--hash-password',action='store_true'); args=parser.parse_args()
    if args.hash_password:
        import getpass
        p=getpass.getpass('운영자 비밀번호 (16자 이상): ')
        if len(p)<16: raise SystemExit('16자 이상이 필요합니다.')
        salt=secrets.token_bytes(16)
        print(salt.hex()+'$'+hashlib.pbkdf2_hmac('sha256',p.encode(),salt,600000).hex()); return
    origin=os.environ.get('PUBLIC_ORIGIN','').rstrip('/')
    key=os.environ.get('PHONE_HMAC_KEY',''); password_hash=os.environ.get('ADMIN_PASSWORD_HASH','')
    admin_password=os.environ.get('ADMIN_PASSWORD','')
    if not password_hash and len(admin_password)>=16:
        salt=secrets.token_bytes(16)
        password_hash=salt.hex()+'$'+hashlib.pbkdf2_hmac('sha256',admin_password.encode(),salt,600000).hex()
    if not origin.startswith('https://') or len(key)<32 or not re.fullmatch(r'[0-9a-f]{32}\$[0-9a-f]{64}',password_hash): raise SystemExit('HTTPS PUBLIC_ORIGIN, PHONE_HMAC_KEY(32자 이상), ADMIN_PASSWORD(16자 이상) 또는 ADMIN_PASSWORD_HASH를 설정하세요.')
    url=os.environ.get('DATABASE_URL','')
    if not url: raise SystemExit('Supabase DATABASE_URL을 비밀 환경변수로 설정하세요. 운영 모드에서는 임시 SQLite로 대체하지 않습니다.')
    import sys
    sys.modules.setdefault('server',sys.modules[__name__])
    from pgstore import PostgresStore
    store=PostgresStore(url,key.encode())
    try:
        store.snapshot()
    except Exception:
        raise SystemExit('데이터베이스 연결 또는 raffle 스키마를 확인하세요. 자세한 접속 정보는 출력하지 않습니다.')
    App(('0.0.0.0',int(os.environ.get('PORT','8080'))),store,password_hash,origin).serve_forever()
if __name__=='__main__': main()
