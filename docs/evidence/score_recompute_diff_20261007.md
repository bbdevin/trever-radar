# 全範圍分數重算差異報告證據(2026-10-07)

> 決議:**不做** docs/20 Phase 2 歷史綜合分正式重算,Phase 2 以「重算不必要」結案(2026-10-07,Fable 決定,使用者已授權 Fable 決定)。本檔保存唯讀差異報告的摘要與工具原始輸出,不附 CSV。

## 摘要

- 工具:`pipeline/tools/score_recompute_diff.py`(唯讀,`mode=ro`),正式庫 2026-10-06 23:56 至 10-07 00:18 執行,約 15 分鐘,涵蓋 56 個日期(2026-07-06..2026-10-06)。
- 最近 5 日(試跑):3,712 列,6.1% 有變動;`final` 變動 81 列,mean |d| 0.08,max 10;未跨越 ≥65 門檻。
- 全 56 日:37,803 列,66.6% 有變動;`final` mean |d| 1.66,p95 9,max 36。
  - 門檻跨越:進榜 9、出榜 16。
  - 僅重算側有列 7,215;僅已存側有列 131。
  - 變動列依分項:theme 21,719;tech 5,970;branch 2,414(null↔value 3,092)。
- 差異全屬 look-ahead,不是 bug:今天的題材成員、事後回補的分點資料、09-04 adj_factor 修正、TPEx 缺口。
- 寫回會把「當日實際發布的內容」換成「今天會說的內容」,違反 docs/04 §12(前瞻記錄法)、STATUS 2026-09-24(不回補歷史)、docs/39 §3.8、docs/20 §4.1(不得改寫歷史 S code;`score_date` 會改寫 `reasons`)。
- 若使用者日後推翻:最小範圍為只對 2026-07-06 以 `--tech-source recompute` 重算,於週六備份後、持 DB 鎖、`import_logs` 記 dataset `scores-recompute`;絕不可對歷史跑 `compute-indicators --all`。

## 原始輸出:全範圍(`full120.log`,已省略 `tech NNN/` 進度行)

```text
score recompute diff: 56 dates 2026-07-06..2026-10-06, tech=recompute, list threshold final>=65
tech ready (561s)
[1/56] 2026-07-06 compared=951 changed=951 (8s, ETA 431s)
[2/56] 2026-07-15 compared=931 changed=552 (14s, ETA 378s)
[3/56] 2026-07-16 compared=610 changed=514 (20s, ETA 351s)
[4/56] 2026-07-17 compared=606 changed=479 (26s, ETA 338s)
[5/56] 2026-07-20 compared=605 changed=495 (32s, ETA 331s)
[6/56] 2026-07-21 compared=604 changed=559 (39s, ETA 322s)
[7/56] 2026-07-22 compared=594 changed=561 (45s, ETA 312s)
[8/56] 2026-07-23 compared=594 changed=512 (51s, ETA 304s)
[9/56] 2026-07-24 compared=593 changed=513 (56s, ETA 294s)
[10/56] 2026-07-27 compared=592 changed=544 (62s, ETA 286s)
[11/56] 2026-07-28 compared=584 changed=528 (68s, ETA 278s)
[12/56] 2026-07-29 compared=586 changed=530 (73s, ETA 269s)
[13/56] 2026-07-30 compared=590 changed=527 (79s, ETA 262s)
[14/56] 2026-07-31 compared=587 changed=515 (85s, ETA 256s)
[15/56] 2026-08-03 compared=586 changed=486 (92s, ETA 250s)
[16/56] 2026-08-04 compared=575 changed=486 (98s, ETA 245s)
[17/56] 2026-08-05 compared=565 changed=516 (104s, ETA 239s)
[18/56] 2026-08-06 compared=557 changed=557 (110s, ETA 232s)
[19/56] 2026-08-07 compared=558 changed=465 (116s, ETA 226s)
[20/56] 2026-08-10 compared=551 changed=551 (122s, ETA 219s)
[21/56] 2026-08-14 compared=539 changed=538 (128s, ETA 214s)
[22/56] 2026-08-17 compared=539 changed=526 (134s, ETA 207s)
[23/56] 2026-08-18 compared=538 changed=522 (140s, ETA 201s)
[24/56] 2026-08-19 compared=540 changed=540 (147s, ETA 196s)
[25/56] 2026-08-20 compared=626 changed=619 (154s, ETA 191s)
[26/56] 2026-08-21 compared=752 changed=685 (160s, ETA 184s)
[27/56] 2026-08-24 compared=544 changed=504 (166s, ETA 178s)
[28/56] 2026-08-25 compared=546 changed=499 (172s, ETA 172s)
[29/56] 2026-08-26 compared=751 changed=615 (177s, ETA 165s)
[30/56] 2026-08-27 compared=744 changed=631 (183s, ETA 159s)
[31/56] 2026-08-28 compared=746 changed=627 (189s, ETA 153s)
[32/56] 2026-08-31 compared=742 changed=532 (195s, ETA 146s)
[33/56] 2026-09-01 compared=748 changed=610 (200s, ETA 140s)
[34/56] 2026-09-02 compared=749 changed=633 (207s, ETA 134s)
[35/56] 2026-09-03 compared=747 changed=524 (213s, ETA 128s)
[36/56] 2026-09-04 compared=752 changed=571 (219s, ETA 121s)
[37/56] 2026-09-07 compared=754 changed=584 (224s, ETA 115s)
[38/56] 2026-09-08 compared=750 changed=580 (230s, ETA 109s)
[39/56] 2026-09-09 compared=744 changed=517 (236s, ETA 103s)
[40/56] 2026-09-10 compared=737 changed=454 (242s, ETA 97s)
[41/56] 2026-09-11 compared=732 changed=304 (250s, ETA 92s)
[42/56] 2026-09-14 compared=735 changed=234 (256s, ETA 85s)
[43/56] 2026-09-15 compared=728 changed=170 (262s, ETA 79s)
[44/56] 2026-09-16 compared=730 changed=250 (268s, ETA 73s)
[45/56] 2026-09-17 compared=729 changed=241 (274s, ETA 67s)
[46/56] 2026-09-18 compared=729 changed=514 (280s, ETA 61s)
[47/56] 2026-09-21 compared=735 changed=90 (287s, ETA 55s)
[48/56] 2026-09-22 compared=740 changed=575 (292s, ETA 49s)
[49/56] 2026-09-23 compared=749 changed=307 (298s, ETA 43s)
[50/56] 2026-09-24 compared=739 changed=41 (304s, ETA 36s)
[51/56] 2026-09-29 compared=738 changed=68 (310s, ETA 30s)
[52/56] 2026-09-30 compared=739 changed=70 (316s, ETA 24s)
[53/56] 2026-10-01 compared=733 changed=17 (323s, ETA 18s)
[54/56] 2026-10-02 compared=742 changed=117 (328s, ETA 12s)
[55/56] 2026-10-05 compared=745 changed=18 (334s, ETA 6s)
[56/56] 2026-10-06 compared=753 changed=4 (340s, ETA 0s)

rows compared (stored & recomputed): 37803
rows changed (any score field): 25172 (66.6%)
rows only stored (would no longer be scored): 131 (of which final>=65: 1)
rows only recomputed (would newly be scored): 7215 (of which final>=65: 4)
list threshold final>=65 crossings among compared rows: enter 9, exit 16 (the 40-row cap and the score_list_gate withholding are not modelled)

field                 n  changed  mean|d|  median   p95   max null<>val
final             37803    14701     1.66     0.0     9    36         0
branch_score      34710     2414     1.24     0.0    15    55      3092
warrant_score     29344      204     0.13     0.0     0    45         0
tech_score        36372     5970     2.39     0.0    15    80      1431
inst_score        36712      269     0.06     0.0     0    40         0
theme_score       37586    21719     1.87     1.0     8    60        29
risk_penalty      37803      303     0.08     0.0     0    23         0

top 20 movers by |final diff| (stored -> recomputed):
date       stock       final      tech    branch   warrant      inst     theme     risk
2026-08-19 3653        54>18     60>60      na>5     35>35     na>na     81>71    0>-15
2026-08-26 2221        52>16     70>60     45>15     na>na     45>45     51>50    0>-20
2026-08-14 6949        19>53     40>65     25>55     na>na     30>30     62>59    -15>0
2026-08-19 6024        16>49      0>40     na>55     na>na     na>na     49>47      0>0
2026-08-20 2204        36>68     35>90     30>70     na>na     30>30     72>73      0>0
2026-08-21 5321        48>16     75>35     35>15     na>na     30>30     67>79    0>-15
2026-07-06 5522        54>23      na>0     na>15     na>na     55>55     52>52      0>0
2026-08-19 2535        48>17     40>25      na>0     na>na     na>na     65>61      0>0
2026-08-19 9921        56>25     50>25      na>0     40>40     na>na     99>80      0>0
2026-08-14 2351         5>35     10>30      0>55       0>0     30>30     64>54     -8>0
2026-08-19 2605        74>44     70>70      na>0     65>65     na>na   100>100      0>0
2026-08-14 3406         8>37     50>40      0>25     55>55     30>30     55>50    -23>0
2026-08-19 2903        51>22     35>35      na>0     na>na     na>na     82>72      0>0
2026-08-19 7689        17>46       0>0     na>70     na>na     na>na     51>51      0>0
2026-08-14 1303         8>36     30>40      0>30     20>20     30>30     89>86    -15>0
2026-08-14 1504        20>48     60>65      0>45     20>40     30>30     73>71     -8>0
2026-08-14 6831        10>38     15>45      0>35     10>30     30>30     90>63     -8>0
2026-08-19 6141        59>31     65>65     na>35     na>na     na>na     46>44    0>-15
2026-08-14 6153         8>35     10>25      0>35     na>na     30>30     67>59     -8>0
2026-09-22 2030        46>19     65>65      na>0     na>na     30>30   100>100  -15>-15

changed rows CSV: /out/full120.csv
```n
## 原始輸出:最近 5 日試跑(`trial5.log`)

```text
score recompute diff: 5 dates 2026-09-30..2026-10-06, tech=recompute, list threshold final>=65
tech 200/2052 stocks (39s, ETA 358s)
tech 400/2052 stocks (78s, ETA 321s)
tech 600/2052 stocks (118s, ETA 285s)
tech 800/2052 stocks (157s, ETA 245s)
tech 1000/2052 stocks (194s, ETA 204s)
tech 1200/2052 stocks (232s, ETA 165s)
tech 1400/2052 stocks (272s, ETA 127s)
tech 1600/2052 stocks (311s, ETA 88s)
tech 1800/2052 stocks (349s, ETA 49s)
tech 2000/2052 stocks (388s, ETA 10s)
tech 2052/2052 stocks (399s, ETA 0s)
tech ready (399s)
[1/5] 2026-09-30 compared=739 changed=70 (7s, ETA 28s)
[2/5] 2026-10-01 compared=733 changed=17 (13s, ETA 19s)
[3/5] 2026-10-02 compared=742 changed=117 (18s, ETA 12s)
[4/5] 2026-10-05 compared=745 changed=18 (24s, ETA 6s)
[5/5] 2026-10-06 compared=753 changed=4 (30s, ETA 0s)

rows compared (stored & recomputed): 3712
rows changed (any score field): 226 (6.1%)
rows only stored (would no longer be scored): 0 (of which final>=65: 0)
rows only recomputed (would newly be scored): 0 (of which final>=65: 0)
list threshold final>=65 crossings among compared rows: enter 0, exit 0 (the 40-row cap and the score_list_gate withholding are not modelled)

field                 n  changed  mean|d|  median   p95   max null<>val
final              3712       81     0.08     0.0     0    10         0
branch_score       3712       33     0.14     0.0     0    20         0
warrant_score      3010        0     0.00     0.0     0     0         0
tech_score         3712       18     0.05     0.0     0    10         0
inst_score         3712        3     0.02     0.0     0    25         0
theme_score        3688      177     0.08     0.0     0    17         0
risk_penalty       3712        1     0.00     0.0     0    10         0

top 20 movers by |final diff| (stored -> recomputed):
date       stock       final      tech    branch   warrant      inst     theme     risk
2026-10-01 6691        43>33     60>60     15>15     55>55     55>55     69>69    0>-10
2026-09-30 3591        30>39     60>60     25>45     na>na     25>25     62>61    -8>-8
2026-10-02 1736        31>22     15>15     45>25     na>na       5>5     53>53      0>0
2026-10-02 4976        28>19       0>0     35>15     na>na     30>30     57>57      0>0
2026-09-30 6472        28>36     40>40     30>50       0>0     30>30     55>55      0>0
2026-10-02 5608        48>56     35>35     50>70     na>na     45>45     68>68      0>0
2026-09-30 2352        34>27     55>55     35>15       0>0     30>30     59>59      0>0
2026-09-30 3441        13>20     25>25      0>15     na>na       5>5     48>48      0>0
2026-09-30 3596         4>11       0>0     15>35       0>0       5>5     56>56    -8>-8
2026-09-30 5292        34>27     35>35     45>25       0>0     30>30     65>67      0>0
2026-09-30 5474        36>29     40>40     35>15     30>30     30>30     56>56      0>0
2026-09-30 6271        24>31     40>40     25>45       0>0       5>5     61>61      0>0
2026-10-01 3515        31>24     15>15     50>30       0>0     30>30     60>60      0>0
2026-10-01 8383        22>29     30>30     25>45       0>0       5>5     69>69      0>0
2026-10-02 6477        16>23     10>10      0>15     na>na     30>30     65>65      0>0
2026-10-02 6830        28>21     20>20     45>25       0>0     15>15     59>58      0>0
2026-10-02 6472         15>9     20>20      15>0       0>0       5>5     47>47      0>0
2026-10-02 6712        13>19     40>40      0>15       0>0       5>5     46>46      0>0
2026-10-02 7765        13>19     25>25      0>15     na>na       5>5     44>44      0>0
2026-10-02 8464         7>13       0>0      0>15       0>0     20>20     44>44      0>0

changed rows CSV: /out/trial5.csv
```n