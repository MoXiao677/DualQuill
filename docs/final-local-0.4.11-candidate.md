# 0.4.11 修布局前候选，不接受、不覆盖

本候选C06/C14后端已通过本机5项与父独立24组主链、34组守卫、4组真实HTTP；父隐藏桌面5组行为通过。但1440宽、双侧栏打开时工作流控制栏不换行，取消/刷新按钮超出可视边界，属于真实产品视觉缺陷。父source-ui-02-visual-red以toolbar client910/scroll1071、cancel右1463/refresh右1543保留有效RED。

run161实际生成的固定候选：

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `AI Novel Writer-0.4.11-win.zip` | 165443002 | `13f4f66d994fb55670217e37608c88acecb2cb221f83bcdcc7dac6e44f938324` |
| `AI Novel Writer Setup 0.4.11.exe` | 122061276 | `ad73b7a01420fc153f7687ba65e19a6ee987793ea7f7d172d0801a27e48b4f2d` |

stage为`desktop/.cache/build-stage-0d46533c80e3`，146源；固定文件不覆盖。run160完整回归在得知视觉RED后，仅终止归属明确的本次Python测试进程；原日志保留，未得完整终态，不计通过。修复从0.4.12重新冻结、完整回归和独立构建。0.4.10正式接受产物保持封存。

run151的取消后step、截断预览提前EOF为测试夹具问题；run152修正夹具后5项通过。run153使用不存在的顶部workflow导航选择器、run155取消POST尚未结束即释放尾流均为夹具问题，run157修正后5组/4次loopback通过。父跨书GET500为真实缺陷，已修为缺失实体404，run154与父source-http-02通过。run158版本测试尚指向0.4.10，已同步本版notices与断言，run162 Node24/静态JS29通过。全部旧失败保留，不将行为绿当排版绿。

真实付费0；只使用隔离虚构库、profile和随机loopback，未操作正式data、8765、作者窗口/凭据、冻结stage或全局设置；安装器不执行，无提交、推送、签名或发布。
