import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker from '../src/index.js';
const origin='https://fabrik.test';
const step='Tester la capsule avec les accès Rachel existants';
async function fixture(){
 const sqlite=new DatabaseSync(':memory:');sqlite.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
 const tokenHash=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('session'))).toString('hex');
 sqlite.prepare('INSERT INTO leads(id,email,name,company,created_at) VALUES(?,?,?,?,?)').run('lead','test@example.com','Philippe','Décisions & Co','2026-01-01');
 sqlite.prepare('INSERT INTO verification_tokens(token_hash,lead_id,expires_at,used_at,created_at) VALUES(?,?,?,?,?)').run(tokenHash,'lead','2027-01-01','2026-01-01','2026-01-01');
 const env={PUBLIC_BASE_URL:origin,LEAD_CALLBACK_SECRET:'test',RESEND_API_KEY:'test',ADMIN_TOKEN:'admin-secret',GITHUB_TOKEN:'test',DB:{prepare(sql){let values=[];return {bind(...v){values=v;return this},async first(){return sqlite.prepare(sql).get(...values)||null},async run(){return {meta:{changes:Number(sqlite.prepare(sql).run(...values).changes)}}}}}}};
 const req=(path,body,admin=false)=>worker.fetch(new Request(origin+path,{method:body?'POST':'GET',headers:{cookie:'rachel_session=session','content-type':'application/json',...(admin?{authorization:'Bearer admin-secret'}:{})},...(body?{body:JSON.stringify(body)}:{})}),env);
 return {sqlite,env,req};
}
async function mockedFetch(handler,operation){const saved=globalThis.fetch;globalThis.fetch=handler;try{return await operation()}finally{globalThis.fetch=saved}}
const ok=data=>new Response(JSON.stringify(data),{headers:{'content-type':'application/json'}});
const body={companyName:'Baresto',site:'https://baresto.fr/',rachelImage:'Rachel Restauration',sourceText:'Texte factuel '.repeat(20)};

test('failure is synchronized, inputs retained, retry reuses the row and rejects a double click',async()=>{
 const {sqlite,req}=await fixture();let dispatched=0;let key;
 await mockedFetch(async(url,options)=>{
  if(options?.method==='POST'){dispatched++;key=JSON.parse(options.body).inputs.request_key;return new Response(null,{status:204})}
  if(url.includes('/jobs'))return ok({jobs:[{steps:[{name:step,conclusion:'failure'}]}]});
  return ok({workflow_runs:[{id:42,display_title:'La Fabrik · '+key,status:'completed',conclusion:'failure'}]});
 },async()=>{
  const first=await req('/api/request',body);assert.equal(first.status,201);const id=(await first.json()).id;
  const me=await (await req('/api/me')).json();assert.equal(me.request.status,'failed');assert.equal(me.request.company_name,'Baresto');assert.equal(me.request.source_text,body.sourceText.trim());
  const retryKey=me.request.generation_key;
  const retry=await req('/api/request',{...body,retryId:id,retryKey});assert.equal(retry.status,201);assert.equal((await retry.json()).id,id);
  const again=await req('/api/request',{...body,retryId:id,retryKey});assert.equal(again.status,400);assert.equal(dispatched,2);
  assert.equal(sqlite.prepare('SELECT count(*) as n FROM requests').get().n,1);
 });
});
test('successful generation blocks retry even when artifact upload failed',async()=>{
 const {req}=await fixture();let key;
 await mockedFetch(async(url,options)=>{
  if(options?.method==='POST'){key=JSON.parse(options.body).inputs.request_key;return new Response(null,{status:204})}
  if(url.includes('/jobs'))return ok({jobs:[{steps:[{name:step,conclusion:'success'}]}]});
  return ok({workflow_runs:[{id:43,display_title:'La Fabrik · '+key,status:'completed',conclusion:'failure'}]});
 },async()=>{
  const id=(await (await req('/api/request',body)).json()).id;
  assert.equal((await (await req('/api/me')).json()).request.status,'completed');
  assert.equal((await req('/api/request',{...body,retryId:id})).status,400);
 });
});
test('unknown GitHub status never unlocks a paid request',async()=>{
 const {req}=await fixture();
 await mockedFetch(async(url,options)=>options?.method==='POST'?new Response(null,{status:204}):ok({workflow_runs:[]}),async()=>{
  const id=(await (await req('/api/request',body)).json()).id;
  assert.equal((await req('/api/request',{...body,retryId:id})).status,400);
  assert.equal((await req('/api/admin/unlock',{id,confirmFailed:true},true)).status,400);
 });
});
test('legacy unlock is authenticated and keeps the record and quotas',async()=>{
 const {sqlite,req}=await fixture();
 sqlite.prepare("INSERT INTO requests(id,lead_id,company_site,company_domain,rachel_image,github_run_status,status,created_at,updated_at) VALUES('old','lead','https://baresto.fr/','baresto.fr','Rachel Restauration','dispatched','queued','2026-01-01','2026-01-01')").run();
 assert.equal((await req('/api/admin/unlock',{id:'old',confirmFailed:true})).status,403);
 assert.equal((await req('/api/admin/unlock',{id:'old'},true)).status,400);
 assert.equal((await req('/api/admin/unlock',{id:'old',confirmFailed:true},true)).status,200);
 assert.equal(sqlite.prepare("SELECT status FROM requests WHERE id='old'").get().status,'failed');
 await mockedFetch(async()=>new Response(null,{status:204}),async()=>{
  assert.equal((await req('/api/request',body)).status,400); // New request remains subject to quotas.
  assert.equal((await req('/api/request',{...body,retryId:'old'})).status,201);
 });
});
test('retry rejects a request owned by another lead and explicit dispatch refusal permits correction',async()=>{
 const {sqlite,req}=await fixture();
 await mockedFetch(async()=>new Response(null,{status:422}),async()=>{
  assert.equal((await req('/api/request',body)).status,400);
  const row=sqlite.prepare('SELECT * FROM requests').get();assert.equal(row.status,'failed');
  sqlite.prepare("UPDATE requests SET lead_id='someone-else' WHERE id=?").run(row.id);
  assert.equal((await req('/api/request',{...body,retryId:row.id})).status,400);
 });
});
test('tracking API error preserves request and displays a warning',async()=>{
 const {req}=await fixture();
 await mockedFetch(async(url,options)=>options?.method==='POST'?new Response(null,{status:204}):new Response(null,{status:403}),async()=>{
  assert.equal((await req('/api/request',body)).status,201);
  const data=await (await req('/api/me')).json();assert.equal(data.request.status,'queued');assert.match(data.trackingWarning,/indisponible/);
 });
});
test('migration preserves previous requests and constraints',()=>{
 const sqlite=new DatabaseSync(':memory:');
 const schema=readFileSync(new URL('../schema.sql',import.meta.url),'utf8').replace('  company_name TEXT,\n  generation_key TEXT,\n  github_run_id TEXT,\n','');sqlite.exec(schema);
 sqlite.exec("INSERT INTO requests(id,lead_id,company_site,company_domain,rachel_image,github_run_status,status,created_at,updated_at) VALUES('old','lead','https://baresto.fr','baresto.fr','Rachel Restauration','dispatched','queued','2026-01-01','2026-01-01')");
 sqlite.exec(readFileSync(new URL('../migrations/0002_request_retry_tracking.sql',import.meta.url),'utf8'));
 assert.equal(sqlite.prepare('SELECT generation_key FROM requests').get().generation_key,null);
 assert.equal(sqlite.prepare('SELECT count(*) as n FROM requests').get().n,1);
});

test('the emitted retry button restores fields and sends the same attempt reference',async()=>{
 const {default:vm}=await import('node:vm');
 const html=await (await worker.fetch(new Request(origin),{})).text();
 const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
 const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],{value:'',hidden:true,textContent:'',dataset:{},classList:{toggle(){}},listeners:{},addEventListener(e,f){this.listeners[e]=f},dispatchEvent(e){this.listeners[e.type]?.()},focus(){},querySelector(){return this.button}}]));
 nodes.get('request').button={dataset:{},textContent:'Lancer ma capsule'};
 const previous={id:'failed-id',status:'failed',company_name:'Baresto',company_site:'https://baresto.fr/',source_text:'Texte factuel '.repeat(20),rachel_image:'Rachel Restauration',siren:'123456789',generation_key:'old-key'};
 let payload;let polls=0;
 const context={document:{hidden:false,getElementById:id=>nodes.get(id)},location:{href:origin},history:{replaceState(){}},localStorage:{getItem(){return ''},setItem(){}},URL,Event:class{constructor(type){this.type=type}},setInterval(){polls++},FormData:class{*[Symbol.iterator](){for(const key of ['companyName','site','sourceText','siren','rachelImage'])yield [key,nodes.get(key).value]}},fetch:async(url,options)=>({ok:true,text:async()=>JSON.stringify(url==='/api/me'?{company:'Décisions & Co',request:previous}:{...(payload=JSON.parse(options.body)),id:'failed-id',status:'queued'})})};
 vm.createContext(context);vm.runInContext(script,context);await new Promise(r=>setImmediate(r));
 assert.equal(nodes.get('retry').hidden,false);nodes.get('retry').listeners.click();
 assert.equal(nodes.get('request-stage').hidden,false);assert.equal(nodes.get('companyName').value,'Baresto');assert.equal(nodes.get('sourceText').value,previous.source_text);assert.match(nodes.get('rachel-preview').src,/Restauration/);
 await nodes.get('request').listeners.submit({preventDefault(){},currentTarget:nodes.get('request')});
 assert.equal(payload.retryId,'failed-id');assert.equal(payload.retryKey,'old-key');assert.equal(payload.companyName,'Baresto');assert.equal(polls,1);
});

test('a recent legacy request unlocks immediately only with a matching failed workflow',async()=>{
 const {sqlite,req}=await fixture();const timestamp=new Date().toISOString();
 sqlite.prepare("INSERT INTO requests(id,lead_id,company_site,company_domain,rachel_image,github_run_status,status,created_at,updated_at) VALUES('recent','lead','https://baresto.fr/','baresto.fr','Rachel Restauration','dispatched','queued',?,?)").run(timestamp,timestamp);
 assert.equal((await req('/api/admin/unlock',{id:'recent',confirmFailed:true},true)).status,400);
 let status='in_progress';let conclusion='failure';let generated=false;let wrongDate=false;
 await mockedFetch(async url=>url.includes('/jobs')?ok({jobs:[{steps:[{name:step,conclusion:generated?'success':'failure'}]}]}):ok({id:99,event:'workflow_dispatch',path:'.github/workflows/rachel-entreprises-test.yml',status,conclusion,created_at:wrongDate?'2020-01-01':timestamp}),async()=>{
  const data={id:'recent',confirmFailed:true,runId:'https://github.com/philippelecam-jpg/dco-agent-editorial/actions/runs/99'};
  assert.equal((await req('/api/admin/unlock',data,true)).status,400);
  status='completed';conclusion='success';assert.equal((await req('/api/admin/unlock',data,true)).status,400);
  conclusion='failure';generated=true;assert.equal((await req('/api/admin/unlock',data,true)).status,400);
  generated=false;wrongDate=true;assert.equal((await req('/api/admin/unlock',data,true)).status,400);
  wrongDate=false;assert.equal((await req('/api/admin/unlock',data,true)).status,200);
  assert.equal(sqlite.prepare("SELECT status FROM requests WHERE id='recent'").get().status,'failed');
 });
});

async function signedResult(env,payload,valid=true){
 const timestamp=String(Math.floor(Date.now()/1000));const body=JSON.stringify(payload);
 const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(env.LEAD_CALLBACK_SECRET),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const signature=Buffer.from(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(timestamp+'.'+body))).toString('hex');
 return worker.fetch(new Request(origin+'/api/capsule-result',{method:'POST',headers:{'content-type':'application/json','x-lead-timestamp':timestamp,'x-lead-signature':valid?signature:'0'.repeat(64)},body}),env);
}
test('signed publication displays the link and emails the stored recipient exactly once',async()=>{
 const {env,req,sqlite}=await fixture();let sends=0;
 await mockedFetch(async(url,options)=>{
  if(url.includes('api.resend.com')){sends++;const mail=JSON.parse(options.body);assert.equal(mail.to,'test@example.com');assert.match(mail.html,/aBcD1234_-Z/);assert.match(options.headers['Idempotency-Key'],/^capsule-/);return ok({id:'email-1'});}
  return new Response(null,{status:204});
 },async()=>{
  const id=(await (await req('/api/request',body)).json()).id;const row=sqlite.prepare('SELECT * FROM requests WHERE id=?').get(id);
  const result={request_id:id,request_key:row.generation_key,github_run_id:'99',status:'published',youtube_id:'aBcD1234_-Z',email:'attacker@example.com'};
  assert.equal((await signedResult(env,result,false)).status,403);assert.equal(sends,0);
  assert.equal((await signedResult(env,result)).status,200);assert.equal((await signedResult(env,result)).status,200);
  const data=await (await req('/api/me')).json();assert.equal(data.request.status,'published');assert.equal(data.request.delivery_status,'sent');assert.equal(data.request.youtube_url,'https://www.youtube.com/watch?v=aBcD1234_-Z');assert.equal(sends,1);
  assert.equal((await signedResult(env,{...result,request_key:'outdated'})).status,409);
 });
});
test('failed email delivery is retried with the same idempotency key without regenerating video',async()=>{
 const {env,req,sqlite}=await fixture();let sends=0;const keys=[];
 await mockedFetch(async(url,options)=>{
  if(url.includes('api.resend.com')){keys.push(options.headers['Idempotency-Key']);sends++;return sends===1?new Response(null,{status:403}):ok({id:'email-2'});}
  return new Response(null,{status:204});
 },async()=>{
  const id=(await (await req('/api/request',body)).json()).id;const row=sqlite.prepare('SELECT * FROM requests').get();
  assert.equal((await signedResult(env,{request_id:id,request_key:row.generation_key,github_run_id:'99',status:'published',youtube_id:'aBcD1234_-Z'})).status,200);
  assert.equal(sqlite.prepare('SELECT delivery_status FROM requests').get().delivery_status,'failed');
  assert.equal((await (await req('/api/me')).json()).request.delivery_status,'sent');assert.equal(keys[0],keys[1]);
 });
});
test('publication failure preserves the existing video and dispatches only an upload workflow',async()=>{
 const {env,req,sqlite}=await fixture();const dispatches=[];
 await mockedFetch(async(_url,options)=>{dispatches.push(JSON.parse(options.body));return new Response(null,{status:204})},async()=>{
  const id=(await (await req('/api/request',body)).json()).id;const row=sqlite.prepare('SELECT * FROM requests').get();
  assert.equal((await signedResult(env,{request_id:id,request_key:row.generation_key,github_run_id:'99',status:'completed',error:'Publication refusée'})).status,200);
  assert.equal((await req('/api/request',{...body,retryId:id,retryKey:row.generation_key})).status,400);
  assert.equal((await req('/api/publish',{id})).status,201);assert.equal(dispatches[1].inputs.mode,'youtube_existing');assert.equal(dispatches[1].inputs.video_run_id,'99');
  assert.equal((await req('/api/publish',{id})).status,400);assert.equal(dispatches.length,2);
 });
});
test('an ambiguous YouTube upload cannot be repeated automatically',async()=>{
 const {env,req,sqlite}=await fixture();
 await mockedFetch(async()=>new Response(null,{status:204}),async()=>{
  const id=(await (await req('/api/request',body)).json()).id;const row=sqlite.prepare('SELECT * FROM requests').get();
  await signedResult(env,{request_id:id,request_key:row.generation_key,github_run_id:'99',status:'completed',publication_pending:true});
  assert.equal((await req('/api/publish',{id})).status,400);
 });
});

test('an email with an expired deduplication window requires review instead of another send',async()=>{
 const {env,req,sqlite}=await fixture();let sends=0;
 await mockedFetch(async(url)=>{if(url.includes('api.resend.com')){sends++;return new Response(null,{status:500})}return new Response(null,{status:204})},async()=>{
  const id=(await (await req('/api/request',body)).json()).id;const row=sqlite.prepare('SELECT * FROM requests').get();
  await signedResult(env,{request_id:id,request_key:row.generation_key,github_run_id:'99',status:'published',youtube_id:'aBcD1234_-Z'});
  sqlite.prepare('UPDATE requests SET delivery_attempted_at=? WHERE id=?').run(new Date(Date.now()-24*60*60*1000).toISOString(),id);
  assert.equal((await (await req('/api/me')).json()).request.delivery_status,'review_required');assert.equal(sends,1);
 });
});
test('YouTube delivery migration preserves existing request and tracking fields',()=>{
 const sqlite=new DatabaseSync(':memory:');let schema=readFileSync(new URL('../schema.sql',import.meta.url),'utf8');
 for(const column of ['youtube_id TEXT','youtube_url TEXT',"publication_status TEXT DEFAULT 'none'","delivery_status TEXT DEFAULT 'pending'",'delivery_error TEXT','delivery_attempted_at TEXT','delivery_lease_until TEXT','notified_at TEXT'])schema=schema.replace('  '+column+',\n','');
 sqlite.exec(schema);sqlite.exec("INSERT INTO requests(id,lead_id,company_name,generation_key,github_run_id,company_site,company_domain,rachel_image,github_run_status,status,created_at,updated_at) VALUES('previous','lead','Baresto','key','99','https://baresto.fr','baresto.fr','Rachel Restauration','completed','completed','2026-01-01','2026-01-01')");
 sqlite.exec(readFileSync(new URL('../migrations/0003_youtube_delivery.sql',import.meta.url),'utf8'));
 const row=sqlite.prepare('SELECT * FROM requests').get();assert.equal(row.generation_key,'key');assert.equal(row.github_run_id,'99');assert.equal(row.youtube_url,null);assert.equal(row.status,'completed');
});
