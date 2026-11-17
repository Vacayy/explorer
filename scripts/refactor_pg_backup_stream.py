import os, subprocess, json, re, time, uuid, select, pathlib, shutil, datetime, sys, signal
h = pathlib.Path.home()
E = os.environ.copy()
E['DOCKER_HOST'] = 'unix://' + str(h / '.colima/default/docker.sock')
lock = dump = None
name = 'explorer-backup-trial-' + uuid.uuid4().hex[:10]
output = None
control = '''import os,sys,json,psycopg
try:
 c=psycopg.connect(os.environ["REFACTOR_POSTGRES_DSN"],autocommit=True)
 locked=c.execute("select pg_try_advisory_lock(hashtextextended('explorer-heavy',0))").fetchone()[0]
 if not locked:
  print(json.dumps({"locked":False}),flush=True); raise SystemExit(0)
 live=os.environ["REFACTOR_FIXTURE_SCHEMA"]; base=os.environ["BACKUP_BASE_SCHEMA"]
 refs=c.execute("select distinct m[1] from information_schema.views v, regexp_matches(v.view_definition, '(refactor_fixture_[0-9a-f]{32})\\\\.', 'g') m where v.table_schema=%s and m[1]<>%s",(live,live)).fetchall()
 schemas=sorted({live,base,*[x[0] for x in refs]})
 size=c.execute("select coalesce(sum(pg_total_relation_size(c.oid)),0) from pg_class c join pg_namespace n on n.oid=c.relnamespace where c.relkind in ('r','m') and n.nspname=any(%s)",(schemas,)).fetchone()[0]
 print(json.dumps({"locked":True,"schemas":schemas,"relation_bytes":int(size)}),flush=True)
 sys.stdin.readline(); c.close()
except Exception as e: print(json.dumps({"error":type(e).__name__}),flush=True)
'''
def vm_free():
 p=subprocess.run(['docker','exec','explorer-refactor-preview-db','df','-Pk','/var/lib/postgresql/data'],env=E,capture_output=True,text=True,timeout=10,check=True)
 return int(p.stdout.splitlines()[1].split()[3])
exit_status = 0
def interrupted(_signum, _frame):
 raise InterruptedError('backup interrupted')
signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
try:
 api=json.loads(subprocess.run(['docker','inspect','explorer-refactor-single-path'],env=E,capture_output=True,check=True).stdout)[0]
 v=dict(x.split('=',1) for x in api['Config']['Env'] if '=' in x)
 base=json.load(open(os.environ.get('REFACTOR_SCHEMA_CONFIG', h/'server-data/review/refactor-single-schema.json')))['base_schema']
 db=json.loads(subprocess.run(['docker','inspect','explorer-refactor-preview-db'],env=E,capture_output=True,check=True).stdout)[0]
 image=db['Image']
 if not re.fullmatch(r'sha256:[0-9a-f]{64}',image): raise ValueError('image')
 for k in ('REFACTOR_POSTGRES_DSN','REFACTOR_FIXTURE_SCHEMA'): E[k]=v[k]
 E['BACKUP_BASE_SCHEMA']=base
 cmd=['docker','run','--rm','-i','--pull=never','--log-driver','none','--network','explorer-refactor-preview-private','--cpus=0.25','--memory=256m','--entrypoint','python','-e','REFACTOR_POSTGRES_DSN','-e','REFACTOR_FIXTURE_SCHEMA','-e','BACKUP_BASE_SCHEMA','explorer-refactor-test:psycopg-3.2.13-auth','-u','-c',control]
 for attempt in range(6):
  lock=subprocess.Popen(cmd,env=E,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
  if not select.select([lock.stdout],[],[],20)[0]: raise TimeoutError('lock')
  info=json.loads(lock.stdout.readline())
  if 'error' in info:
   print('backup failed: lock probe',flush=True); raise SystemExit(1)
  if info.get('locked'): break
  lock.stdin.close(); lock.wait(timeout=10); lock=None; time.sleep(5)
 else: print('backup deferred: heavy lock busy',flush=True); raise SystemExit(1)
 schemas=info['schemas']
 if not schemas or not all(re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',s) for s in schemas): raise ValueError('schema')
 directory=pathlib.Path(os.environ.get('REFACTOR_BACKUP_DIR', h/'server-data/backups/refactor-pg')); directory.mkdir(mode=0o700,parents=True,exist_ok=True)
 before_vm=vm_free(); before_host=shutil.disk_usage(directory).free; floor_vm=2359296
 if before_vm<=floor_vm:
  print('not enough VM space for a backup',flush=True); raise SystemExit(1)
 if before_host<=info['relation_bytes']+3*1024**3:
  print('not enough host space for a backup',flush=True); raise SystemExit(1)
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 partial=directory/(stamp+'-candidate.dump.partial')
 output=os.open(partial,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 cmd=['docker','run','--rm','--pull=never','--log-driver','none','--name',name,'--network','explorer-refactor-preview-private','--cpus=1','--memory=1g','--pids-limit','100','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','-e','REFACTOR_POSTGRES_DSN','--entrypoint','sh',image,'-c','exec pg_dump -d "$REFACTOR_POSTGRES_DSN" -Fc -Z 6 "$@"','sh']
 for s in schemas: cmd+=['-n',s]
 dump=subprocess.Popen(cmd,env=E,stdout=output,stderr=subprocess.DEVNULL); os.close(output); output=None
 low=before_vm; start=time.monotonic(); reason=None
 while dump.poll() is None:
  try: free=vm_free(); low=min(low,free); host=shutil.disk_usage(directory).free
  except Exception: reason='telemetry'; break
  if free<=floor_vm: reason='vm_space'; break
  if host<=3*1024**3: reason='host_space'; break
  if time.monotonic()-start>900: reason='timeout'; break
  time.sleep(2)
 if reason:
  subprocess.run(['docker','kill',name],env=E,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); dump.wait(timeout=30)
  print('backup stopped: '+reason,flush=True); raise SystemExit(1)
 if dump.returncode!=0 or not partial.exists() or partial.stat().st_size==0:
  print('backup dump failed',flush=True); raise SystemExit(1)
 verify=['docker','run','--rm','--pull=never','--log-driver','none','--network','none','--cpus=1','--memory=512m','--user','0','--entrypoint','sh','-v',str(directory)+':/backup:ro',image,'-c','set -e; sha256sum "/backup/$1"; pg_restore --list "/backup/$1"','sh',partial.name]
 result=subprocess.run(verify,env=E,capture_output=True,text=True,timeout=300,check=True); digest=result.stdout.split()[0]
 present=set(re.findall(r'refactor_fixture_[0-9a-f]{32}',result.stdout))
 if not re.fullmatch(r'[0-9a-f]{64}',digest) or not set(schemas)<=present: raise ValueError('archive validation')
 final=directory/(stamp+'-candidate.dump'); sha=directory/(stamp+'-candidate.dump.sha256')
 if final.exists() or sha.exists(): raise FileExistsError('destination')
 os.rename(partial,final); fd=os.open(sha,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f: f.write(digest+'  '+final.name+'\n')
 print(str(final),flush=True)
except SystemExit as e: exit_status = int(e.code or 0)
except Exception as e:
 print('backup failed: '+type(e).__name__,flush=True); exit_status = 1
finally:
 if output is not None: os.close(output)
 if dump is not None and dump.poll() is None:
  subprocess.run(['docker','kill',name],env=E,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); dump.wait(timeout=30)
 if lock is not None:
  try: lock.stdin.write('\n'); lock.stdin.flush(); lock.wait(timeout=15)
  except Exception: lock.kill(); lock.wait()

sys.exit(exit_status)
