以下为两个核心接口的整理说明（Markdown格式），可直接交给他人用于实现批量下载程序。

---

# MangaDex 批量下载接口说明

## 1. 获取漫画章节列表（Aggregate）

### 接口

```
GET https://api.mangadex.org/manga/{mangaId}/aggregate
```

### Query 参数

| 参数                 | 说明                        |
| -------------------- | --------------------------- |
| translatedLanguage[] | 语言（如 `en`, `zh`, `ja`） |
| groups[]             | 扫描组ID（可多个）          |

### 示例

```
https://api.mangadex.org/manga/{mangaId}/aggregate?translatedLanguage[]=en
```

---

### 响应结构（简化）

```json
{
  "result": "ok",
  "volumes": {
    "15": {
      "volume": "15",
      "chapters": {
        "75": {
          "chapter": "75",
          "id": "chapter-uuid",
          "isUnavailable": false
        }
      }
    }
  }
}
```

---

### 关键字段说明

| 字段                | 说明                         |
| ------------------- | ---------------------------- |
| volumes             | 按卷分组                     |
| volumes.\*.chapters | 章节集合                     |
| chapter             | 章节号（字符串，可能含小数） |
| id                  | **章节ID（关键）**           |
| isUnavailable       | 是否不可用                   |

---

### 提取逻辑

1. 遍历 `volumes`
2. 遍历每个 `chapters`
3. 过滤：
   - `isUnavailable === false`

4. 收集：

```json
{
  "chapter": "75",
  "id": "xxxxx"
}
```

---

## 2. 获取章节图片资源

### 接口

```
GET https://api.mangadex.org/at-home/server/{chapterId}
```

### 示例

```
https://api.mangadex.org/at-home/server/{chapterId}?forcePort443=false
```

---

### 响应结构（简化）

```json
{
  "baseUrl": "https://xxx.mangadex.network",
  "chapter": {
    "hash": "hash_value",
    "data": ["img1.png", "img2.png"],
    "dataSaver": ["img1.jpg", "img2.jpg"]
  }
}
```

---

### 关键字段说明

| 字段              | 说明          |
| ----------------- | ------------- |
| baseUrl           | CDN 基础地址  |
| chapter.hash      | 图片路径 hash |
| chapter.data      | 原图          |
| chapter.dataSaver | 压缩图        |

---

### 图片 URL 拼接规则

#### 原图

```
{baseUrl}/data/{hash}/{filename}
```

#### 压缩图（推荐）

```
{baseUrl}/data-saver/{hash}/{filename}
```

---

### 示例

```text
https://xxx.mangadex.network/data/{hash}/x1.png
```

---

## 3. 下载流程

### Step 1：获取章节列表

```
aggregate → 获取所有 chapterId
```

---

### Step 2：遍历章节

对每个 `chapterId`：

```
请求 at-home/server 接口
```

---

### Step 3：生成图片 URL

```js
for (i = 0; i < pages.length; i++) {
  filename = pages[i];
  url = `${baseUrl}/data/${hash}/${filename}`;
}
```

---

### Step 4：下载并命名

文件名建议：

```
1.png
2.png
3.png
...
```

（按数组顺序 +1）

---

### Step 5：打包 ZIP（推荐）

每个章节：

```
chapter_{chapterNumber}.zip
```

---

## 4. 注意事项

### 1. 章节号不是整数

例如：

```
74.5
75.6
```

需要按 **浮点排序**

---

### 2. 多语言问题

必须加：

```
translatedLanguage[]=en
```

否则返回混合语言

---

### 3. data vs dataSaver

| 类型      | 说明               |
| --------- | ------------------ |
| data      | 原图（大）         |
| dataSaver | 压缩（推荐批量用） |

---

### 4. 限速建议

- 并发控制（例如 3~5）
- 避免触发 CDN 限流

---

### 5. headers（可选）

一般无需特殊 header，但可加：

```
Referer: https://mangadex.org/
```

---

## 5. 最小实现伪代码

```js
chapters = fetchAggregate(mangaId);

for (ch of chapters) {
  meta = fetchAtHome(ch.id);

  for (i in meta.pages) {
    url = buildImageUrl(meta, i);
    download(url);
  }

  zip();
}
```

---

如需扩展，可增加：

- 断点续传
- 已下载检测
- 多线程队列
- CLI / GUI 工具化
