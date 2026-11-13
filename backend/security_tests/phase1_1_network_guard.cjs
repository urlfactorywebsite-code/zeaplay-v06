/* Preload for source-only Node audits. Never start app services or listeners. */
'use strict';
const deny = () => { throw new Error('Phase 1.1 audit forbids network/listeners'); };
const net = require('node:net');
net.Socket.prototype.connect = deny;
net.Server.prototype.listen = deny;
require('node:tls').connect = deny;
for (const protocol of ['node:http', 'node:https']) {
  const mod = require(protocol);
  mod.request = deny;
  mod.get = deny;
}
const datagram = require('node:dgram');
datagram.Socket.prototype.bind = deny;
datagram.Socket.prototype.connect = deny;
datagram.Socket.prototype.send = deny;
const dns = require('node:dns');
for (const key of Object.keys(dns)) {
  if (typeof dns[key] === 'function' && /^(lookup|resolve|reverse)/.test(key)) dns[key] = deny;
}
for (const key of Object.keys(dns.promises)) {
  if (typeof dns.promises[key] === 'function' && /^(lookup|resolve|reverse)/.test(key)) dns.promises[key] = deny;
}
globalThis.fetch = deny;
globalThis.WebSocket = class { constructor() { deny(); } };
require('node:module').syncBuiltinESMExports();
