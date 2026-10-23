'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../src/novel_writer/ui/static/app.js'),'utf8').replace(/\r\n/g,'\n');
function sourceBetween(first,last){const start=app.indexOf(first);assert(start>=0,'handler anchor exists');const end=app.indexOf(last,start+first.length);assert(end>start,'handler end exists');return app.slice(start,end);}
function setup(kind,composing=false){
 const stats={clicks:0,focus:0,finds:0,saves:0,commands:0,prevented:0};let callback;
 const nodes={
  '#command-search':{addEventListener:(_type,fn)=>callback=fn},
  '#find-input':{addEventListener:(_type,fn)=>callback=fn},
  '#command-list button:not(:disabled)':{click:()=>stats.clicks++,focus:()=>stats.focus++},
  '#find-bar':{hidden:false},'#edit-content':{focus:()=>stats.focus++},
  '#content form[data-action]':{requestSubmit:()=>stats.saves++}
 };
 const source=kind==='command'?sourceBetween("$('#command-search').addEventListener('keydown',","\n$('#find-input').addEventListener"):
  kind==='find'?sourceBetween("$('#find-input').addEventListener('keydown',","\ndocument.addEventListener('compositionstart'"):
  sourceBetween("document.addEventListener('keydown',event=>{","\n\n$('#export-project')");
 vm.runInNewContext(source,{$:selector=>nodes[selector],composing,busy:false,findNext:()=>stats.finds++,openCommands:()=>stats.commands++,document:{addEventListener:(_type,fn)=>callback=fn,querySelector:()=>null}});
 return {stats,nodes,dispatch(properties){callback({key:'Enter',isComposing:false,keyCode:13,preventDefault:()=>stats.prevented++,...properties});}};
}
for(const [label,properties,active]of [['isComposing',{isComposing:true},false],['legacy229',{keyCode:229},false],['tracked composition',{},true]]){
 test('command Enter during '+label+' cannot execute',()=>{const s=setup('command',active);s.dispatch(properties);assert.equal(s.stats.clicks,0);});
 test('command ArrowDown during '+label+' cannot move candidate focus',()=>{const s=setup('command',active);s.dispatch({key:'ArrowDown',...properties});assert.equal(s.stats.focus,0);});
 test('find Enter during '+label+' cannot change manuscript selection',()=>{const s=setup('find',active);s.dispatch(properties);assert.equal(s.stats.finds,0);});
 test('find Escape during '+label+' cannot close find or move focus',()=>{const s=setup('global',active);s.dispatch({key:'Escape',...properties});assert.equal(s.nodes['#find-bar'].hidden,false);assert.equal(s.stats.focus,0);});
 test('Ctrl+S during '+label+' cannot persist manuscript',()=>{const s=setup('global',active);s.dispatch({key:'s',ctrlKey:true,...properties});assert.equal(s.stats.saves,0);});
 test('Ctrl+K during '+label+' cannot open commands',()=>{const s=setup('global',active);s.dispatch({key:'k',ctrlKey:true,...properties});assert.equal(s.stats.commands,0);});
}
test('normal Enter executes a command once',()=>{const s=setup('command');s.dispatch({});assert.equal(s.stats.clicks,1);});
test('normal command ArrowDown moves focus',()=>{const s=setup('command');s.dispatch({key:'ArrowDown'});assert.equal(s.stats.focus,1);});
test('normal find Enter searches',()=>{const s=setup('find');s.dispatch({});assert.equal(s.stats.finds,1);});
test('normal find Escape closes and returns focus',()=>{const s=setup('global');s.dispatch({key:'Escape'});assert.equal(s.nodes['#find-bar'].hidden,true);assert.equal(s.stats.focus,1);});
test('normal Ctrl+S submits once',()=>{const s=setup('global');s.dispatch({key:'s',ctrlKey:true});assert.equal(s.stats.saves,1);});
test('normal Ctrl+K opens commands once',()=>{const s=setup('global');s.dispatch({key:'k',ctrlKey:true});assert.equal(s.stats.commands,1);});
