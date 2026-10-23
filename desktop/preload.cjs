'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('novelDesktop',Object.freeze({
  version:1,
  download:route=>ipcRenderer.invoke('desktop:download',route),
  info:(...args)=>{if(args.length)throw Error('Unexpected IPC parameters');return ipcRenderer.invoke('desktop:info');},
  onBackendEnded:callback=>{
    if(typeof callback!=='function')throw Error('Callback required');
    const listener=()=>callback();ipcRenderer.on('desktop:backend-ended',listener);
    return ()=>ipcRenderer.removeListener('desktop:backend-ended',listener);
  }
}));
