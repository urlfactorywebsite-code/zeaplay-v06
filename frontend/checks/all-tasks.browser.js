// Real application/components, intercepted APIs and a controlled task socket.
async function verifyAllTasks(page) {
  await page.setViewportSize({width:1440,height:1000});
  const origin = 'http://127.0.0.1:6322';
  const registry = await (await page.request.get(origin + '/checks/navigation-registry.fixture.json')).json();
  const results = [], requests = [], errors = [], writes = [], externalWrites = [];
  let role = 'owner', disabled = '', hidden = '', failWrite = false;
  const owner = {id:'task-owner', name:'Task Reviewer', email:'review@example.test', role:'owner', status:'ACTIVE', timezone:'Asia/Kolkata',
    points:0,skills:[],projects:[],tasks_created:0,tasks_completed:0,clarity_scores:[],claimed_reward_ids:[],unlocked_achievement_ids:[],created_at:'2026-10-01T00:00:00',updated_at:'2026-10-29T00:00:00'};
  const date = new Date(); const day = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  let tasks = [{id:'task-one',title:'Centralized task fixture',description:'Existing task workflow',status:'TODO',priority:'HIGH',team:'Engineering',assigned_to_ids:[owner.id],assigned_to_id:owner.id,created_by_id:owner.id,
    created_at: day+'T08:00:00', updated_at:day+'T08:00:00',due_at:day+'T10:00:00',dependencies:[{id:'dependency',title:'Existing dependency'}],subtasks:[{id:'sub-one',title:'Fixture subtask',completed:false}],attachments:[],tags:[],estimated_hours:2,recurrence_rule:'NONE',follower_ids:[],clarity_rating:null}];
  const statuses=['WAITING_FOR_REQUIREMENT','TODO','IN_PROGRESS','BLOCKED','IN_REVIEW','ON_HOLD','DONE','FAILED','GRAVEYARD'];
  const titles=['Battle Plan','Case Filed','In Progress','Boss Encounter','Tactical Shift','On Hold','Conquered','Fallen','Graveyard'];
  const assert = (value,message) => { if (!value) throw new Error(message); };
  const check = async (name,run) => { try { await run(); results.push({name,status:'PASS'}); } catch(error) { results.push({name,status:'FAIL',error:String(error).slice(0,700),url:page.url(),body:(await page.locator('body').innerText()).slice(-1800)}); } };
  page.setDefaultTimeout(7000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('dialog', dialog => dialog.accept());
  await page.addInitScript(() => {
    localStorage.setItem('vee_access_token','fixture-token'); localStorage.setItem('zenith-task-theme','dark');
    Object.keys(localStorage).filter(key=>key.startsWith('zea-play-cache:')).forEach(key=>localStorage.removeItem(key));
    window.__taskSockets=[];
    class Socket extends EventTarget {
      static OPEN=1; static CONNECTING=0; static CLOSED=3; readyState=1;
      constructor(url) { super(); this.url=String(url); if(this.url.includes('/ws/tasks'))window.__taskSockets.push(this); setTimeout(()=>this.dispatchEvent(new Event('open')),0); }
      send() {} close() { this.readyState=3; this.dispatchEvent(new Event('close')); }
    }
    window.WebSocket=Socket;
    window.__taskEvent = payload => window.__taskSockets.filter(socket=>socket.readyState===1).forEach(socket=>socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(payload)})));
  });
  function policy() {
    const access = item => !item.permittedRoles.includes(role) ? 'forbidden' : item.id===disabled ? 'disabled' : item.parentId ? access(registry.find(parent=>parent.id===item.parentId)) : 'allowed';
    return {tenantId:'tasks-fixture',version:0,updatedBy:null,updatedAt:null,roles:['user','manager','admin','owner'],canManage:['admin','owner'].includes(role),canChangeAccess:role==='owner',pages:registry.map(item=>({...item,enabled:item.id!==disabled,hidden:item.id===hidden,allowedRoles:item.permittedRoles,access:access(item),visible:access(item)==='allowed'&&item.id!==hidden}))};
  }
  await page.route('**/*', async route => {
    const request=route.request(), url=new URL(request.url()), method=request.method();
    if(url.pathname.startsWith('/api/')) {
      const path=url.pathname.slice(4); requests.push({path,method,search:url.search});
      if(path==='/navigation') return route.fulfill({json:policy()});
      if(path==='/auth/me') return route.fulfill({json:{...owner,role}});
      if(path==='/users') return route.fulfill({json:[{...owner,role}]});
      if(path==='/departments') return route.fulfill({json:[{id:'engineering',name:'Engineering'}]});
      if(path==='/config/release-notes') return route.fulfill({json:{versionLabel:'Fixture',updates:[]}});
      if(path==='/tasks/page') {
        let filtered=tasks;
        if(url.searchParams.get('status'))filtered=filtered.filter(task=>task.status===url.searchParams.get('status'));
        if(url.searchParams.get('priority'))filtered=filtered.filter(task=>task.priority===url.searchParams.get('priority'));
        if(url.searchParams.get('search'))filtered=filtered.filter(task=>task.title.toLowerCase().includes(url.searchParams.get('search').toLowerCase()));
        const pageNumber=Number(url.searchParams.get('page')||1),pageSize=Number(url.searchParams.get('page_size')||50);
        return route.fulfill({json:{items:filtered.slice((pageNumber-1)*pageSize,pageNumber*pageSize),page:pageNumber,page_size:pageSize,total:filtered.length,total_pages:Math.max(1,Math.ceil(filtered.length/pageSize)),status_counts:{TODO:filtered.length}}});
      }
      if(path==='/tasks/kanban') return route.fulfill({json:{columns:statuses.map((status,index)=>({status,title:titles[index],order:index,count:tasks.filter(task=>task.status===status).length,items:tasks.filter(task=>task.status===status).slice((Number(url.searchParams.get('page')||1)-1)*Number(url.searchParams.get('page_size')||20),Number(url.searchParams.get('page')||1)*Number(url.searchParams.get('page_size')||20))}))}});
      if(path==='/tasks/calendar/summary') return route.fulfill({json:{start_date:url.searchParams.get('start_date'),end_date:url.searchParams.get('end_date'),days:[{date:day,total:tasks.length,completed:0,overdue:0,dueSoon:0,low:0,medium:0,high:tasks.length,urgent:0}]}});
      if(path==='/tasks/calendar/tasks') return route.fulfill({json:tasks});
      if(path==='/tasks' && method==='GET') return route.fulfill({json:tasks});
      if(path==='/tasks' && method==='POST') {
        const body=request.postDataJSON();writes.push({path,method,body});
        const task={...tasks[0],...body,id:body.title==='Scheduled through calendar'?'calendar-created-task':'created-task',created_by_id:owner.id};tasks=[...tasks,task];return route.fulfill({json:[task]});
      }
      if(path==='/tasks/task-one' && method==='PATCH') {
        const body=request.postDataJSON(); writes.push({path,method,body});
        if(failWrite){failWrite=false;return route.fulfill({status:403,json:{detail:'Fixture transition denied'}});}
        tasks=tasks.map(task=>task.id==='task-one'?{...task,...body}:task);return route.fulfill({json:tasks[0]});
      }
      if(path.startsWith('/tasks/12345678-1234-1234-1234-123456789012'))return route.fulfill({json:path.endsWith('/group')?[{...tasks[0],id:'12345678-1234-1234-1234-123456789012'}]:{...tasks[0],id:'12345678-1234-1234-1234-123456789012'}});
      if(path==='/tasks/task-one') return route.fulfill({json:tasks[0]});
      if(path.startsWith('/tasks/task-one/group')) return route.fulfill({json:[tasks[0]]});
      if(path.startsWith('/tasks/created-task')) return route.fulfill({json:tasks.find(task=>task.id==='created-task')});
      if(path==='/avatars/policy')return route.fulfill({json:{maxBytes:5242880,contentTypes:['image/jpeg','image/png','image/webp']}});
      return route.fulfill({json:[]});
    }
    if(url.origin!==origin&&!['GET','HEAD'].includes(method))externalWrites.push({url:url.origin+url.pathname,method});
    if(url.origin===origin||['cdn.tailwindcss.com','cdn.jsdelivr.net'].includes(url.hostname))return route.continue();
    return route.fulfill({body:'',contentType:'text/plain'});
  });
  const visit=path=>page.goto(origin+'/#'+path,{waitUntil:'networkidle'});
  const tab=name=>page.getByRole('tab',{name,exact:true});
  const panel=()=>page.locator('[role=tabpanel]:visible');
  await visit('/tasks');
  await check('One All Tasks sidebar entry and four horizontal tabs',async()=>{
    await page.getByRole('heading',{name:'All Tasks',exact:true}).waitFor();
    assert(await page.getByRole('tablist',{name:'Task views'}).getByRole('tab').count()===4,'Missing four tabs');
    assert(await page.getByRole('tablist',{name:'Task views'}).evaluate(element=>[...element.querySelectorAll('[role=tab]')].every(tab=>document.getElementById(tab.getAttribute('aria-controls')))),'A tab controls a missing panel');
    const sidebar=page.locator('nav').first();
    assert(await sidebar.getByRole('link',{name:'All Tasks',exact:true}).count()===1,'Missing parent sidebar link');
    for(const name of ['Kanban Board','Gantt Chart','Calendar'])assert(await sidebar.getByRole('link',{name,exact:true}).count()===0,'Standalone task view remains');
    assert(!requests.some(request=>request.path==='/tasks/kanban'||request.path.startsWith('/tasks/calendar/')),'Unvisited views fetched data');
  });
  await check('List keeps task controls and existing details',async()=>{
    await panel().getByText('Centralized task fixture',{exact:true}).first().waitFor();
    assert(await panel().getByRole('button',{name:'+ Create Task',exact:true}).isVisible(),'Create task missing');
    await panel().getByText('Centralized task fixture',{exact:true}).first().click();
    await page.getByText('Fixture subtask',{exact:true}).first().waitFor();
    assert(await page.evaluate(()=>!Object.keys(localStorage).some(key=>key.startsWith('zea-play-cache:')&&key.includes('comments:'))),'Task comments leaked into a persisted shared cache');
    await page.locator('select:visible').filter({has:page.locator('option[value="IN_REVIEW"]')}).selectOption('IN_REVIEW');
    await Promise.all([page.waitForResponse(response=>response.url().includes('/api/tasks/task-one')&&response.request().method()==='PATCH'),page.getByRole('button',{name:'Update Task',exact:true}).click()]);
    assert(tasks[0].status==='IN_REVIEW','Existing details update did not persist');
    await page.getByRole('button',{name:'Close modal',exact:true}).click();
  });
  await check('Task creation retains the existing form and POST contract',async()=>{
    await panel().getByRole('button',{name:'+ Create Task',exact:true}).click();
    await page.getByPlaceholder('Name your quest...').fill('Created through centralized tasks');
    await page.locator('input[type=date]').first().fill(day);
    await page.locator('input[type=time]').first().fill('18:00');
    await Promise.all([page.waitForResponse(response=>response.url().endsWith('/api/tasks')&&response.request().method()==='POST'),page.getByRole('button',{name:'Create quest',exact:true}).click()]);
    assert(writes.some(write=>write.method==='POST'&&write.body.title==='Created through centralized tasks'&&Array.isArray(write.body.assigned_to_ids)),'Task form did not use the backend array contract');
    await panel().getByText('Created through centralized tasks',{exact:true}).first().waitFor();
  });
  await check('Kanban is route-backed and sidebar parent stays active',async()=>{
    await tab('Kanban Board').click();
    await panel().getByText('Centralized task fixture',{exact:true}).first().waitFor();
    assert(page.url().includes('#/tasks/kanban'),'Kanban route incorrect');
    assert(await page.locator('nav').first().getByRole('link',{name:'All Tasks',exact:true}).getAttribute('aria-current')==='page','Parent not highlighted');
  });
  await check('Kanban uses existing status PATCH and rolls back a denied transition',async()=>{
    const transfer=await page.evaluateHandle(()=>new DataTransfer());await transfer.evaluate(data=>data.setData('taskId','task-one'));
    const target=panel().getByRole('group',{name:'In Progress tasks',exact:true});
    await Promise.all([page.waitForResponse(response=>response.url().includes('/api/tasks/task-one')&&response.request().method()==='PATCH'),target.dispatchEvent('drop',{dataTransfer:transfer})]);
    assert(tasks[0].status==='IN_PROGRESS','Status PATCH missing');
    failWrite=true;
    const denied=panel().getByRole('group',{name:'Conquered tasks',exact:true});
    await Promise.all([page.waitForResponse(response=>response.url().includes('/api/tasks/task-one')&&response.status()===403),denied.dispatchEvent('drop',{dataTransfer:transfer})]);
    assert(tasks[0].status==='IN_PROGRESS','Denied transition changed server fixture');
    await panel().getByRole('group',{name:'In Progress tasks',exact:true}).getByText('Centralized task fixture',{exact:true}).waitFor();
  });
  await check('Gantt reuses timeline and retains range controls',async()=>{
    await tab('Gantt Chart').click();await panel().getByRole('heading',{name:'Gantt Raid Map'}).waitFor();
    await panel().getByRole('button',{name:'All Time',exact:true}).click();
    await panel().locator('[title*="Depends on: Existing dependency"]').first().waitFor();
    await panel().getByText('Centralized task fixture',{exact:true}).first().waitFor();
    await panel().getByRole('button',{name:'Unassigned',exact:true}).click();
    assert(page.url().includes('ganttUnassigned=1')&&!page.url().includes('assignee=__UNASSIGNED__'),'Gantt-only filter leaked into shared employee filter');
    await panel().getByText('Created through centralized tasks',{exact:true}).first().waitFor();
    await tab('Kanban Board').click();
    await panel().getByText('Centralized task fixture',{exact:true}).first().waitFor();
    await tab('Gantt Chart').click();await panel().getByRole('button',{name:'All Champs',exact:true}).click();
  });
  await check('Calendar occupies the tab panel and opens existing day/task details',async()=>{
    await tab('Calendar').click();await panel().getByRole('heading',{name:'Calendar',exact:true}).waitFor();
    await panel().getByText('Calendar timezone: Asia/Kolkata',{exact:true}).waitFor();
    await panel().getByRole('button',{name:'Day',exact:true}).click();
    await panel().getByText('Centralized task fixture',{exact:true}).first().waitFor();
    await panel().getByText('Centralized task fixture',{exact:true}).first().click();
    await page.getByText('Fixture subtask',{exact:true}).first().waitFor();await page.getByRole('button',{name:'Close modal',exact:true}).click();
    await panel().getByRole('button',{name:'Month',exact:true}).click();
    await panel().locator('.calendar-day-card[data-today="true"]').click();
    await page.getByRole('button',{name:'Open full task',exact:true}).click();
    await page.getByText('Fixture subtask',{exact:true}).first().waitFor();
    assert(await page.getByRole('button',{name:'Close day details',exact:true}).count()===0,'Day drawer covers task details');
    await page.getByRole('button',{name:'Close modal',exact:true}).click();
  });
  await check('Tab keyboard navigation supports arrows, Home, End and Space',async()=>{
    await tab('Calendar').focus();await page.keyboard.press('Home');
    assert(await tab('All Tasks').evaluate(element=>element===document.activeElement),'Home did not focus first tab');
    await page.keyboard.press('ArrowRight');
    assert(await tab('Kanban Board').evaluate(element=>element===document.activeElement),'ArrowRight did not move focus');
    await page.keyboard.press('Space');await page.waitForURL('**/#/tasks/kanban');
    await page.keyboard.press('End');await page.keyboard.press('Space');await page.waitForURL('**/#/tasks/calendar');
  });
  await check('Browser refresh, back/forward and legacy routes preserve selected tab',async()=>{
    await page.reload({waitUntil:'networkidle'});await tab('Calendar').waitFor();assert(await tab('Calendar').getAttribute('aria-selected')==='true','Refresh lost tab');
    await tab('All Tasks').click();await tab('Kanban Board').click();await page.goBack();assert(await tab('All Tasks').getAttribute('aria-selected')==='true','Back wrong');await page.goForward();assert(await tab('Kanban Board').getAttribute('aria-selected')==='true','Forward wrong');
    for(const [from,to] of [['/kanban','kanban'],['/gantt','gantt'],['/calendar','calendar']]){await visit(from+'?priority=HIGH#anchor');await page.waitForURL('**/#/tasks/'+to+'?priority=HIGH#anchor');assert(page.url().includes('/tasks/'+to+'?priority=HIGH#anchor'),'Legacy redirect dropped state');}
  });
  await check('Filters, local view state and retained panel nodes survive switching',async()=>{
    await visit('/tasks?priority=HIGH&assignee=task-owner');
    await panel().getByPlaceholder('Search Tasks').fill('Centralized');
    await panel().getByText('Centralized task fixture',{exact:true}).first().waitFor();
    await panel().evaluate(el=>el.dataset.retained='yes');
    await tab('Kanban Board').click();assert(page.url().includes('priority=HIGH')&&page.url().includes('assignee=task-owner')&&page.url().includes('search=Centralized'),'Shared filters lost');
    await tab('All Tasks').click();await page.locator('#tasks-panel-list').waitFor({state:'visible'});assert(await page.locator('#tasks-panel-list').getAttribute('data-retained')==='yes','List was remounted');
    assert(await panel().getByPlaceholder('Search Tasks').inputValue()==='Centralized','Search reset');
  });
  await check('One task socket survives switches and updates all visited views',async()=>{
    const before=await page.evaluate(()=>window.__taskSockets.length);
    assert(await page.evaluate(()=>window.__taskSockets.filter(socket=>socket.readyState===1).length)===1,'Expected exactly one live task socket');
    await tab('Kanban Board').click();await tab('Calendar').click();await tab('All Tasks').click();
    assert(await page.evaluate(()=>window.__taskSockets.length)===before,'Tab switches reconnected task socket');
    tasks=tasks.map(task=>({...task,title:'Realtime updated fixture'}));
    await page.evaluate(()=>window.__taskEvent({type:'task.updated'}));
    await panel().getByPlaceholder('Search Tasks').fill('');
    await panel().getByText('Realtime updated fixture',{exact:true}).first().waitFor();
    await tab('Kanban Board').click();await panel().getByText('Realtime updated fixture',{exact:true}).first().waitFor();
    await tab('Gantt Chart').click();await panel().getByText('Realtime updated fixture',{exact:true}).first().waitFor();
    await tab('Calendar').click();await panel().getByRole('button',{name:'Day',exact:true}).click();await panel().getByText('Realtime updated fixture',{exact:true}).first().waitFor();
  });
  await check('User Gantt ceiling and disabled child direct URLs are enforced',async()=>{
    role='user';await visit('/tasks/gantt');await page.waitForURL('**/settings/profile');assert(await page.getByRole('tab',{name:'Gantt Chart',exact:true}).count()===0,'User reached Gantt');
    role='owner';disabled='kanban';const start=requests.length;await visit('/tasks/kanban');await page.waitForURL('**/settings/profile');assert(!requests.slice(start).some(request=>request.path==='/tasks/kanban'),'Denied child fetched board');disabled='';
  });
  await check('Hidden-only tab keeps established direct-access semantics',async()=>{
    hidden='calendar';await visit('/tasks/calendar');await panel().getByRole('heading',{name:'Calendar',exact:true}).waitFor();assert(await tab('Calendar').count()===0,'Hidden tab visible');assert(await tab('All Tasks').getAttribute('tabindex')==='0','Hidden active tab removed keyboard entry to other tabs');hidden='';
  });
  await check('Sidebar Management groups all four task tabs separately',async()=>{
    await visit('/settings/sidebar-management');await page.getByRole('button',{name:'All Tasks Tabs',exact:true}).click();
    for(const id of ['tasks.list','kanban','gantt','calendar'])await page.locator('[data-page-id="'+id+'"]').waitFor();
    assert(await page.locator('[data-page-id="tasks.list"]').getByRole('switch').isDisabled(),'Essential list tab not protected');
  });
  await check('Mobile and tablet views contain horizontal overflow inside panels',async()=>{
    for(const width of [390,768])for(const [name,path] of [['All Tasks','/tasks'],['Kanban Board','/tasks/kanban'],['Gantt Chart','/tasks/gantt'],['Calendar','/tasks/calendar']]){
      await page.setViewportSize({width,height:900});await visit(path);await tab(name).waitFor();await panel().waitFor();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+' page overflows at '+width);
      if(name==='Calendar')assert(await panel().locator('[data-calendar-filters]').evaluate(element=>[...element.children].every(child=>child.getBoundingClientRect().right<=element.getBoundingClientRect().right)), 'Calendar filter controls are clipped at '+width);
    }
    await page.setViewportSize({width:1365,height:900});
  });
  await check('Closing unchanged Task Details does not refetch the task list',async()=>{
    await visit('/tasks');await panel().getByText('Realtime updated fixture',{exact:true}).first().waitFor();
    await page.waitForLoadState('networkidle');const before=requests.filter(request=>request.path==='/tasks/page').length;
    await panel().getByText('Realtime updated fixture',{exact:true}).first().click();
    await page.getByText('Fixture subtask',{exact:true}).first().waitFor();await page.getByRole('button',{name:'Close modal',exact:true}).click();
    await page.waitForLoadState('networkidle');assert(requests.filter(request=>request.path==='/tasks/page').length===before,'Cancel refetched unchanged list');
  });
  await check('Notification UUID deep links preserve filters and open existing Task Details',async()=>{
    const id='12345678-1234-1234-1234-123456789012';
    await visit('/tasks/'+id+'?priority=HIGH#bookmark');
    await page.getByText('Fixture subtask',{exact:true}).first().waitFor();
    assert(page.url().includes('/tasks?priority=HIGH&taskId='+id+'#bookmark'),'Task detail redirect lost location');
    await page.getByRole('button',{name:'Close modal',exact:true}).click();
    await page.waitForURL('**/#/tasks?priority=HIGH#bookmark');
  });
  await check('List pagination, 100-task page size and retained page state work with the shared cache',async()=>{
    const previous=tasks;
    tasks=[...tasks,...Array.from({length:25},(_,index)=>({...tasks[0],id:'list-'+index,title:'Paged list '+index}))];
    await page.evaluate(()=>window.__taskEvent({type:'task.changed'}));
    await visit('/tasks');await panel().getByRole('combobox',{name:'Tasks per page',exact:true}).selectOption('10');
    await panel().getByText('Page 1 of 3',{exact:true}).waitFor();
    await panel().getByRole('button',{name:'Next page',exact:true}).click();await panel().getByText('Paged list 17',{exact:true}).waitFor();
    await tab('Kanban Board').click();await tab('All Tasks').click();await panel().getByText('Page 2 of 3',{exact:true}).waitFor();
    await panel().getByRole('combobox',{name:'Tasks per page',exact:true}).selectOption('100');await panel().getByText('Paged list 24',{exact:true}).waitFor();
    assert(requests.some(request=>request.path==='/tasks/page'&&new URLSearchParams(request.search).get('page_size')==='100'),'100 per page was silently capped');
    assert(!requests.some(request=>request.path==='/tasks/page'&&new URLSearchParams(request.search).get('page_size')==='100'&&new URLSearchParams(request.search).get('page')==='2'),'Page-size change fetched an unnecessary empty second page');
    const count=requests.filter(request=>request.path==='/tasks/page').length;
    await panel().getByTitle('Grid View',{exact:true}).click();await panel().getByRole('combobox',{name:'Tasks per page',exact:true}).selectOption('100');
    await panel().getByText('Paged list 24',{exact:true}).waitFor();await page.waitForLoadState('networkidle');
    assert(requests.filter(request=>request.path==='/tasks/page').length<=count+1,'Grid issued redundant requests for cached server data');
    await panel().getByTitle('List View',{exact:true}).click();
    tasks=previous;await page.evaluate(()=>window.__taskEvent({type:'task.changed'}));
  });
  await check('Renamed Kanban columns and server pagination expose later tasks',async()=>{
    const previous=tasks;titles[2]='Implementation';
    tasks=[...tasks,...Array.from({length:25},(_,index)=>({...tasks[0],id:'paged-'+index,title:'Paged task '+index,status:'IN_PROGRESS'}))];
    await page.evaluate(()=>window.__taskEvent({type:'task.changed'}));
    await visit('/tasks/kanban');
    await panel().getByRole('group',{name:'Implementation tasks',exact:true}).waitFor();
    await panel().getByRole('button',{name:'Next page',exact:true}).click();
    await panel().getByText('Paged task 24',{exact:true}).waitFor();
    assert(requests.some(request=>request.path==='/tasks/kanban'&&new URLSearchParams(request.search).get('page')==='2'),'Second server page was not requested');
    tasks=previous;titles[2]='In Progress';
  });
  await check('Calendar day creation submits profile-zone wall time as UTC',async()=>{
    const previous=tasks;
    await visit('/tasks/calendar');await panel().getByRole('button',{name:'Month',exact:true}).click();
    await panel().locator('.calendar-day-card[data-today="true"]').click();
    await page.getByRole('button',{name:'Add task',exact:true}).click();
    await page.getByPlaceholder('Name your quest...').fill('Scheduled through calendar');
    assert(await page.locator('input[type=date]').first().inputValue()===day,'Selected calendar date shifted before creation');
    await page.locator('input[type=time]').first().fill('00:00');
    await Promise.all([page.waitForResponse(response=>response.url().endsWith('/api/tasks')&&response.request().method()==='POST'),page.getByRole('button',{name:'Create quest',exact:true}).click()]);
    const write=writes.find(write=>write.method==='POST'&&write.body.title==='Scheduled through calendar');
    assert(write?.body.due_at===new Date(day+'T00:00:00+05:30').toISOString(),'Calendar wall time was not converted to UTC');
    tasks=previous;await page.evaluate(()=>window.__taskEvent({type:'task.changed'}));
  });
  await check('Calendar scheduling PATCH keeps local day and rolls back a denied date change',async()=>{
    const previous=tasks;
    await panel().getByRole('button',{name:'Week',exact:true}).click();
    const nextDate=new Date(date);nextDate.setDate(nextDate.getDate()+1);const key=nextDate.toISOString().slice(0,10);
    await panel().locator('.calendar-task-card').first().waitFor();
    const transfer=await page.evaluateHandle(()=>new DataTransfer());await transfer.evaluate(data=>data.setData('taskId','task-one'));
    const target=panel().locator('.calendar-day-card[data-date="'+key+'"]');
    await Promise.all([page.waitForResponse(response=>response.url().includes('/api/tasks/task-one')&&response.request().method()==='PATCH'),target.dispatchEvent('drop',{dataTransfer:transfer})]);
    assert(tasks[0].due_at===new Date(key+'T00:00:00+05:30').toISOString(),'Drop used the browser timezone instead of the profile timezone');
    await target.getByText('Realtime updated fixture',{exact:true}).first().waitFor();
    failWrite=true;
    await Promise.all([page.waitForResponse(response=>response.url().includes('/api/tasks/task-one')&&response.status()===403),panel().locator('.calendar-day-card[data-today="true"]').dispatchEvent('drop',{dataTransfer:transfer})]);
    await target.getByText('Realtime updated fixture',{exact:true}).first().waitFor();
    tasks=previous;await page.evaluate(()=>window.__taskEvent({type:'task.changed'}));
  });
  await check('Calendar uses the profile zone and never posts task data to unconfigured external endpoints',async()=>{
    const previous=tasks;const tomorrow=new Date(date);tomorrow.setDate(tomorrow.getDate()+1);
    tasks=[...tasks,{...tasks[0],id:'tomorrow-task',due_at:tomorrow.toISOString().slice(0,10)+'T10:00:00'}];
    await visit('/tasks/calendar');await panel().getByRole('button',{name:'Day',exact:true}).click();await page.waitForLoadState('networkidle');
    assert(requests.filter(request=>request.path.startsWith('/tasks/calendar/')).every(request=>new URLSearchParams(request.search).get('timezone')==='Asia/Kolkata'),'Calendar requests lack the profile timezone');
    assert(externalWrites.length===0,JSON.stringify(externalWrites));tasks=previous;
  });
  await check('Leaving All Tasks closes its socket without a delayed reconnect',async()=>{
    const before=await page.evaluate(()=>window.__taskSockets.length);
    await page.evaluate(()=>location.hash='/settings/profile');await page.getByRole('tab',{name:'General / Profile',exact:true}).waitFor();
    await page.waitForTimeout(1300);
    assert(await page.evaluate(()=>window.__taskSockets.filter(socket=>socket.readyState===1).length)===0,'Socket survived module unmount');
    assert(await page.evaluate(()=>window.__taskSockets.length)===before,'Disposed socket reconnected');
  });
  await check('Unknown task tab is handled without rendering a task view',async()=>{await visit('/tasks/unknown');await page.getByRole('heading',{name:'Page Not Found',exact:true}).waitFor();});
  await check('No uncaught browser errors',async()=>assert(errors.length===0,errors.join('\n')));
  return {passed:results.filter(row=>row.status==='PASS').length,failed:results.filter(row=>row.status==='FAIL').length,results,errors,writes,externalWrites,calendarTimezones:[...new Set(requests.filter(request=>request.path.startsWith('/tasks/calendar/')).map(request=>new URLSearchParams(request.search).get('timezone')))]};
}
