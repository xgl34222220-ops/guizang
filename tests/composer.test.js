'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('public/index.html', 'utf8');
const source = html.slice(html.indexOf('function draftKey(){'), html.indexOf('\n$("#send").onclick=send;'));
function setup() {
  const nodes = {'#input':{value:'first'}, '#send':{disabled:false}, '#reply':{hidden:false}};
  const sent=[], notices=[];
  let ack;
  const storage=new Map();
  const state = {crypto:require('node:crypto').webcrypto,Uint8Array,room:'main',role:'owner',pendingSend:null,draftScope:'guizang.draft.v1:main:owner',
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    sending:false, observer:false, roomReady:true, replyTo:null, kind:'chat', R:{},K:{chat:1,proposal:1},setKind:()=>{},
    $:id=>nodes[id], toast:s=>notices.push(s),
    socket:{connected:true, timeout(ms){assert.equal(ms,15000);return {emit(event,payload,cb){sent.push({event,payload});ack=cb}}},emit(){}}};
  vm.createContext(state);vm.runInContext(source,state);
  return {state,nodes,sent,notices,storage,ack:(...args)=>ack(...args)};
}
test('blocks duplicate submission and clears only acknowledged draft',()=>{const t=setup();t.state.send();t.state.send();assert.equal(t.sent.length,1);t.ack(null,{ok:true});assert.equal(t.nodes['#input'].value,'');assert.equal(t.state.sending,false)});
test('new typing survives old acknowledgement',()=>{const t=setup();t.state.send();t.nodes['#input'].value='second';t.ack(null,{ok:true});assert.equal(t.nodes['#input'].value,'second')});
test('timeout retains content without automatic retry',()=>{const t=setup();t.state.send();t.ack(new Error('timeout'));assert.equal(t.nodes['#input'].value,'first');assert.equal(t.sent.length,1);assert.equal(t.nodes['#send'].disabled,false)});
test('must finish joining room before sending',()=>{const t=setup();t.state.roomReady=false;t.state.send();assert.equal(t.sent.length,0);assert.equal(t.nodes['#input'].value,'first')});
test('observer cannot send',()=>{const t=setup();t.state.observer=true;t.state.send();assert.equal(t.sent.length,0)});
test('over-limit messages retained rather than truncated',()=>{const t=setup();t.nodes['#input'].value='x'.repeat(12001);t.state.send();assert.equal(t.sent.length,0);assert.equal(t.nodes['#input'].value.length,12001)});
test('new reply selection survives acknowledgement',()=>{const t=setup();t.state.replyTo={body:'old'};t.state.send();const newer={body:'new'};t.state.replyTo=newer;t.ack(null,{ok:true});assert.equal(t.state.replyTo,newer);assert.equal(t.nodes['#reply'].hidden,false)});
test('synchronous transport failure releases button',()=>{const t=setup();t.state.socket.timeout=()=>{throw Error('closed')};t.state.send();assert.equal(t.state.sending,false);assert.equal(t.nodes['#input'].value,'first')});
test('Enter respects Chinese IME and Shift while plain Enter sends',()=>{
  const code=html.match(/addEventListener\("keydown",(e=>\{.*?\})\);/)[1];
  let sent=0, prevented=0;
  const handler=vm.runInNewContext(`(${code})`, {send:()=>sent++});
  for(const extra of [{isComposing:true},{keyCode:229},{shiftKey:true},{key:'a'}]) {
    handler({key:'Enter',shiftKey:false,isComposing:false,keyCode:13,preventDefault:()=>prevented++,...extra});
  }
  assert.equal(sent,0);assert.equal(prevented,0);
  handler({key:'Enter',preventDefault:()=>prevented++});
  assert.equal(sent,1);assert.equal(prevented,1);
});
test('inline scripts parse',()=>{for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)){if(m[1].trim())new vm.Script(m[1])}});

test('disconnected socket retains draft',()=>{const t=setup();t.state.socket.connected=false;t.state.send();assert.equal(t.sent.length,0);assert.equal(t.nodes['#input'].value,'first')});
test('negative acknowledgement keeps draft and reply',()=>{const t=setup();const reply={body:'quote'};t.state.replyTo=reply;t.state.send();t.ack(null,{ok:false});assert.equal(t.nodes['#input'].value,'first');assert.equal(t.state.replyTo,reply);assert.equal(t.nodes['#send'].disabled,false)});
test('late acknowledgement after timeout cannot clear a newer draft',()=>{const t=setup();t.state.send();t.ack(new Error('timeout'));t.nodes['#input'].value='second';t.ack(null,{ok:true});assert.equal(t.nodes['#input'].value,'second')});
test('reply quote is included in length limit',()=>{const t=setup();t.nodes['#input'].value='x'.repeat(11999);t.state.replyTo={body:'quote'};t.state.send();assert.equal(t.sent.length,0)});
test('exact length limit is accepted',()=>{const t=setup();t.nodes['#input'].value='x'.repeat(12000);t.state.send();assert.equal(t.sent.length,1)});
test('blank draft does not send',()=>{const t=setup();t.nodes['#input'].value='  \n ';t.state.send();assert.equal(t.sent.length,0)});

test('manual retry keeps request ID; successful identical new message gets a fresh ID',()=>{
  const t=setup();t.state.send();const first=t.sent[0].payload.clientRequestId;
  t.ack(new Error('timeout'));t.state.send();assert.equal(t.sent[1].payload.clientRequestId,first);
  t.ack(null,{ok:true,id:1});t.nodes['#input'].value='first';t.state.send();
  assert.notEqual(t.sent[2].payload.clientRequestId,first);
});
test('changing body or kind creates a new request instead of overwriting pending content',()=>{
  const t=setup();t.state.send();t.ack(new Error('timeout'));const first=t.sent[0].payload.clientRequestId;
  t.nodes['#input'].value='changed';t.state.send();assert.notEqual(t.sent[1].payload.clientRequestId,first);
  t.ack(new Error('timeout'));const second=t.sent[1].payload.clientRequestId;t.state.kind='proposal';t.state.send();assert.notEqual(t.sent[2].payload.clientRequestId,second);
});
test('pending request and draft survive per-tab restore without sending',()=>{
  const t=setup();t.state.send();t.ack(new Error('timeout'));const id=t.sent[0].payload.clientRequestId;
  t.state.pendingSend=null;t.state.draftScope=null;t.nodes['#input'].value='';t.state.restoreDraft();
  assert.equal(t.nodes['#input'].value,'first');assert.equal(t.sent.length,1);assert.equal(t.state.pendingSend.clientRequestId,id);
  t.state.send();assert.equal(t.sent[1].payload.clientRequestId,id);
});
test('draft storage is isolated by room and authenticated role',()=>{
  const t=setup();t.state.saveDraft();const original=t.storage.get('guizang.draft.v1:main:owner');
  t.state.room='other';t.state.draftScope=null;t.nodes['#input'].value='other draft';t.state.restoreDraft();t.state.saveDraft();
  assert.equal(t.storage.get('guizang.draft.v1:main:owner'),original);
  t.state.role='muse';t.state.draftScope=null;t.nodes['#input'].value='Muse draft';t.state.restoreDraft();t.state.saveDraft();
  assert.equal(JSON.parse(t.storage.get('guizang.draft.v1:other:owner')).text,'other draft');
  t.state.role='owner';t.state.room='main';t.state.draftScope=null;t.state.restoreDraft();assert.equal(t.nodes['#input'].value,'first');
});
test('storage denial does not lose the in-memory retry ID',()=>{
  const t=setup();t.state.sessionStorage.setItem=()=>{throw Error('blocked')};t.state.send();t.ack(new Error('timeout'));t.state.send();assert.equal(t.sent[0].payload.clientRequestId,t.sent[1].payload.clientRequestId);
});
test('old room/socket acknowledgement does not clear a current draft',()=>{
  const t=setup();t.state.send();t.state.room='other';t.nodes['#input'].value='other draft';t.ack(null,{ok:true,id:1});assert.equal(t.nodes['#input'].value,'other draft');
});
test('history/live delivery ignores foreign rooms and deduplicates confirmed IDs',()=>{
  const handlers={}; const state={socket:{on:(name,fn)=>handlers[name]=fn},room:'main',role:'owner',messages:[],meta:{},roomReady:false,unread:0,
    applyMeta:()=>{},render:()=>{},nearBottom:()=>true,$:()=>({})};
  vm.createContext(state);
  for(const name of ['room:state','message:new']){const line=html.split('\n').find(line=>line.includes(`socket.on("${name}"`));vm.runInContext(line,state)}
  const message={id:1,room_key:'main',body:'saved',role:'owner'};
  handlers['room:state']({room:'other',messages:[message]});assert.equal(state.roomReady,false);
  handlers['room:state']({room:'main',messages:[message,message]});assert.equal(state.messages.length,1);
  handlers['message:new'](message);handlers['message:new']({id:2,room_key:'other'});assert.equal(state.messages.length,1);
});
