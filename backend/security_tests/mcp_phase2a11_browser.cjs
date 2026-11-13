/* Real Chromium + real backend password login; synthetic media only. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.ZEA_PLAYWRIGHT_MODULE);
const state = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(state.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(execFileSync('docker', ['inspect', '--format', '{{index .Config.Labels "zea.phase15"}}', state.backend],
  {encoding:'utf8',windowsHide:true}).trim(), state.run);
const results=[], observations=[];
const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAI0lEQVR4nGPUjW5iIAUwkaSaYVQDcYCJSHVwMKqBGEByKAEAYHQBKidPM/kAAAAASUVORK5CYII=';
const safe=e=>String(e).split(state.password).join('[REDACTED]').replace(/\beyJ[\w-]+\.[\w-]+\.[\w-]+/g,'[REDACTED_TOKEN]');
async function request(p,url,{token='',method='GET',body}={}) {
  assert(url.startsWith('/')&&!url.startsWith('//'));
  return p.evaluate(async({url,token,method,body})=>{
    const r=await fetch(url,{method,headers:{...(token?{Authorization:'Bearer '+token}:{}),'Content-Type':'application/json'},
      body:body===undefined?undefined:JSON.stringify(body)});
    const type=r.headers.get('content-type');let data=null;
    if(type?.includes('application/json')){const raw=await r.text();if(raw)data=JSON.parse(raw);}else await r.arrayBuffer();
    return {status:r.status,data,cache:r.headers.get('cache-control'),type,location:r.headers.get('location')};
  },{url,token,method,body});
}
async function login(p,email){const r=await request(p,'/api/auth/login',{method:'POST',body:{email,password:state.password}});
  assert.equal(r.status,200,'real password login');return r.data.token.access_token;}
async function test(name,run,status='PASS'){try{await run();results.push({name,status});console.log(status+' '+name)}
  catch(e){results.push({name,status:'FAIL',reason:safe(e.message).slice(0,300)});console.log('FAIL '+name+': '+safe(e.message).slice(0,180));}}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZEA_CHROMIUM_EXE,args:['--disable-background-networking','--no-first-run']});
 const ctx=await browser.newContext({serviceWorkers:'block'});
 await ctx.route('**/*',r=>new URL(r.request().url()).origin===state.origin?r.continue():r.abort());
 const p=await ctx.newPage();await p.goto(state.origin+'/runtime-config.js');
 try {
  const owner=await login(p,'owner@phase15.example.com'), foreign=await login(p,'foreign@phase15.example.com');
  const email='phase2a11-'+state.run+'-'+Date.now()+'@phase15.example.com';
  const made=await request(p,'/api/users',{token:owner,method:'POST',body:{name:'Synthetic media reviewer',email,
    password:state.password,role:'manager',status:'ACTIVE',department_id:null}});
  assert.equal(made.status,201);const user=made.data;let actor=await login(p,email),avatar,legacy;
  await test('P01_private_avatar_real_creation_and_read_no_store',async()=>{
    const r=await request(p,'/api/avatars',{token:owner,method:'POST',body:{name:'Phase2A11 synthetic',storage_type:'data_url',data_url:png}});
    assert.equal(r.status,201);avatar=r.data.id;
    const read=await request(p,'/api/avatars/'+avatar+'/image',{token:owner});assert.equal(read.status,200);
    assert.equal(read.cache,'no-store');assert.equal(read.location,null);
  });
  await test('P02_private_avatar_anonymous_foreign_and_missing_denied',async()=>{
    assert(avatar);const url='/api/avatars/'+avatar+'/image';
    assert.equal((await request(p,url)).status,401);
    const other=await request(p,url,{token:foreign}), missing=await request(p,'/api/avatars/absent/image',{token:foreign});
    assert.equal(other.status,404);assert.deepEqual(other.data,missing.data);
  });
  await test('P03_tenant_portrait_visibility_preserved',async()=>{
    assert(avatar);assert.equal((await request(p,'/api/avatars/'+avatar+'/image',{token:actor})).status,200);
  });
  await test('P04_packaged_public_asset_and_legacy_portrait_block',async()=>{
    assert.equal((await request(p,'/api/assets/avatars/library/default-avatar-01.svg')).status,200);
    assert.equal((await request(p,'/api/assets/avatars/custom/phase2a11.svg')).status,404);
    assert.equal((await request(p,'/api/assets/avatars/library')).status,404);
    assert.equal((await request(p,'/api/uploads/%2e%2e%2fprivate-avatars/absent.webp')).status,404);
  });
  await test('P05_legacy_media_metadata_role_and_tenant_checks',async()=>{
    const r=await p.evaluate(async({token,png})=>{const b=await (await fetch(png)).blob();const f=new FormData();
      f.append('file',b,'synthetic.png');const r=await fetch('/api/media/upload',{method:'POST',headers:{Authorization:'Bearer '+token},body:f});return {status:r.status,data:await r.json()};},{token:owner,png});
    assert.equal(r.status,201);legacy=r.data;
    assert.equal((await request(p,'/api/media/'+legacy.id,{token:actor})).status,200);
    assert.equal((await request(p,'/api/media/'+legacy.id,{token:foreign})).status,404);
    assert.equal((await request(p,'/api/media/'+legacy.id)).status,401);
  });
  await test('P06_ticket_path_rejection_through_real_proxy',async()=>{
    const prefix='tenant/'+state.fixture.tenant+'/tickets/'+state.fixture.ticket+'/';
    for(const tail of ['../other/object','x/y.txt','x\\..\\y','%2e%2e%2fforeign','a\u0000.txt']){
      const r=await request(p,'/api/api/tickets/'+state.fixture.ticket+'/attachments/confirm',
        {token:owner,method:'POST',body:{fileKey:prefix+tail}});assert.equal(r.status,400);
      assert.equal(r.cache,'no-store');assert.equal(r.location,null);
    }
    assert.equal((await request(p,'/api/api/tickets/not-a-uuid/attachments',{token:owner})).status,422);
  });
  await test('P07_current_ticket_membership_controls_attachment_admission',async()=>{
    const followerEmail=email.replace('@','-follower@');
    const created=await request(p,'/api/users',{token:owner,method:'POST',body:{name:'Synthetic attachment follower',
      email:followerEmail,password:state.password,role:'user',status:'ACTIVE'}});
    assert.equal(created.status,201);const follower=await login(p,followerEmail);
    const control=action=>execFileSync('docker',['exec',state.backend,'python','-B','/tests/mcp_phase2a11_fixture.py',JSON.stringify({action,user:created.data.id})],{windowsHide:true});
    // A Manager without a department has no blanket admission.
    const url='/api/api/tickets/'+state.fixture.ticket+'/attachments';
    assert.equal((await request(p,url,{token:actor})).status,403);
    assert.equal((await request(p,url,{token:follower})).status,403);
    control('grant');assert.equal((await request(p,url,{token:follower})).status,200);
    control('remove');assert.equal((await request(p,url,{token:follower})).status,403);
    assert.equal((await request(p,url,{token:foreign})).status,404);
    assert.equal((await request(p,url)).status,401);
    assert.equal((await request(p,url+'/presign',{token:follower,method:'POST',body:{fileName:'synthetic.txt',contentType:'text/plain',sizeBytes:8}})).status,403);
  });
  await test('P08_role_change_revokes_old_authority_and_rechecks_media',async()=>{
    assert(legacy);assert.equal((await request(p,'/api/users/'+user.id,{token:owner,method:'PATCH',body:{role:'user'}})).status,200);
    assert.equal((await request(p,'/api/media/'+legacy.id,{token:actor})).status,401);
    actor=await login(p,email);assert.equal((await request(p,'/api/media/'+legacy.id,{token:actor})).status,403);
    assert.equal((await request(p,'/api/media/absent',{token:actor})).status,404);
  });
  await test('P09_deactivation_denies_private_images_and_signing',async()=>{
    assert.equal((await request(p,'/api/users/'+user.id,{token:owner,method:'PATCH',body:{status:'DEACTIVATED'}})).status,200);
    assert.equal((await request(p,'/api/avatars/'+avatar+'/image',{token:actor})).status,401);
    assert.equal((await request(p,'/api/media/presign',{token:actor,method:'POST',body:{purpose:'media',tab:'images',file_name:'synthetic.png',content_type:'image/png',size_bytes:8}})).status,401);
  });
  await test('P10_deleted_avatar_cannot_be_read',async()=>{
    assert.equal((await request(p,'/api/avatars/'+avatar,{token:owner,method:'DELETE'})).status,204);
    assert.equal((await request(p,'/api/avatars/'+avatar+'/image',{token:owner})).status,404);
  });
  await test('D01_legacy_soft_delete_does_not_revoke_public_bytes',async()=>{
    assert(legacy);const url='/api'+legacy.public_url;
    assert.equal((await request(p,url)).status,200);
    assert.equal((await request(p,'/api/media/'+legacy.id,{token:owner,method:'DELETE'})).status,204);
    assert.equal((await request(p,'/api/media/'+legacy.id,{token:owner})).status,404);
    assert.equal((await request(p,url)).status,200);
    observations.push({name:'legacy_url_after_soft_delete',anonymous_status:200,visibility:'UNKNOWN; requires decision'});
  },'DIAGNOSTIC');
 } finally {
  await browser.close();fs.writeFileSync(path.join(state.evidence,'phase2a11-browser.json'),JSON.stringify({run:state.run,
    authentication:'Real browser HTTP password authentication and backend-issued tokens; no auth mocks',
    object_storage:'NOT RUN; local filesystem only',results,observations},null,2));
 }
 if(results.length!==11||results.some(r=>r.status==='FAIL'))process.exitCode=1;
})().catch(e=>{console.error(safe(e.message));process.exitCode=1});
