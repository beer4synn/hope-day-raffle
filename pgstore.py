"""Supabase PostgreSQL persistence. No browser database key or REST exposure."""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from server import Store

class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

class Cursor:
    def __init__(self,cursor,lastrowid=None): self.cursor,self.lastrowid=cursor,lastrowid
    def fetchone(self):
        r=self.cursor.fetchone(); return Row(r) if r is not None else None
    def fetchall(self): return [Row(r) for r in self.cursor.fetchall()]
    def __iter__(self): return iter(self.fetchall())

class Connection:
    def __init__(self,conn): self.conn=conn
    def execute(self,sql,args=None):
        # Store.snapshot starts a read transaction itself for SQLite. PostgreSQL
        # transactions are already started by PostgresStore.db.
        if sql.strip().upper()=='BEGIN': return None
        sql=sql.replace('?','%s')
        if sql.startswith('INSERT OR REPLACE INTO attempts VALUES'):
            sql=sql.replace('INSERT OR REPLACE','INSERT')+' ON CONFLICT(ip_hash) DO UPDATE SET count=EXCLUDED.count,until=EXCLUDED.until'
        returning=sql.startswith('INSERT INTO entries(')
        if returning: sql+=' RETURNING id'
        try:
            cursor=self.conn.execute(sql,args)
            return Cursor(cursor,cursor.fetchone()['id'] if returning else None)
        except psycopg.IntegrityError as e:
            raise sqlite3.IntegrityError('Database constraint rejected write') from e
    def executemany(self,sql,rows):
        with self.conn.cursor() as cur: cur.executemany(sql.replace('?','%s'),rows)
    def commit(self): self.conn.commit()

class PostgresStore(Store):
    def __init__(self,url,key,initialize=False,sslmode='require'):
        self.url,self.key,self.sslmode=url,key,sslmode
        self.slots=threading.BoundedSemaphore(8)
        if initialize:
            with self.connect() as conn:
                conn.execute('BEGIN')
                conn.execute('SELECT pg_advisory_xact_lock(73419823)')
                conn.execute((Path(__file__).parent/'supabase-schema.sql').read_text())
                conn.commit()
    def connect(self):
        return psycopg.connect(self.url,autocommit=True,row_factory=dict_row,
            prepare_threshold=None,connect_timeout=10,sslmode=self.sslmode)
    @contextmanager
    def db(self,write=False):
        with self.slots, self.connect() as conn:
            conn.execute('BEGIN' if write else 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute('SET LOCAL search_path = raffle, pg_catalog')
            conn.execute("SET LOCAL statement_timeout = '20s'")
            conn.execute("SET LOCAL lock_timeout = '15s'")
            try:
                # Serializes every mutation across processes, including closing,
                # registering and selecting different ranks concurrently.
                if write: conn.execute('SELECT pg_advisory_xact_lock(73419823)')
                yield Connection(conn)
                conn.commit()
            except BaseException:
                conn.rollback(); raise
