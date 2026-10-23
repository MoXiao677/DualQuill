
// 仅调用原有本机接口；token 留在窗口内存。
let token = '';
export async function downloadFile(path,filename){
  if(window.novelDesktop?.download)return (await window.novelDesktop.download(path)).saved;
  const link=document.createElement('a');link.href=path;link.download=filename;document.body.append(link);link.click();link.remove();return true;
}
export function setToken(value) { token = value; }
export async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-Novel-Token': token, ...(options.headers || {}) } });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error||'操作失败，请保留输入后重试。');
    error.status = response.status;
    error.originalMessage=result.error||'';
    error.code=result.code||null;
    throw error;
  }
  return result;
}
