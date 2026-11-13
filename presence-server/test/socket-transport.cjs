// Copied to an owned scratch mount; run inside --network none with no DB/Redis.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { once } = require('node:events');
const fs = require('node:fs');
const { Server } = require('/app/node_modules/socket.io');
const jwt = require('/app/node_modules/jsonwebtoken');
const { io } = require('/client/node_modules/socket.io-client/build/cjs/index.js');
const fixture = JSON.parse(fs.readFileSync('/fixture/interop.json', 'utf8'));

test('real Socket.IO handshake, traffic and revoked-session disconnect within 18 seconds', {timeout:22000}, async () => {
  const {createPresenceAuthenticator,createSessionValidator,enforcePresenceExpiry,enforcePresenceSession} = await import('/fixture/presence-auth.mjs');
  let active=true, checks=0;
  const authority=http.createServer((request,response)=>{
    checks++;
    assert.equal(request.url,'/auth/presence/validate');
    assert.equal(request.method,'POST');
    assert.equal(request.headers.authorization,'Bearer '+fixture.presence);
    response.writeHead(active?204:401);response.end();
  });
  const server=http.createServer();
  const sockets=new Server(server);
  const clients=[];
  try {
    authority.listen(0,'127.0.0.1');await once(authority,'listening');
    const validateSession=createSessionValidator({url:`http://127.0.0.1:${authority.address().port}/auth/presence/validate`});
    sockets.use(createPresenceAuthenticator({jwt,secret:fixture.secret,algorithm:'HS256',validateSession}));
    sockets.on('connection',socket=>{
      enforcePresenceExpiry(socket);enforcePresenceSession(socket,validateSession);
      socket.on('presence:ping',ack=>ack('ok'));
    });
    server.listen(0,'127.0.0.1');await once(server,'listening');
    const connect=token=>{
      const socket=io(`http://127.0.0.1:${server.address().port}`,{auth:{token},transports:['websocket'],reconnection:false,forceNew:true});
      clients.push(socket);return socket;
    };
    const wrong=connect(fixture.access);
    const [failure]=await once(wrong,'connect_error');assert.ok(failure instanceof Error);wrong.close();
    assert.equal(checks,0); // Wrong profile never reaches the authority.
    const valid=connect(fixture.presence);await once(valid,'connect');
    assert.equal(await valid.timeout(2000).emitWithAck('presence:ping'),'ok');
    active=false;
    const start=Date.now();
    const [reason]=await once(valid,'disconnect');
    assert.equal(reason,'io server disconnect');
    assert.ok(Date.now()-start<=18000);
    const revoked=connect(fixture.presence);await once(revoked,'connect_error');
    assert.ok(checks>=3);
  } finally {
    clients.forEach(client=>client.close());
    await new Promise(resolve=>sockets.close(resolve));
    await new Promise(resolve=>authority.close(resolve));
  }
});
