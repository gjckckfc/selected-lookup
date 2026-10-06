# 第三方数据与许可

本项目代码以 MIT 许可发布。运行时依赖的词典数据来源如下。

## ECDICT

- 上游项目：`skywind3000/ECDICT`
- 许可：**MIT License**
- 本项目使用的数据版本：`ecdict-bc015ed2-focus13-v2`
- 上游提交：`bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b`
- 词条数：770,611

## 打包来源

`data/ecdict.sqlite` 由下面的第三方打包仓库提供（它把上游 ECDICT 整理成 SQLite，
并额外附加了词形索引与 13 张考试词表）：

- 仓库：`iamzhangship/fluency-ecdict-offline`
- 归档文件：`ecdict-ecdict-bc015ed2-focus13-v2.zip`
- 归档大小：54,594,964 字节
- 归档 SHA-256：`1e745ea698878772226a7df584129409dd4b27cb7ea26b4259bc770e7533352f`
- 解包后：`ecdict.sqlite`，131,756,032 字节

校验方式：下载后比对上面的 SHA-256，再确认 `dictionary_meta` 表里的
`source_sha256` 等于 `1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf`。

## 考试词表

`focus_word_memberships` 表里的 13 张词表（高考、中考、CET4/6、考研、雅思、托福、
GRE、GMAT、TEM4/8、商务 5000、日常 3000）各自的来源与许可见
`focus_word_list_meta` 表的 `source_name` / `license` 字段。

其中 11 张来自 ECDICT 自带的考试标签与词频字段，随 ECDICT 的 MIT 许可；
**剩下 2 张的来源不是 ECDICT，许可是 CC BY-SA 4.0**，需要单独署名：

| 词表 | 来源 |
|---|---|
| GMAT | NGSL / NAWL / BSL / TOEIC + ECDICT 的 gre & toefl |
| 商务 5000 | TOEIC 1.2 + BSL 1.2 + NGSL 1.2 |

### CC BY-SA 4.0 署名

上面两张词表用到的源词表来自 <https://www.newgeneralservicelist.org/>，
快照取自 `nltk-data-hub/words`（commit `1834637f1b759aad676cc47cb71708700bf8c2b4`）：

- New General Service List 1.2 — Charles Browne
- New Academic Word List 1.2 — Charles Browne, Brent Culligan, Joseph Phillips
- Business Service List 1.2 — Charles Browne, Brent Culligan
- TOEIC Service List 1.2 — Charles Browne, Brent Culligan

许可全文：<https://creativecommons.org/licenses/by-sa/4.0/>

相应的派生数据（`focus_word_memberships` 里那两张表的成员关系）按
**CC BY-SA 4.0** 分发，署名同上。其余 11 张词表随 ECDICT 的 MIT 许可。

## 分发提醒

词典数据体积较大（约 130 MB），没有纳入版本库。若要对外分发本项目，
请随包提供本文件和上游 ECDICT 的 MIT 许可声明。

## 可选第三方工具：NaturalVoiceSAPIAdapter（**不在本仓库，也不随本项目分发**）

朗读功能用到的 Windows 神经网络语音（Ava、Emma、Aria…）系统默认只给讲述人用。
让普通程序也能用上它们的，是一个**开源社区里的独立第三方项目**，不是本项目写的：

- 项目：<https://github.com/gexgd0419/NaturalVoiceSAPIAdapter>（作者 @gexgd0419）
- 许可：**MIT**
- 它做什么：注册一个 SAPI5 语音引擎，把微软的神经网络语音暴露给所有支持 SAPI 的程序
- 本项目怎么用它：只做一件事——调 SAPI 枚举系统语音列表。**不复制、不修改、不打包、
  不再分发它的任何代码或资源**，两边没有代码耦合
- 安装方式：由用户自己安装（需要管理员权限，装完不能挪动）
- **性质提醒**：它靠从系统文件里取密钥来解锁这批语音，属于绕过微软限制的灰区做法；
  微软并未允许第三方程序使用讲述人和 Edge 的语音，系统大更新后可能失效（重装即可）
