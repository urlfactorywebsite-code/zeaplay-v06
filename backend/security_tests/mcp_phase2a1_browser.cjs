/* Real browser HTTP/security checks. Only owned loopback stack, real login. */
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const {randomUUID}=require('node:crypto');
const {chromium}=require(process.env.ZEA_PLAYWRIGHT_MODULE);
const state=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.match(state.origin,/^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(execFileSync('docker',['inspect','--format','{{index .Config.Labels "zea.phase15"}}',state.backend],{encoding:'utf8',windowsHide:true}).trim(),state.run);
const diagnostic=process.argv.includes('--diagnostic'), results=[], observations=[];
const seeded=diagnostic?null:JSON.parse(execFileSync('docker',['exec',state.backend,'python','-B','/tests/mcp_phase2a1_cases.py','seed-http'],{encoding:'utf8',windowsHide:true}).trim().split('\n').at(-1));
const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAI0lEQVR4nGPUjW5iIAUwkaSaYVQDcYCJSHVwMKqBGEByKAEAYHQBKidPM/kAAAAASUVORK5CYII=';
function safe(message){return String(message).split(state.password).join('[REDACTED]').replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g,'[REDACTED_TOKEN]');}
async function request(page,url,{token='',method='GET',body,cache}={}) {
  assert(url.startsWith('/')&&!url.startsWith('//'));
  return page.evaluate(async({url,token,method,body,cache})=>{
    const response=await fetch(url,{method,cache,headers:{...(token?{Authorization:'Bearer '+token}:{}),'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
    const text=await response.text();let data;try{data=JSON.parse(text)}catch{data=null}
    return {status:response.status,data,type:response.headers.get('content-type'),cacheControl:response.headers.get('cache-control'),vary:response.headers.get('vary'),bytes:text.length};
  },{url,token,method,body,cache});
}
async function login(page,name) {
  const r=await request(page,'/api/auth/login',{method:'POST',body:{email:name+'@phase15.example.com',password:state.password}});
  assert.equal(r.status,200,'Fixture login HTTP status');return r.data.token.access_token;
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.ZEA_CHROMIUM_EXE,args:['--disable-background-networking','--no-first-run']});
  const ctx=await browser.newContext({serviceWorkers:'block'});
  await ctx.route('**/*',route=>new URL(route.request().url()).origin===state.origin?route.continue():route.abort());
  const p=await ctx.newPage();await p.goto(state.origin+'/runtime-config.js');
  async function test(name,work){try{await work();const status=diagnostic||name.startsWith('M06_')?'DIAGNOSTIC':'PASS';results.push({name,status});console.log(status+' '+name)}catch(e){results.push({name,status:'FAIL',reason:safe(e.message).slice(0,350)});console.log('FAIL '+name+': '+safe(e.message).slice(0,200));}}
  try {
    const owner=await login(p,'owner'), member=await login(p,'member'), watcher=await login(p,'watcher'), manager=await login(p,'manager'), foreign=await login(p,'foreign');
    let avatar;
    await test('M01_real_avatar_creation_and_authorized_read',async()=>{
      const made=await request(p,'/api/avatars',{method:'POST',token:owner,body:{name:'Phase2A1 synthetic',storage_type:'data_url',data_url:png}});
      assert.equal(made.status,201);avatar=made.data.id;
      assert.equal((await request(p,'/api/avatars/'+avatar+'/image',{token:owner})).status,200);
    });
    await test('M02_avatar_cache_cannot_bypass_foreign_authority',async()=>{
      assert(avatar);
      const response=await request(p,'/api/avatars/'+avatar+'/image',{token:foreign});
      const uncached=await request(p,'/api/avatars/'+avatar+'/image',{token:foreign,cache:'no-store'});
      observations.push({name:'avatar_cache',cached_status:response.status,network_status:uncached.status});
      if(!diagnostic) assert.equal(response.status,404);
      assert.equal(uncached.status,404);
    });
    await test('M03_avatar_requires_authentication_and_rejects_unsafe_url',async()=>{
      assert.equal((await request(p,'/api/avatars/'+avatar+'/image',{cache:'no-store'})).status,401);
      const r=await request(p,'/api/avatars',{token:owner,method:'POST',body:{name:'unsafe',storage_type:'external_url',external_url:'javascript:alert(1)'}});
      assert.equal(r.status,422);
    });
    let upload;
    await test('M04_real_legacy_upload_owner_metadata',async()=>{
      upload=await p.evaluate(async token=>{
        const body=new FormData();body.append('file',new Blob(['phase2a1 synthetic bytes'],{type:'text/plain'}),'phase2a1.txt');
        const r=await fetch('/api/media/upload',{method:'POST',headers:{Authorization:'Bearer '+token},body});return {status:r.status,data:await r.json()};
      },owner);
      assert.equal(upload.status,201);
      assert.equal((await request(p,'/api/media/'+upload.data.id,{token:owner})).status,200);
    });
    await test('M05_foreign_legacy_list_and_mutation_denied',async()=>{
      const listing=await request(p,'/api/media',{token:foreign});assert.equal(listing.status,200);
      if(!diagnostic) assert(!listing.data.items.some(x=>x.id===upload.data.id));
      for(const method of ['GET','PATCH','DELETE']) {
        const r=await request(p,'/api/media/'+upload.data.id,{token:foreign,method,body:method==='PATCH'?{filename:'foreign.txt'}:undefined});
        observations.push({name:'foreign_legacy_'+method,status:r.status});
        if(!diagnostic) {
          assert.equal(r.status,404);
          const missing=await request(p,'/api/media/'+randomUUID(),{token:foreign,method,body:method==='PATCH'?{filename:'foreign.txt'}:undefined});
          assert.equal(missing.status,404);assert.deepEqual(r.data,missing.data);
          const sameTenantDenied=await request(p,'/api/media/'+upload.data.id,{token:member,method,body:method==='PATCH'?{filename:'other.txt'}:undefined});
          assert.equal(sameTenantDenied.status,403,'Existing same-tenant nonowner rule preserved');
        }
      }
      if(!diagnostic)assert.equal((await request(p,'/api/media/'+upload.data.id,{token:manager})).status,200,'Existing same-tenant staff read preserved');
    });
    await test('M06_legacy_static_bytes_policy_diagnostic',async()=>{
      // No expectation of private bytes is invented: report existing capability.
      const r=await request(p,'/api/'+upload.data.storage_path,{cache:'no-store'});
      observations.push({name:'legacy_static_bytes',unauthenticated_status:r.status,content_type:r.type,bytes:r.bytes});
      assert.equal(r.status,200,'Reproduce existing public byte-serving policy');
      assert(r.type.includes('text/plain'));
    });
    await test('M07_unauthorized_media_and_presign_requests',async()=>{
      assert.equal((await request(p,'/api/media/external/connect',{method:'POST',body:{provider:'local'}})).status,401);
      assert.equal((await request(p,'/api/media/presign',{method:'POST',body:{purpose:'library',tab:'images',file_name:'x.png',content_type:'image/png',size_bytes:8}})).status,401);
      assert.equal((await request(p,'/api/media/presign',{method:'POST',token:owner,body:{purpose:'library',tab:'images',file_name:'x.exe',content_type:'application/octet-stream',size_bytes:8}})).status,400);
    });
    if(!diagnostic) {
      await test('M08_foreign_presigned_media_is_not_enumerated_or_modified',async()=>{
        for(const prefix of ['/api','/api/api']) {
          for(const token of [owner,manager]) {
            const listed=await request(p,prefix+'/media/list?tab=images',{token});assert.equal(listed.status,200);assert.equal(listed.data.total,0);
          }
          for(const token of [owner,manager,member]) for(const endpoint of ['/media/confirm','/media/avatar/finalize']) {
            const crop={x:0,y:0,width:1,height:1,rotate:0};
            const r=await request(p,prefix+endpoint,{token,method:'POST',body:{file_id:seeded.foreign_media_file,crop}});
            const missing=await request(p,prefix+endpoint,{token,method:'POST',body:{file_id:randomUUID(),crop}});
            assert.equal(r.status,404);assert.equal(missing.status,404);assert.deepEqual(r.data,missing.data);
          }
          assert.equal((await request(p,prefix+'/media/'+seeded.foreign_media_file,{token:owner,method:'DELETE'})).status,404);
        }
      });
      await test('C01_cross_tab_identity_change_discards_stale_bootstrap',async()=>{
        const a=await ctx.newPage(), b=await ctx.newPage();
        async function ui(page,user) {
          await page.goto(state.origin+'/#/login');
          await page.locator('#email-address').fill(user+'@phase15.example.com');await page.locator('#password').fill(state.password);
          await page.locator('#password').press('Enter');
          await page.waitForURL(url=>url.hash && !['#/','#'].includes(url.hash) && !url.hash.includes('/login'));
        }
        await ui(a,'owner');
        let heldResolve, releaseResolve, first=true;
        const held=new Promise(resolve=>heldResolve=resolve), release=new Promise(resolve=>releaseResolve=resolve);
        await a.route(state.origin+'/api/auth/me',async route=>{
          if(!first)return route.continue();first=false;
          const response=await route.fetch(); // The real backend authenticates the old session.
          heldResolve();await release;await route.fulfill({response}).catch(()=>{});
        });
        await a.reload();await held;await ui(b,'foreign');releaseResolve();
        await a.getByRole('button').filter({hasText:'Fixture foreign'}).first().waitFor();
        const current=await a.evaluate(()=>{const c=JSON.parse(atob(localStorage.getItem('vee_access_token').split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));return {sub:c.sub,tenant:c.tenant_id};});
        assert.equal(current.sub,state.fixture.users.foreign);assert.equal(current.tenant,state.fixture.foreign);
        await b.getByRole('button').filter({hasText:'Fixture foreign'}).first().click();await b.getByRole('button',{name:'Logout',exact:true}).first().click();
        await a.waitForURL(url=>url.hash.includes('/login'));await a.close();await b.close();
      });
      await test('E01_task_page_roles_and_grouped_assignment_visibility',async()=>{
        for(const prefix of ['/api','/api/api']) {
          const list=await request(p,prefix+'/tasks/page?page_size=1',{token:member});assert.equal(list.status,200);assert(list.data.items.length<=1);
          // R01 can transfer this assignment through the real approval workflow.
          // Establish current ownership through an authorized real read.
          const current=await request(p,prefix+'/tasks/assigned',{token:owner});assert.equal(current.status,200);
          const assigned=current.data.assigned_to_id===state.fixture.users.member?member:watcher;
          assert([state.fixture.users.member,state.fixture.users.watcher].includes(current.data.assigned_to_id));
          const tasks=await request(p,prefix+'/tasks/page',{token:assigned});assert.equal(tasks.status,200);
          assert(tasks.data.items.some(t=>t.id==='assigned'));assert(!tasks.data.items.some(t=>['sibling','foreign-task'].includes(t.id)));
          const overdue=await request(p,prefix+'/tasks/page?quick_filter=overdue',{token:assigned});assert.equal(overdue.status,200);
          assert(overdue.data.items.some(t=>t.id==='assigned'));assert(!overdue.data.items.some(t=>['sibling','foreign-task'].includes(t.id)));
          const first=await request(p,prefix+'/tasks/page?page_size=1',{token:owner});assert.equal(first.status,200);assert(first.data.next_cursor);
          const next=await request(p,prefix+'/tasks/page?page_size=1&cursor='+encodeURIComponent(first.data.next_cursor),{token:owner});assert.equal(next.status,200);
          assert(next.data.items.length<=1);assert(next.data.items.every(t=>t.id!==first.data.items[0].id && t.id!=='foreign-task'));
          const group=await request(p,prefix+'/tasks/assigned/group',{token:assigned});assert.equal(group.status,200);assert(!group.data.some(t=>t.id==='sibling'));
          const seen=await request(p,prefix+'/tasks/assigned/information?section=overview',{token:watcher});assert.equal(seen.status,200);
          for(const id of ['sibling','foreign-task']) assert([403,404].includes((await request(p,prefix+'/tasks/'+id+'/information?section=subtasks',{token:member})).status));
        }
      });
      await test('E02_workload_subject_policy_and_aliases',async()=>{
        for(const prefix of ['/api','/api/api']) {
          assert.equal((await request(p,prefix+'/tasks/activity',{token:member})).status,200);
          assert.equal((await request(p,prefix+'/tasks/activity?user_id='+state.fixture.users.peer,{token:member})).status,403);
          assert.equal((await request(p,prefix+'/tasks/activity?user_id='+state.fixture.users.member,{token:manager})).status,403);
          assert.equal((await request(p,prefix+'/tasks/activity?user_id='+state.fixture.users.member,{token:owner})).status,200);
          assert.equal((await request(p,prefix+'/tasks/activity?user_id='+state.fixture.users.foreign,{token:owner})).status,404);
        }
      });
      await test('E03_invalid_queries_and_identifiers_are_safe',async()=>{
        for(const prefix of ['/api','/api/api']) for(const suffix of ['/tasks/page?page=0','/tasks/page?page_size=201','/tasks/page?status=invalid','/tasks/page?cursor=invalid%7Cassigned','/tasks/page?search=%00','/tasks/page?assignee_id=%00','/tasks/page?team=%00','/tasks/page?tag=%00','/tasks/assigned/information?section=invalid','/tasks/assigned/information?section=subtasks&search=%00','/tasks/assigned/information?subtask_id=%00','/tasks/'+('x'.repeat(37))+'/information','/tasks/%00/information','/tasks/activity?user_id=%00']) {
          const r=await request(p,prefix+suffix,{token:owner});assert([400,404,422].includes(r.status),'Safe invalid request status for '+suffix);
        }
      });
      await test('E04_task_endpoints_require_real_active_sessions',async()=>{
        for(const endpoint of ['/tasks/page','/tasks/assigned/information?section=overview','/tasks/activity']) assert.equal((await request(p,'/api'+endpoint)).status,401);
        const fresh=await login(p,'life');
        assert.equal((await request(p,'/api/auth/logout',{token:fresh,method:'POST',body:{}})).status,204);
        for(const endpoint of ['/tasks/page','/tasks/assigned/information?section=overview','/tasks/activity']) assert.equal((await request(p,'/api'+endpoint,{token:fresh})).status,401);
      });
      await test('E05_foreign_ticket_attachment_parent_authorization',async()=>{
        const id=state.fixture.foreign_ticket;
        assert.equal((await request(p,'/api/api/tickets/'+id+'/attachments',{token:owner})).status,404);
        assert.equal((await request(p,'/api/api/tickets/'+id+'/attachments/presign',{token:owner,method:'POST',body:{fileName:'fixture.txt',contentType:'text/plain',sizeBytes:8}})).status,404);
      });
    }
  } finally {
    await ctx.close();await browser.close();
    const record={run:state.run,mode:diagnostic?'diagnostic':'final',results,observations,auth:'Real issued backend credentials; no auth mocks',storage:'Local upload real; external object-store bytes not executed'};
    fs.writeFileSync(path.join(state.evidence,'phase2a1-browser-'+(diagnostic?'before':'final')+'.json'),JSON.stringify(record,null,2));
    const fail=results.filter(x=>x.status==='FAIL').length;console.log('RESULT '+JSON.stringify({pass:results.filter(x=>x.status==='PASS').length,diagnostic:results.filter(x=>x.status==='DIAGNOSTIC').length,fail}));if(fail||results.length!==(diagnostic?7:14))process.exitCode=1;
  }
})().catch(e=>{console.error(safe(e.message));process.exitCode=1});
