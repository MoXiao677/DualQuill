'use strict';
const {app,BrowserWindow,protocol,session,ipcMain,dialog}=require('electron');
const fs=require('node:fs/promises'),path=require('node:path');
const {text}=require('./localization.cjs');
const {Backend}=require('./backend.cjs');
const {APP_URL,CSP,classify,assertSender,downloadPath}=require('./security.cjs');
const hidden=app.commandLine.hasSwitch('background-test');
let window=null,backend=null,finishing=false,closeBlocked=0;
const uiLanguage='zh-CN';
const tr=key=>text(uiLanguage,key);
app.commandLine.appendSwitch('disable-background-networking');
if(hidden)app.disableHardwareAcceleration();
protocol.registerSchemesAsPrivileged([{scheme:'novel',privileges:{standard:true,secure:true,supportFetchAPI:true,corsEnabled:true,stream:true}}]);
const selectedProfile=app.commandLine.getSwitchValue('profile-dir');
if(selectedProfile&&!path.isAbsolute(selectedProfile))throw Error('Profile must be an absolute directory');
const selectedDatabase=app.commandLine.getSwitchValue('database');
if(selectedDatabase&&!path.isAbsolute(selectedDatabase))throw Error('Database must be an absolute file path');
app.setPath('userData',selectedProfile||path.join(app.getPath('appData'),'DualQuill'));
const ownsInstance=app.requestSingleInstanceLock();
if(!ownsInstance)app.quit();
else {
  app.on('second-instance',()=>{if(!hidden&&window){if(window.isMinimized())window.restore();window.focus();}});
  app.on('before-quit',event=>{if(finishing)return;event.preventDefault();if(window&&!window.isDestroyed())window.close();else void finish();});
  app.on('window-all-closed',()=>{void finish();});
  app.whenReady().then(start).catch(async()=>{
    if(finishing)return;
    if(!hidden)await dialog.showMessageBox({type:'error',title:tr('startupTitle'),message:tr('startup')});
    else process.stderr.write('DESKTOP_START_FAILED\n');
    await finish(1);
  });
}
async function finish(code=0){if(finishing)return;finishing=true;if(backend)await backend.stop();app.exit(code);}
async function start(){
  const resources=app.isPackaged?process.resourcesPath:path.join(__dirname,'.cache','stage');
  backend=new Backend({resources,profile:app.getPath('userData'),database:selectedDatabase||undefined,onExit:()=>{if(window&&!window.isDestroyed())window.webContents.send('desktop:backend-ended');}});
  let backendReady=false;
  const boot=backend.start();
  // Keep rejection handled while the loading window is being created.
  boot.catch(()=>{});
  const isolated=session.fromPartition('persist:writing');
  isolated.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
  isolated.setPermissionCheckHandler(()=>false);
  isolated.webRequest.onBeforeRequest((details,callback)=>callback({cancel:!details.url.startsWith(APP_URL)}));
  isolated.on('will-download',(event,item)=>{if(!item.getURL().startsWith(APP_URL+'api/'))event.preventDefault();});
  await isolated.protocol.handle('novel',async request=>{
    try {
      const route=classify(request.url,request.method);
      if(!backendReady&&route.path==='/')return new Response('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DualQuill · 正在启动</title><style>body{background:#151515;color:#ddd;font:16px system-ui;display:grid;place-content:center;height:90vh}p{color:#aaa}</style><h1>DualQuill</h1><p role="status">正在启动本地写作服务，请稍候…</p></html>',{headers:{'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':CSP,'Cache-Control':'no-store'}});
      if(!backendReady&&route.kind==='api')return Response.json({error:'本地服务正在启动，请稍候'},{status:503});
      if(route.kind==='asset'){
        const content=await fs.readFile(path.join(resources,'backend','src','novel_writer','ui','static',route.file));
        const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[path.extname(route.file)];
        return new Response(content,{headers:{'Content-Type':mime+'; charset=utf-8','Content-Security-Policy':CSP,'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'}});
      }
      // Browser compatibility shim has no authority; the real token never leaves main.
      if(route.path==='/api/session')return Response.json({token:''});
      return await backend.request(request,route.path);
    }catch{
      return Response.json({error:tr('operation')},{status:422});
    }
  });
  ipcMain.handle('desktop:info',(event,...args)=>{
    assertSender(event,window?.webContents);if(args.length)throw Error('Unexpected IPC parameters');
    return {version:1,platform:'win32',manualDefault:true,uiLanguage};
  });
  ipcMain.handle('desktop:download',async(event,route,...args)=>{
    assertSender(event,window?.webContents);if(args.length)throw Error('Unexpected IPC parameters');
    const pathname=downloadPath(route),response=await backend.request(new Request(APP_URL.slice(0,-1)+pathname),pathname);
    if(!response.ok)throw Error('导出文件读取失败');
    const disposition=response.headers.get('content-disposition')||'';
    let filename=pathname.includes('/backups/')?'novel-library.nwbak':'novel.'+(pathname.includes('/md')?'md':'txt');
    const match=disposition.match(/filename\*=UTF-8''([^;]+)/i)||disposition.match(/filename="([^"]+)"/i);
    if(match)try{filename=decodeURIComponent(match[1]);}catch{}
    filename=path.basename(filename).replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,180);
    const testDirectory=hidden?app.commandLine.getSwitchValue('test-download-dir'):'';
    if(testDirectory&&!path.isAbsolute(testDirectory))throw Error('Test download directory must be absolute');
    const selection=testDirectory?{filePath:path.join(testDirectory,filename)}:await dialog.showSaveDialog(window,{title:'保存导出文件',defaultPath:filename});
    if(selection.canceled||!selection.filePath)return {saved:false};
    const bytes=Buffer.from(await response.arrayBuffer());if(bytes.length>512*1024*1024)throw Error('导出文件过大');
    await fs.writeFile(selection.filePath,bytes);return {saved:true};
  });
  window=new BrowserWindow({title:'DualQuill',width:1440,height:940,minWidth:800,minHeight:580,
    icon:path.join(__dirname,'assets','icon.ico'),
    show:false,autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.cjs'),session:isolated,
      nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true,allowRunningInsecureContent:false,
      webviewTag:false,devTools:false,spellcheck:false,offscreen:hidden,backgroundThrottling:!hidden}});
  window.setMenu(null);
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',(event,url)=>{if(url!==APP_URL)event.preventDefault();});
  window.webContents.on('will-frame-navigate',(event)=>{if(event.url!==APP_URL)event.preventDefault();});
  window.webContents.on('will-attach-webview',event=>event.preventDefault());
  window.webContents.on('will-prevent-unload',event=>{
    closeBlocked++;
    if(hidden)return;
    const choice=dialog.showMessageBoxSync(window,{type:'warning',title:tr('unsavedTitle'),message:tr('unsaved'),detail:tr('unsavedDetail'),buttons:[tr('keep'),tr('discard')],defaultId:0,cancelId:0,noLink:true});
    if(choice===1)event.preventDefault();
  });
  window.on('closed',()=>{window=null;void finish();});
  await window.loadURL(APP_URL);
  if(!hidden)window.show();
  await boot;
  if(finishing||!window||window.isDestroyed())return;
  backendReady=true;
  await window.loadURL(APP_URL);
}
function status(){return {backendPid:backend?.child?.pid||null,port:backend?.port||null,closeBlocked,packaged:app.isPackaged,hidden};}
module.exports={status};
