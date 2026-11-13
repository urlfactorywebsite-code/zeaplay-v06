/* Independent stored-document execution audit. Owned stack, real UI login. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const {chromium}=require(process.env.ZEA_PLAYWRIGHT_MODULE);
const s=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.match(s.origin,/^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(execFileSync('docker',['inspect','--format','{{index .Config.Labels "zea.phase15"}}',s.backend],{encoding:'utf8',windowsHide:true}).trim(),s.run);
const before=process.argv.includes('--expect-exposure'),results=[],observations=[];
const suffix=before?'before':'after';
const safe=v=>String(v).split(s.password).join('[REDACTED]').replace(/\beyJ[\w-]+\.[\w-]+\.[\w-]+/g,'[REDACTED_TOKEN]');
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="blue"/><script>localStorage.setItem("media-audit-probe",localStorage.getItem("media-audit-sentinel")||"unreadable")</script></svg>';
async function login(p){await p.goto(s.origin+'/#/login');await p.locator('#email-address').fill('owner@phase15.example.com');
 await p.locator('#password').fill(s.password);await p.locator('#password').press('Enter');
 await p.waitForURL(u=>u.hash&&!['#','#/'].includes(u.hash)&&!u.hash.includes('/login'));
 await p.waitForFunction(()=>!!localStorage.getItem('vee_access_token'));
}
async function test(name,run){try{await run();results.push({name,status:before?'EXPECTED_REPRODUCTION':'PASS'});console.log(results.at(-1).status+' '+name)}
 catch(e){results.push({name,status:'FAIL',reason:safe(e.message).slice(0,250)});console.log('FAIL '+name+': '+safe(e.message).slice(0,180));}}
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:process.env.ZEA_CHROMIUM_EXE,args:['--disable-background-networking','--no-first-run']});
 const c=await b.newContext({serviceWorkers:'block'});await c.route('**/*',r=>new URL(r.request().url()).origin===s.origin?r.continue():r.abort());
 const p=await c.newPage();
 try{
  await login(p);
  const uploads=await p.evaluate(async({svg,suffix,password})=>{
   const token=localStorage.getItem('vee_access_token');
   const signed=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'member@phase15.example.com',password})});
   const member=await signed.json();const uploadToken=member.token?.access_token;
   const file=new Blob([svg],{type:'image/svg+xml'}),a=new FormData();a.append('file',file,'synthetic-'+suffix+'.svg');
   const one=await fetch('/api/media/upload',{method:'POST',headers:{Authorization:'Bearer '+uploadToken},body:a});
   const oneData=await one.json();
   const t=new FormData();t.append('payload',JSON.stringify({title:'Synthetic media audit '+suffix}));t.append('featured_image',file,'synthetic.svg');
   const two=await fetch('/api/tasks/task-templates',{method:'POST',headers:{Authorization:'Bearer '+token},body:t});
   const twoData=await two.json();
   return {legacy:{status:one.status,url:oneData.public_url,storage_path_exposed:typeof oneData.storage_path==='string'},template:{status:two.status,url:twoData.featured_image}};
  },{svg,suffix,password:s.password});
  assert.equal(uploads.legacy.status,201,'Real multipart MediaItem creation');assert.equal(uploads.template.status,201,'Real multipart featured image creation');
  observations.push({finding:'Authorized legacy upload response exposes storage_path; literal no-key criterion is unmet',storage_path_exposed:uploads.legacy.storage_path_exposed});
  for(const [name,upload]of Object.entries(uploads)){
   assert(upload.url);const url=s.origin+'/api/'+upload.url.replace(/^\//,'');
   await test(name+'_uploaded_svg_cannot_execute_in_application_origin',async()=>{
    await p.goto(s.origin+'/runtime-config.js');
    await p.evaluate(run=>{localStorage.setItem('media-audit-sentinel',run);localStorage.removeItem('media-audit-probe');},s.run);
    const r=await p.goto(url);assert.equal(r.status(),200);assert.match(r.headers()['content-type'],/image\/svg\+xml/);
    await p.goto(s.origin+'/runtime-config.js');
    const marker=await p.evaluate(()=>localStorage.getItem('media-audit-probe'));
    if(before)assert.equal(marker,s.run,'Reproduce same-origin script reading synthetic storage sentinel');
    else {assert.equal(marker,null,'Uploaded SVG must not execute/read application storage');const csp=r.headers()['content-security-policy']||'';
      assert.match(csp,/(?:^|;)\s*sandbox\s+allow-downloads\s*(?:;|$)/);assert(!/allow-scripts|allow-same-origin/.test(csp));assert.equal(r.headers()['x-content-type-options'],'nosniff');}
   });
   if(!before)await test(name+'_public_image_render_and_fetch_remain_usable',async()=>{
    const loaded=await p.evaluate(url=>new Promise(resolve=>{const image=document.createElement('img');image.onload=()=>resolve(image.naturalWidth===16);image.onerror=()=>resolve(false);image.src=url;document.body.append(image);}),url);
    assert.equal(loaded,true,'Legitimate inline SVG image renders');
    const fetched=await p.evaluate(async url=>{const r=await fetch(url);return {status:r.status,size:(await r.arrayBuffer()).byteLength,cache:r.headers.get('cache-control')};},url);
    assert.equal(fetched.status,200);assert(fetched.size>0);assert.equal(fetched.cache,'no-store');
    const pending=p.waitForEvent('download',{timeout:10000});
    await p.evaluate(url=>{const a=document.createElement('a');a.href=url;a.download='synthetic.svg';document.body.append(a);a.click();a.remove();},url);
    const download=await pending;assert.match(download.suggestedFilename(),/\.svg$/);assert.equal(await download.failure(),null,'Native browser download completes');
   });
  }
  if(!before){
   await p.goto(s.origin+'/runtime-config.js');
   const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAI0lEQVR4nGPUjW5iIAUwkaSaYVQDcYCJSHVwMKqBGEByKAEAYHQBKidPM/kAAAAASUVORK5CYII=';
   const identity=await p.evaluate(async({png,run,password})=>{
    const owner=localStorage.getItem('vee_access_token');
    const response=await fetch('/api/avatars',{method:'POST',headers:{Authorization:'Bearer '+owner,'Content-Type':'application/json'},
      body:JSON.stringify({name:'Independent probe '+run,storage_type:'data_url',data_url:png})});
    const avatar=await response.json();
    const login=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'foreign@phase15.example.com',password})});
    const data=await login.json();return {status:response.status,id:avatar.id,owner,foreign:data.token?.access_token};
   },{png,run:s.run,password:s.password});assert.equal(identity.status,201);assert(identity.foreign);
   const privatePath=JSON.parse(execFileSync('docker',['exec',s.backend,'python','-B','-c',
    "import json,sys;sys.path.insert(0,'/tests');from pathlib import Path;import mcp_phase1_5_backend as f;f.verify();from sqlalchemy.orm import Session;from sqlalchemy import select;from app import models as m;db=Session(f.engine);a=db.scalar(select(m.AvatarAsset).where(m.AvatarAsset.id==sys.argv[1],m.AvatarAsset.name=='Independent probe '+f.run_id));assert a and a.created_by_id==f.ident('owner') and a.file_path.startswith('private-avatars/');assert (Path('/scratch/media')/a.file_path).is_file();print(json.dumps(a.file_path))",identity.id],
    {encoding:'utf8',windowsHide:true}).trim().split('\n').at(-1));
   await test('private_avatar_both_api_aliases_require_current_tenant_authority',async()=>{
    const statuses=await p.evaluate(async identity=>{
     const out=[];for(const prefix of ['/api','/api/api'])for(const token of [identity.owner,'',identity.foreign]){
      const r=await fetch(prefix+'/avatars/'+identity.id+'/image',{headers:token?{Authorization:'Bearer '+token}:{}});out.push(r.status);
     }return out;
    },identity);assert.deepEqual(statuses,[200,401,404,200,401,404]);
   });
   await test('static_aliases_deny_existing_private_avatar_and_custom_portrait',async()=>{
    const statuses=await p.evaluate(async privatePath=>{
     const urls=['/api/uploads/%2e%2e%2f'+privatePath,'/api/uploads/../'+privatePath,
       '/api/api/uploads/%2e%2e%2f'+privatePath,'/api/assets/avatars/custom/phase2a11.svg',
       '/api/assets/%61vatars/custom/phase2a11.svg','/api/assets/avatars%2fcustom%2fphase2a11.svg',
       '/api/assets/avatars%5ccustom%5cphase2a11.svg'];
     return Promise.all(urls.map(async url=>(await fetch(url)).status));
    },privatePath);assert(statuses.every(v=>v===404),'Existing private bytes must remain unavailable through static aliases');
   });
  }
 }finally{await b.close();fs.writeFileSync(path.join(s.evidence,'independent-uploaded-document-'+suffix+'.json'),JSON.stringify({run:s.run,
    authentication:'Real UI password login; backend-issued credentials; only synthetic storage sentinel read by probe',
    mode:before?'Expected defect reproduction, not a security PASS':'Current code',results,observations},null,2));}
 if(results.length!==(before?2:6)||results.some(x=>x.status==='FAIL'))process.exitCode=1;
})().catch(e=>{console.error(safe(e.message));process.exitCode=1});
