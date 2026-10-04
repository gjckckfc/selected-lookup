# 生词本 / Vocabulary

这是「选中即查」自动生成的本地生词本。**纯 Markdown，不联网，不花 token**，
内容只写在本目录里，整个文件夹拷走就带走了全部记录，放回来就接着用。

## 目录结构

```
vocabulary/
├─ README.md               这份说明（给人和 AI 看）
├─ raw/2026-10-05.md       原稿：按天一个文件，选中即自动追加
└─ curated/                沉淀稿：后续版本从原稿里提炼，目前还没有
```

`raw/` 是**事实层**：机械化记录，查到什么写什么，不怕筛错，随时可以重新提炼。
`curated/` 是**学习层**：以后由规则或 AI 从原稿里挑出精华、去掉太简单的词。

## 收录规则

- 拖选/双击选中的英文，查到结果就自动写进当天的 `raw/YYYY-MM-DD.md`。
- 单词和短语记整条词条；句子和段落记原文 + 译文（开了整句翻译才有）+ 逐词释义。
- 同一个标题只写一次，之后每次遇到只更新 `last_seen` 和 `lookups`。
- 三条防脏门槛：查不到又没有译文的不写；不含英文字母的（纯中文）不写；原文超过 400 字截断。
- 在托盘右键菜单里可以关掉自动收录，或直接打开这个文件夹。

## 条目格式

每个条目以二级标题开始，下面是固定的 `- 字段: 值` 行，字段顺序可能略有不同。
字段名是给 AI 读的 schema，请尽量不要改名。

### 词条 type: word / phrase

```markdown
## inflation
- type: word
- phonetic: /in'fleiʃən/
- pos: n.
- meaning: 胀大, 夸张, 通货膨胀 ｜ [化] 充气吹胀; 膨胀
- forms: 复数 inflations
- tags: 六级、考研、托福、雅思 · 柯林斯 4 星
- first_seen: 2026-10-05 14:22
- last_seen: 2026-10-05 18:03
- lookups: 3
```

### 语句 type: sentence

```markdown
## the inflation rate rose sharply in 2022
- type: sentence
- translation: 2022 年通货膨胀率大幅上升。
- gloss: inflation n. 通货膨胀; rate n. 比率, 率
- source: the inflation rate rose sharply in 2022
- first_seen: 2026-10-05 14:22
- last_seen: 2026-10-05 14:22
- lookups: 1
```

## 字段说明

| 字段 | 含义 |
|---|---|
| `type` | `word` 单词 / `phrase` 短语 / `sentence` 句子或段落 |
| `phonetic` | 音标 |
| `pos` | 词性 |
| `meaning` | 中文释义，`｜` 分隔不同来源 |
| `forms` | 词形变化（复数、过去式等） |
| `tags` | 考试标签与柯林斯星级 |
| `seen_as` | 这次实际选中的变形（如选 `went` 记在 `go` 下时） |
| `translation` | 整句译文 |
| `gloss` | 逐词释义，`;` 分隔 |
| `source` | 原文，超过 400 字截断 |
| `first_seen` | 第一次收录时间 |
| `last_seen` | 最近一次遇到的时间 |
| `lookups` | 一共遇到过几次 |

## 给 AI 的说明

- 这是标准 Markdown；一条记录 = 一个 `## 标题` + 若干 `- 字段: 值`。
- 想找生词：筛 `type: word`，按 `lookups` 降序就是最该复习的。
- 想找长难句：筛 `type: sentence`，看 `translation` 和 `gloss`。
- 文件按天分片，一天一个文件，适合逐天喂给模型，不用一次读完整本。
