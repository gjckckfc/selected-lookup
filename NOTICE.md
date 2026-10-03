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

## 分发提醒

词典数据体积较大（约 130 MB），没有纳入版本库。若要对外分发本项目，
请随包提供本文件和上游 ECDICT 的 MIT 许可声明。
