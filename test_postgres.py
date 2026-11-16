"""Run inherited integration cases against isolated local PostgreSQL databases.
Never use a Supabase/production URL here; local TCP host only.
"""
import os,uuid,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import psycopg
from psycopg import sql
from pgstore import PostgresStore
from test_app import RaffleTest

class PostgresRaffleTest(RaffleTest):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'not-a-production-db'
  self.name='hope_test_'+uuid.uuid4().hex
  self.admin='postgresql://postgres@127.0.0.1:55432/postgres'
  with psycopg.connect(self.admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
  self.url='postgresql://postgres@127.0.0.1:55432/'+self.name
  self.store=PostgresStore(self.url,b'test-key-only-never-production-000000',initialize=True,sslmode='disable')
  self.patcher=patch('test_app.Store',lambda path,key:PostgresStore(self.url,key,sslmode='disable'))
  self.patcher.start()
 def tearDown(self):
  self.patcher.stop()
  with psycopg.connect(self.admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.name)))
  self.tmp.cleanup()
 def test_database_api_roles_have_no_access(self):
  with self.store.connect() as c:
   self.assertEqual(c.execute("SELECT has_schema_privilege('public','raffle','USAGE') AS allowed").fetchone()['allowed'],False)
   self.assertTrue(all(r['relrowsecurity'] for r in c.execute("SELECT relrowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='raffle' AND relkind='r'")))

if __name__=='__main__':
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(PostgresRaffleTest)
 r=unittest.TextTestRunner(verbosity=2).run(suite)
 raise SystemExit(not r.wasSuccessful())
