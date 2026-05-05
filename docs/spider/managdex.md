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

## 6. 我人工补充内容：

比如来到某个漫画的首页，URL是这样：https://mangadex.org/title/d8f1d7da-8bb1-407b-8be3-10ac2894d3c6/isekai-ojisan?tab=chapters

然后用这个里面的UUID，调用GET接口：
https://api.mangadex.org/manga/read?ids[]=d8f1d7da-8bb1-407b-8be3-10ac2894d3c6&grouped=true

响应体：

```json
{
  "d8f1d7da-8bb1-407b-8be3-10ac2894d3c6": [
    "1928a312-3062-4a5f-af6f-5fb84f12a06e",
    "cc6c57ce-18f9-41e4-a6f5-30e39dcb2ecf"
  ]
}
```

然后通过这个GET接口，获取到两个我也不知道干啥用的ID
https://api.mangadex.org/chapter/cc6c57ce-18f9-41e4-a6f5-30e39dcb2ecf?includes[]=scanlation_group&includes[]=manga&includes[]=user

响应体：
```json
{
    "result": "ok",
    "response": "entity",
    "data": {
        "id": "cc6c57ce-18f9-41e4-a6f5-30e39dcb2ecf",
        "type": "chapter",
        "attributes": {
            "volume": "1",
            "chapter": "1",
            "title": "",
            "translatedLanguage": "en",
            "externalUrl": null,
            "isUnavailable": false,
            "publishAt": "2020-05-26T10:22:08+00:00",
            "readableAt": "2020-05-26T10:22:08+00:00",
            "createdAt": "2020-05-26T10:22:08+00:00",
            "updatedAt": "2020-05-26T10:22:08+00:00",
            "version": 1,
            "pages": 18
        },
        "relationships": [
            {
                "id": "79071f17-c5a3-4624-8caa-b55c749c8705",
                "type": "scanlation_group",
                "attributes": {
                    "name": "Dead-chan",
                    "altNames": [],
                    "locked": false,
                    "website": null,
                    "ircServer": null,
                    "ircChannel": null,
                    "discord": null,
                    "contactEmail": null,
                    "description": "#### `Uploads from this group will be scanlations of whatever I feel like or random side projects.This group does not accept recruits or commissions; this is purely a personal group consisting of only me.`\n\n  \n  \n  \n\n\n---\n\n  \n#### Projects List:\n\n\n> Ongoing Projects:\n\n  \n- *[Tadashi Ore wa Heroine Toshite](https://mangadex.org/title/24667/tadashi-ore-wa-heroine-toshite)* by Morishita Mao  \n- *[Tsumi to Kai](https://mangadex.org/title/22727/tsumi-to-kai)* by Someya Yuu  \n- *[Oversized Sextet](https://mangadex.org/title/41070/oversized-sextet)* by Amagaeru  \n- *[UNCOntrollable](https://mangadex.org/title/18220/uncontrollable)* by MIYABA Yajirou  \n- *[Hige Wo Soru. Soshite Joshikosei Wo Hirou.](https://mangadex.org/title/32043/i-shaved-then-i-brought-a-high-school-girl-home)* by Shimesaba and Adachi Imaru  \n- *[Isekai Ojisan](https://mangadex.org/title/31488/isekai-ojisan)* by Hotondo Shindeiru  \n- *[Maou-sama to Kekkon shitai](https://mangadex.org/title/28892/maou-sama-to-kekkon-shitai)* by Ikeuchi Tanuma  \n- *[Gyaru to Otaku wa Wakari Aenai.](https://mangadex.org/title/19630/gyaru-to-otaku-wa-wakari-aenai)* by Kawai Rou  \n- *[Yokubou Pandora](https://mangadex.org/title/22135/yokubou-pandora)* by Hizuki Akira  \n\n> Pending Projects:\n\n  \n- *[Eiyū no Musume Toshite Umarekawatta Eiyū wa Futatabi Eiyū o Mezasu](https://mangadex.org/title/23467/eiyuu-no-musume-toshite-umarekawatta-eiyuu-wa-futatabi-eiyuu-o-mezasu)* by Kaburagi Haruka, Akita Hika and Kotodera Amane  \n- *[Zeta⇄Raga SWITCH!](https://exhentai.org/g/1401265/0c32cb6a29/)* by Tachikawa Negoro  \n- *[Trade - Ore wa Kyou Kara Joshikousei](https://mangadex.org/title/22659/trade-ore-wa-kyou-kara-joshikousei)* by Ayaka Morita and Oshiduki  \n- *[Sayonara no Asa ni Yakusoku no Hana wo Kazarou](https://mangadex.org/title/29853/sayonara-no-asa-ni-yakusoku-no-hana-wo-kazarou)* by Iorph, Okada Mari and Mito Satou  \n- *[Koi to Utatane](https://mangadex.org/title/21204/koi-to-utatane)* by Torio Chinori  \n- *[Sakura-chan to Amane-kun](https://mangadex.org/title/25476/sakura-chan-to-amane-kun)* by Asazuki Norito  \n- *[Nyotaika Yankee Gakuen ☆ Ore no Hajimete, Nerawaretemasu.](https://mangadex.org/title/28577/nyotaika-yankee-gakuen-ore-no-hajimete-nerawaretemasu)* by Takao Yori  \n- *[Trinity Blood](https://mangadex.org/title/4901/trinity-blood)* by Yoshida Sunao and Kyujyo Kiyo  \n\n> Assisted Projects:\n\n  \n- *[Maou Desu. Onna Yuusha no Hahaoya to Saikon Shita no de, Onna Yuusha ga Giri no Musume ni Narimashita.](https://mangadex.org/title/34785/maou-desu-onna-yuusha-no-hahaoya-to-saikon-shita-no-de-onna-yuusha-ga-giri-no-musume-ni-narimashita)* by Morita Kisetsu, Ikuhashi Muiko, Sushi* and Ikuhashi Muiko  \n- *[Saikyou Juzoku Tensei: Cheat Majutsushi no Slow Life](https://mangadex.org/title/32084/saikyou-juzoku-tensei-cheat-majutsushi-no-slow-life)* by Necoco, Shinomura Asahi and Mika Pikazo  \n- *[Lv2 kara Cheat datta Moto Yuusha Kouho no Mattari Isekai Life](https://mangadex.org/title/33797/lv2-kara-cheat-datta-moto-yuusha-kouho-no-mattari-isekai-life)* by Kinojo Miya and Itomachi Akine  \n- *[Tomodachi no Imouto ga Ore ni Dake Uzai](https://mangadex.org/title/43822/tomodachi-no-imouto-ga-ore-ni-dake-uzai)* by Mikawa Ghost and Hiraoka Hira  \n- *[Shinigami ni Sodaterareta Shoujo wa Shikkoku no Tsurugi wo Mune ni Idaku](https://mangadex.org/title/40770/shinigami-ni-sodaterareta-shoujo-wa-shikkoku-no-tsurugi-wo-mune-ni-idaku)* by Ayamine Maito and Matsukaze Suiren  \n- *[Jiyo Tsuma AV Netorase-hen](https://mangadex.org/title/45638/jiyo-tsuma-av-netorase-hen)* by dosiro-do  \n- *[Touchuukasou](https://mangadex.org/title/39307/touchuukasou)* by Fuetakishi  \n\n> Completed Projects:\n\n  \n- *[Fate/Grand Order - Raikou Mama ni Omakase](https://mangadex.org/title/44878/fate-grand-order-raikou-mama-ni-omakase-doujinshi)* by Keoya  \n- *[Ore ga... Yuri!?](https://mangadex.org/title/19728/ore-ga-yuri)* by Satoru  \n\n> Dropped Projects:\n\n  \n- *[Monogatari no Naka no Hito](https://mangadex.org/title/16800/monogatari-no-naka-no-hito)* by Tanaka Nijusan and Kuroyurihime  \n- *[Watari-kun no ×× ga Houkai Sunzen](https://mangadex.org/title/12850/watari-kun-no-ga-houkai-sunzen)* by Narumi Naru  \n- *[Futanari no Elf](https://mangadex.org/title/35451/futanari-no-elf)* by Kawakami Masaki  \n- *[Saikyou no Kurokishi♂, Sentou Maid♀ ni Tenshoku shimashita](https://mangadex.org/title/29119/saikyou-no-kurokishi-sentou-maid-ni-tenshoku-shimashita)* by Momokado Isshin and Kazahana Chiruwo  \n- *[Trap Heroine](https://mangadex.org/title/23263/trap-heroine)* by Tomiki Kou  \n\n> Deleted Projects:\n\n  \n- ---\n\n  \n#### Additional Information:\n\n||Nothing at the moment.  \n||\n",
                    "twitter": null,
                    "mangaUpdates": null,
                    "focusedLanguages": [
                        "en"
                    ],
                    "official": false,
                    "verified": false,
                    "inactive": false,
                    "publishDelay": null,
                    "exLicensed": false,
                    "createdAt": "2021-04-19T21:45:59+00:00",
                    "updatedAt": "2021-04-19T21:45:59+00:00",
                    "version": 1
                }
            },
            {
                "id": "822eaeb8-9521-4a11-ac7e-d828e13179a4",
                "type": "scanlation_group",
                "attributes": {
                    "name": "Unknown III",
                    "altNames": [],
                    "locked": false,
                    "website": null,
                    "ircServer": null,
                    "ircChannel": null,
                    "discord": "yjMuxUC",
                    "contactEmail": null,
                    "description": null,
                    "twitter": null,
                    "mangaUpdates": null,
                    "focusedLanguages": [
                        "en"
                    ],
                    "official": false,
                    "verified": false,
                    "inactive": false,
                    "publishDelay": null,
                    "exLicensed": false,
                    "createdAt": "2021-04-19T21:45:59+00:00",
                    "updatedAt": "2021-04-19T21:45:59+00:00",
                    "version": 1
                }
            },
            {
                "id": "d8f1d7da-8bb1-407b-8be3-10ac2894d3c6",
                "type": "manga",
                "attributes": {
                    "title": {
                        "ja-ro": "Isekai Ojisan"
                    },
                    "altTitles": [
                        {
                            "fr": "Coma héroïque dans un autre monde"
                        },
                        {
                            "en": "Isekai Uncle"
                        },
                        {
                            "en": "Ojisan in Another World"
                        },
                        {
                            "en": "Uncle from Another World"
                        },
                        {
                            "ja": "異世界おじさん"
                        },
                        {
                            "uk": "Переродження дядька"
                        }
                    ],
                    "description": {
                        "en": "Having survived an isekai for 17 years, 34 year old Ojisan (uncle) returns to modern day Japan. Takafumi, Ojisan's nephew, now gets to witness what throwing a diehard Sega fan into an isekai for 17 years does to various things and people, both past and present.",
                        "uk": "Після сімнадцяти років коми бувалий фанат сеги повертається у реальність. На подив Такафумі, племінника чоловіка, його оповіді про подорож до іншого світу далеко не марення, а сувора реальність \"ісекаю\".\nВона не залишить нікого... байдужим. Тепер же Шибасакі, вибравшись із ненависного місця, будує нові плани на своє майбутнє.\nАдже що залишається майже тридцятип'ятирічному магу, окрім як надолужити втрачене - завести активний ютуб канал, пізнати технології та й племінника навчити уму-розуму на своєму гіркому досвіді.."
                    },
                    "isLocked": true,
                    "links": {
                        "al": "104617",
                        "ap": "uncle-from-another-world",
                        "bl": "566668",
                        "bw": "series/181865/list",
                        "kt": "54444",
                        "mu": "m0k7p2h",
                        "amz": "https://www.amazon.co.jp/dp/B07R8GQ8DZ",
                        "ebj": "https://ebookjapan.yahoo.co.jp/books/510354",
                        "mal": "120177",
                        "raw": "https://comic-walker.com/detail/KC_003631_S"
                    },
                    "officialLinks": null,
                    "originalLanguage": "ja",
                    "lastVolume": "",
                    "lastChapter": "",
                    "publicationDemographic": null,
                    "status": "ongoing",
                    "year": 2018,
                    "contentRating": "suggestive",
                    "tags": [
                        {
                            "id": "423e2eae-a7a2-4a8b-ac03-a8351462d71d",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Romance"
                                },
                                "description": {},
                                "group": "genre",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "4d32cc48-9f00-4cca-9b5a-a839f0764984",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Comedy"
                                },
                                "description": {},
                                "group": "genre",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "aafb99c1-7f60-43fa-b75f-fc9502ce29c7",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Harem"
                                },
                                "description": {},
                                "group": "theme",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "ace04997-f6bd-436e-b261-779182193d3d",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Isekai"
                                },
                                "description": {},
                                "group": "genre",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "cdc58593-87dd-415e-bbc0-2ec27bf404cc",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Fantasy"
                                },
                                "description": {},
                                "group": "genre",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "e197df38-d0e7-43b5-9b09-2842d0c326dd",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Web Comic"
                                },
                                "description": {},
                                "group": "format",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "e5301a23-ebd9-49dd-a0cb-2add944c7fe9",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Slice of Life"
                                },
                                "description": {},
                                "group": "genre",
                                "version": 1
                            },
                            "relationships": []
                        },
                        {
                            "id": "f8f62932-27da-4fe4-8ee1-6779a8c5edba",
                            "type": "tag",
                            "attributes": {
                                "name": {
                                    "en": "Tragedy"
                                },
                                "description": {},
                                "group": "genre",
                                "version": 1
                            },
                            "relationships": []
                        }
                    ],
                    "state": "published",
                    "chapterNumbersResetOnNewVolume": false,
                    "createdAt": "2019-08-25T15:36:52+00:00",
                    "updatedAt": "2026-04-23T22:13:34+00:00",
                    "version": 42,
                    "availableTranslatedLanguages": [
                        "en",
                        "it",
                        "id",
                        "pt-br",
                        "vi",
                        "de",
                        "fr",
                        "es-la",
                        "ko",
                        "ru",
                        "uk"
                    ],
                    "latestUploadedChapter": "839e1024-9031-48eb-a726-0cd8c137b23b"
                }
            },
            {
                "id": "8f627d2f-0fc9-4d29-9157-f955c148cbac",
                "type": "user",
                "attributes": {
                    "username": "Dead-chan",
                    "roles": [
                        "ROLE_GROUP_LEADER",
                        "ROLE_GROUP_MEMBER",
                        "ROLE_MEMBER",
                        "ROLE_POWER_UPLOADER",
                        "ROLE_SUPPORTER"
                    ],
                    "version": 1163
                }
            }
        ]
    }
}
```

再用里面的ID，访问这个接口（也就是aggregate接口），获取到每个章节的ID信息：
https://api.mangadex.org/manga/d8f1d7da-8bb1-407b-8be3-10ac2894d3c6/aggregate?translatedLanguage[]=en&groups[]=79071f17-c5a3-4624-8caa-b55c749c8705&groups[]=822eaeb8-9521-4a11-ac7e-d828e13179a4