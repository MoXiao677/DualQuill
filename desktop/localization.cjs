'use strict';
const messages={
  "startupTitle": "写作工作台启动失败",
  "startup": "内置写作服务未能启动。请检查应用资源及数据目录是否可写；已有小说和升级前备份保留。",
  "unsavedTitle": "保留未保存修改",
  "unsaved": "还有未保存的正文、资料、创作需求或正在处理的操作。",
  "unsavedDetail": "继续编辑并保存后再关闭；选择放弃将丢失本窗口尚未保存的输入。",
  "keep": "继续编辑",
  "discard": "放弃未保存并关闭",
  "operation": "本机操作失败或入口受限。请保留输入，已保存内容仍在；长操作请核对状态。"
};
function text(_language,key){return messages[key];}
module.exports={text};
