import unittest, tempfile, threading, concurrent.futures, json, hashlib, sqlite3, urllib.request, urllib.error
from pathlib import Path
from server import Store, App, Problem, normalize_phone

class RaffleTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'test.sqlite3'
  self.store=Store(self.path,b'test-key-only-never-production-000000')
 def tearDown(self): self.tmp.cleanup()
 def seed(self):
  self.store.change('registration',{'open':True})
  def reg(i): return self.store.register('테스트'+str(i),f'0107000{i:04}',True)
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool: self.entries=list(pool.map(reg,range(150)))
  self.assertEqual(self.store.snapshot()['count'],150)
 def test_normalization_and_storage(self):
  for s in ['010-1234-5678','+82 10 1234 5678','0082-10-1234-5678','０１０１２３４５６７８']:
   self.assertEqual(normalize_phone(s),'01012345678')
  for s in ['0101','010abc12345678','+8201012345678','010-1234-56789']:
   with self.assertRaises(Problem): normalize_phone(s)
  self.store.change('registration',{'open':True})
  r=self.store.register('<img src=x>', '01012345678',True)
  self.assertEqual(self.store.receipt(r['receipt'])['number'],r['number'])
  with self.assertRaises(Problem):self.store.register('다른별명','+82 10-1234-5678',True)
  with self.store.db() as db:
   rows=db.execute('SELECT * FROM entries').fetchall()
   self.assertNotIn('01012345678',str([tuple(r) for r in rows]))
 def test_150_atomic_draw_restore(self):
  self.seed(); self.store.change('screen',{'rank':4,'view':'draw'})
  with self.assertRaises(Problem): self.store.draw(4)
  self.store.change('registration',{'open':False})
  with self.assertRaises(Problem):self.store.register('마감후','01099999999',True)
  self.store.change('prize',{'rank':4,'name':'테스트 상품'})
  with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool: copies=list(pool.map(lambda _:self.store.draw(4),range(12)))
  self.assertTrue(all(x['results']['4']==copies[0]['results']['4'] for x in copies))
  for rank in [3,2,1]:
   self.store.change('screen',{'rank':rank,'view':'draw'});self.store.draw(rank)
  s=self.store.snapshot(); numbers=[e['number'] for result in s['results'].values() for e in result]
  self.assertEqual(len(numbers),12);self.assertEqual(len(set(numbers)),12)
  self.assertEqual([len(s['results'][str(i)]) for i in [1,2,3,4]],[1,5,3,3])
  restored=Store(self.path,b'test-key-only-never-production-000000')
  self.assertEqual(restored.snapshot(),s)
  for rank in [1,2,3,4]:self.assertEqual(restored.draw(rank)['results'],s['results'])
  with self.assertRaises(Problem): restored.change('registration',{'open':True})
  with self.assertRaises(Problem): restored.change('prize',{'rank':4,'name':'변경'})
  self.assertEqual(len(s['recent']),3)
 def test_registration_close_race(self):
  self.store.change('registration',{'open':True})
  def attempt(i):
   try:self.store.register('레이스'+str(i),f'0107777{i:04}',True);return True
   except Problem:return False
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
   futures=[pool.submit(attempt,i) for i in range(100)]
   self.store.change('registration',{'open':False});accepted=sum(f.result() for f in futures)
  self.assertEqual(self.store.snapshot()['count'],accepted)
  with self.assertRaises(Problem):attempt_result=self.store.register('불가','01066666666',True)
 def test_duplicate_race(self):
  self.store.change('registration',{'open':True})
  def reg(i):
   try:self.store.register('동일'+str(i),'01011112222',True);return 1
   except Problem as e:self.assertEqual(e.status,409);return 0
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:self.assertEqual(sum(pool.map(reg,range(40))),1)
 def test_http_mobile_beam_auth_csrf_and_restart(self):
  salt=b'0123456789abcdef';password='test-password-only-1234'
  ph=salt.hex()+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000).hex()
  app=App(('127.0.0.1',0),self.store,ph,'https://event.test',True)
  thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
  base='http://127.0.0.1:'+str(app.server_port)
  def req(path,data=None,cookie='',csrf='',origin='https://event.test'):
   headers={'Origin':origin,'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':csrf}
   r=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
   try:
    with urllib.request.urlopen(r) as res:return res.status,res.read(),res.headers
   except urllib.error.HTTPError as e:return e.code,e.read(),e.headers
  try:
   self.assertEqual(req('/display')[0],401)
   self.assertEqual(req('/api/admin/state')[0],401)
   self.assertEqual(req('/qr.png')[0],401)
   code,body,headers=req('/api/login',{'password':password});self.assertEqual(code,200)
   csrf=json.loads(body)['csrf'];cookie=headers['Set-Cookie'].split(';')[0]
   self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie'])
   self.assertEqual(req('/api/admin/registration',{'open':True},cookie)[0],403)
   self.assertEqual(req('/api/admin/registration',{'open':True},cookie,csrf,origin='https://evil.test')[0],403)
   self.assertEqual(req('/api/admin/registration',{'open':True},cookie,csrf)[0],200)
   for i in range(150):
    code,b,_=req('/api/register',{'nickname':'모바일'+str(i),'phone':f'0108000{i:04}','consent':True});self.assertEqual(code,201)
    if i==0:receipt=json.loads(b)
   self.assertEqual(req('/api/register',{'nickname':'중복','phone':'+82 10 8000 0000','consent':True})[0],409)
   code,b,_=req('/api/admin/state',cookie=cookie);s=json.loads(b)
   self.assertEqual(s['count'],150);self.assertEqual(s['recent'][0]['nickname'],'모바일149')
   self.assertNotIn('phone_hash',b.decode());self.assertNotIn('01080000000',b.decode())
   self.assertEqual(req('/display',cookie=cookie)[0],200)
   self.assertEqual(req('/qr.png',cookie=cookie)[1][:8],b'\x89PNG\r\n\x1a\n')
   self.assertEqual(req('/api/admin/registration',{'open':False},cookie,csrf)[0],200)
   self.assertEqual(req('/api/register',{'nickname':'늦음','phone':'01099999999','consent':True})[0],409)
   for rank in [4,3,2,1]:
    self.assertEqual(req('/api/admin/screen',{'view':'draw','rank':rank},cookie,csrf)[0],200)
    code,b,_=req('/api/admin/draw',{'rank':rank},cookie,csrf);self.assertEqual(code,200)
   results=json.loads(b)['results']
   app.store=Store(self.path,b'test-key-only-never-production-000000')
   self.assertEqual(json.loads(req('/api/admin/state',cookie=cookie)[1])['results'],results)
   self.assertEqual(json.loads(req('/api/receipt',{'receipt':receipt['receipt']})[1])['number'],receipt['number'])
   for rank in [1,2,3,4]:self.assertEqual(json.loads(req('/api/admin/draw',{'rank':rank},cookie,csrf)[1])['results'],results)
   self.assertEqual(req('/api/admin/logout',{},cookie,csrf)[0],200)
   self.assertEqual(req('/api/admin/state',cookie=cookie)[0],401)
  finally:app.shutdown();app.server_close();thread.join()
 def test_insufficient_no_partial_winners(self):
  self.store.change('screen',{'rank':2,'view':'draw'})
  with self.assertRaises(Problem):self.store.draw(2)
  with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM draws').fetchone()[0],0)
 def test_failed_login_commits_rate_limit(self):
  salt=b'0123456789abcdef';h=salt.hex()+'$'+hashlib.pbkdf2_hmac('sha256',b'correct',salt,600000).hex()
  for _ in range(5):
   with self.assertRaises(Problem) as c:self.store.login('bad',h,'test-ip')
   self.assertEqual(c.exception.status,401)
  with self.assertRaises(Problem) as c:self.store.login('correct',h,'test-ip')
  self.assertEqual(c.exception.status,429)

if __name__=='__main__':unittest.main(verbosity=2)
