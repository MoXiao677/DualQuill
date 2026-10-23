'use strict';
const {spawn}=require('node:child_process');
const {randomBytes,timingSafeEqual}=require('node:crypto');
const http=require('node:http');
const path=require('node:path');
const fs=require('node:fs');
const {Readable}=require('node:stream');
const {proxyHeaders}=require('./security.cjs');
function childEnvironment(source,profile){
  const env={},names=new Map(Object.keys(source).map(name=>[name.toUpperCase(),name]));
  for(const name of ['SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA']){
    const key=names.get(name);if(key&&typeof source[key]==='string')env[name]=source[key];
  }
  const windows=env.SYSTEMROOT||env.WINDIR||'C:/Windows';
  env.PATH=[path.join(windows,'System32'),windows,path.join(windows,'System32','WindowsPowerShell','v1.0')].join(';');
  if(profile){env.USERPROFILE=profile;env.TEMP=path.join(profile,'tmp');env.TMP=env.TEMP;env.APPDATA=path.join(profile,'environment','Roaming');env.LOCALAPPDATA=path.join(profile,'environment','Local');}
  return env;
}
class Backend {
  constructor({resources,profile,database,startupMs=15000,onExit=()=>{}}) {
    Object.assign(this,{resources,profile,database,startupMs,onExit});
    this.token=randomBytes(32).toString('hex');this.nonce=randomBytes(32).toString('hex');
    this.stopping=false;this.exited=false;this.port=0;
  }
  async start() {
    const env=childEnvironment(process.env,this.profile);
    for(const key of ['TEMP','APPDATA','LOCALAPPDATA'])fs.mkdirSync(env[key],{recursive:true});
    const args=['-B','-X','utf8','-u','-m','novel_writer.ui.desktop','--profile',this.profile];
    if(this.database)args.push('--database',this.database);
    this.child=spawn(path.join(this.resources,'runtime','python.exe'),args,{cwd:path.join(this.resources,'backend'),env,windowsHide:true,stdio:['pipe','pipe','pipe']});
    this.closed=new Promise(resolve=>this.child.once('close',()=>{this.exited=true;resolve();if(!this.stopping&&this.port)this.onExit();}));
    this.child.stdin.on('error',()=>{});this.child.stderr.resume();
    try {
      await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>reject(Error('后端启动超时 (startup timeout)')),this.startupMs);
        const fail=()=>{clearTimeout(timer);reject(Error('内置运行时启动失败 (startup failed)'));};
        this.child.once('error',fail);this.child.once('exit',fail);let text='',ready=false;
        this.child.stdout.setEncoding('utf8');
        this.child.stdout.on('data',chunk=>{
          if(ready)return;text+=chunk;if(text.length>4096)return fail();
          const end=text.indexOf('\n');if(end<0)return;
          try {
            const data=JSON.parse(text.slice(0,end));
            if(Object.keys(data).sort().join(',')!=='nonce,pid,port,protocol,type'||data.type!=='ready'||data.protocol!==1||data.pid!==this.child.pid||!Number.isInteger(data.port)||data.port<1||data.port>65535||typeof data.nonce!=='string'||data.nonce.length!==64||!timingSafeEqual(Buffer.from(data.nonce),Buffer.from(this.nonce)))throw Error();
            this.port=data.port;ready=true;clearTimeout(timer);resolve();
          }catch{fail();}
        });
        this.child.stdin.write(JSON.stringify({token:this.token,nonce:this.nonce})+'\n');
      });
      return this;
    }catch(error){await this.stop();throw error;}
  }
  async stop() {
    this.stopping=true;if(!this.child)return;
    this.child.stdin.end();
    if(!this.exited&&this.child.pid) {
      let timer;await Promise.race([this.closed,new Promise(resolve=>{timer=setTimeout(resolve,6000);})]);clearTimeout(timer);
      if(!this.exited){this.child.kill();await this.closed;}
    }else await this.closed;
  }
  async request(request,pathname) {
    if(!this.port||this.stopping||this.exited)throw Error('本机写作服务已停止，请保留草稿后重新打开软件。');
    const max=pathname==='/api/backups/restore'||pathname==='/api/migrations/import'?512*1024*1024:12*1024*1024;
    let size=0,parts=[];
    if(request.body) {
      for await(const chunk of request.body){size+=chunk.length;if(size>max)throw Error('文件或请求超出允许大小');parts.push(Buffer.from(chunk));}
    }
    const body=Buffer.concat(parts);parts=[];
    return await new Promise((resolve,reject)=>{
      const operation=http.request({hostname:'127.0.0.1',port:this.port,path:pathname,method:request.method,
        headers:proxyHeaders(request.headers,this.token,this.port,request.method==='POST'?body.length:undefined),agent:false},response=>{
        const headers=new Headers();for(const name of ['content-type','content-disposition','content-length']){if(response.headers[name])headers.set(name,response.headers[name]);}
        headers.set('Cache-Control','no-store');headers.set('X-Content-Type-Options','nosniff');
        response.on('error',()=>{});resolve(new Response(Readable.toWeb(response),{status:response.statusCode,headers}));
      });
      operation.setTimeout(310000,()=>operation.destroy(Error('本机请求超时；请核对操作状态。')));
      operation.on('error',()=>reject(Error('本机请求中断；已保存内容保留，请核对操作状态。')));
      if(request.signal)request.signal.addEventListener('abort',()=>operation.destroy(),{once:true});
      operation.end(body);
    });
  }
}
module.exports={Backend,childEnvironment};
